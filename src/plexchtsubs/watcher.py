"""Real-time Plex media watcher using WebSocket Alert Listener.

Monitors Plex timeline events for new/updated media items and
processes their subtitles automatically with debounce batching.
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from plexapi.server import PlexServer
    from plexchtsubs.config import Config

logger = logging.getLogger(__name__)

# Timeline entry type codes from Plex
_TYPE_MOVIE = 1
_TYPE_EPISODE = 4
_VALID_TYPES = frozenset({_TYPE_MOVIE, _TYPE_EPISODE})

# Timeline state=5 means "item finished processing"
_STATE_DONE = 5


class PlexWatcher:
    """WebSocket-based real-time watcher for Plex media changes.

    Listens for timeline events, batches item IDs with a debounce timer,
    then processes each item's subtitles using the existing scanner logic.
    Auto-reconnects with exponential backoff on disconnect.
    """

    _BASE_DELAY = 2.0
    _MAX_DELAY = 300.0
    _BACKOFF_FACTOR = 2.0

    def __init__(
        self, plex: PlexServer, config: Config, *, on_batch_complete=None,
    ) -> None:
        self._plex = plex
        self._config = config
        self._on_batch_complete = on_batch_complete
        self._pending: set[int] = set()
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._listener = None
        self._running = False
        self._stop_event = threading.Event()
        self._reconnect_delay = self._BASE_DELAY

    def start(self) -> None:
        """Start the alert listener (non-blocking, runs in daemon thread)."""
        self._stop_event.clear()
        self._running = True
        self._listener = self._plex.startAlertListener(
            callback=self._on_alert,
            callbackError=self._on_error,
        )
        logger.info("Watcher connected to %s", self._config.plex_url)

    def stop(self) -> None:
        """Stop the alert listener and cancel any pending debounce timer."""
        self._running = False
        self._stop_event.set()
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

    @property
    def is_running(self) -> bool:
        return self._running

    def _on_alert(self, data: dict) -> None:
        """Callback for plexapi AlertListener — filters and collects item IDs."""
        if data.get("type") != "timeline":
            return

        new_ids: list[int] = []
        for entry in data.get("TimelineEntry", []):
            state = entry.get("state")
            item_type = entry.get("type")
            item_id = entry.get("itemID")

            if state == _STATE_DONE and item_type in _VALID_TYPES and item_id:
                new_ids.append(int(item_id))

        if not new_ids:
            return

        with self._lock:
            self._pending.update(new_ids)
            logger.debug("Watcher: +%d IDs (pending: %d)", len(new_ids), len(self._pending))
            self._reset_timer()

    def _on_error(self, error: Exception) -> None:
        """Callback for AlertListener errors — triggers auto-reconnect."""
        if not self._running:
            return
        logger.warning("Watcher connection lost: %s", error)
        self._running = False
        thread = threading.Thread(target=self._reconnect, daemon=True)
        thread.start()

    def _reset_timer(self) -> None:
        """Cancel existing debounce timer and start a new one. Called under _lock."""
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(self._config.watch_debounce, self._flush_pending)
        self._timer.daemon = True
        self._timer.start()

    def _flush_pending(self) -> None:
        """Process all accumulated item IDs as a batch."""
        with self._lock:
            if not self._pending:
                return
            batch = list(self._pending)
            self._pending.clear()
            self._timer = None

        n = len(batch)
        print(f"\n[Watch] Detected {n} updated item{'s' if n != 1 else ''}, processing...")

        from plexchtsubs.display import ScanStats, print_header, print_summary
        from plexchtsubs.scanner import _process_item

        print_header("Watcher Batch")
        stats = ScanStats()
        stats_lock = threading.Lock()
        start = time.time()

        with concurrent.futures.ThreadPoolExecutor(max_workers=self._config.workers) as pool:
            futures = [
                pool.submit(_process_item, self._plex, item_id, self._config, stats, stats_lock)
                for item_id in batch
            ]
            concurrent.futures.wait(futures)

        duration = time.time() - start
        print_summary(stats, duration)

        if self._on_batch_complete is not None:
            try:
                self._on_batch_complete(stats, duration)
            except Exception:
                logger.debug("on_batch_complete callback error", exc_info=True)

    def _reconnect(self) -> None:
        """Auto-reconnect with exponential backoff."""
        while not self._stop_event.is_set():
            logger.info("Watcher reconnecting in %.0fs...", self._reconnect_delay)
            self._stop_event.wait(self._reconnect_delay)
            if self._stop_event.is_set():
                return

            try:
                from plexapi.server import PlexServer
                self._plex = PlexServer(self._config.plex_url, self._config.plex_token)
                self.start()
                self._reconnect_delay = self._BASE_DELAY
                logger.info("Watcher reconnected successfully.")
                return
            except Exception as e:
                logger.error("Watcher reconnect failed: %s", e)
                self._reconnect_delay = min(
                    self._reconnect_delay * self._BACKOFF_FACTOR,
                    self._MAX_DELAY,
                )
