"""Service mode: cron scheduling, real-time watcher, and/or web UI.

Uses APScheduler for cron-based periodic scans, PlexWatcher
for WebSocket-based real-time media change detection, and optionally
a FastAPI web dashboard for remote monitoring and manual scans.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plexchtsubs.config import Config

logger = logging.getLogger(__name__)


def _parse_cron(expr: str) -> dict:
    """Parse a standard 5-field cron expression into APScheduler kwargs.

    Format: minute hour day month day_of_week
    Example: '0 3 * * 0' → every Sunday at 03:00
    """
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression '{expr}': expected 5 fields, got {len(parts)}")

    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


def run_service(config: Config) -> None:
    """Start persistent service with cron scheduling, watcher, and/or web UI."""
    from plexapi.server import PlexServer

    from plexchtsubs.history import ScanHistoryStore

    # Connect once to verify credentials
    print(f"Connecting to {config.plex_url} ...")
    try:
        plex = PlexServer(config.plex_url, config.plex_token)
    except Exception as e:
        print(f"Error: Failed to connect to Plex server: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Connected: {plex.friendlyName} (v{plex.version})")

    # History store (shared by cron, watcher, and web)
    history = ScanHistoryStore()

    watcher = None
    scheduler = None
    stop_event = threading.Event()

    # --- History callback for watcher batches ---
    def _on_batch_complete(stats, duration):
        history.record(
            duration=duration,
            total=stats.total,
            changed=stats.changed,
            skipped=stats.skipped,
            fallback_used=stats.fallback_used,
            errors=stats.errors,
            dry_run=config.dry_run,
            trigger="watcher",
        )

    # --- Watcher (if enabled) ---
    if config.watch_enabled:
        try:
            from plexchtsubs.watcher import PlexWatcher
        except ImportError:
            print("Error: websocket-client is required for watch mode.", file=sys.stderr)
            print("Install it with: pip install websocket-client", file=sys.stderr)
            sys.exit(1)
        watcher = PlexWatcher(plex, config, on_batch_complete=_on_batch_complete)
        watcher.start()
        print(f"Watcher started (debounce: {config.watch_debounce}s)")

    # --- Cron scheduler (if enabled) ---
    if config.schedule_enabled:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            print("Error: apscheduler is required for scheduled mode.", file=sys.stderr)
            print("Install it with: pip install apscheduler", file=sys.stderr)
            sys.exit(1)

        from plexchtsubs.scanner import scan_library

        cron_kwargs = _parse_cron(config.schedule_cron)
        trigger = CronTrigger(**cron_kwargs)

        def _on_cron_complete(stats, duration):
            history.record(
                duration=duration,
                total=stats.total,
                changed=stats.changed,
                skipped=stats.skipped,
                fallback_used=stats.fallback_used,
                errors=stats.errors,
                dry_run=config.dry_run,
                trigger="cron",
            )

        def _job():
            """Reconnect and scan (connection may go stale between runs)."""
            try:
                p = PlexServer(config.plex_url, config.plex_token)
                logger.info("Scheduled scan starting...")
                scan_library(p, config, on_complete=_on_cron_complete)
            except Exception as e:
                logger.error("Scheduled scan failed: %s", e)

        scheduler = BackgroundScheduler()
        scheduler.add_job(_job, trigger, id="plexchtsubs_scan", name="PlexPreferCHTSubs scan")
        scheduler.start()

        print(f"Scheduler started. Cron: {config.schedule_cron}")

        # Run initial scan immediately
        _job()

    # --- Graceful shutdown ---
    def _shutdown(signum, frame):
        logger.info("Received signal %s, shutting down...", signum)
        if watcher:
            watcher.stop()
        if scheduler:
            scheduler.shutdown(wait=False)
        stop_event.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # --- Web UI (if enabled) ---
    if config.web_enabled:
        try:
            import uvicorn

            from plexchtsubs.web import create_app
        except ImportError:
            print("Error: fastapi and uvicorn are required for web UI.", file=sys.stderr)
            print("Install them with: pip install fastapi uvicorn", file=sys.stderr)
            sys.exit(1)

        app = create_app(plex, config, history=history, watcher=watcher)
        print(f"Web UI: http://{config.web_host}:{config.web_port}")
        print("Press Ctrl+C to stop.\n")

        # uvicorn handles SIGINT/SIGTERM and becomes the main blocking loop
        uvicorn.run(
            app,
            host=config.web_host,
            port=config.web_port,
            log_level="warning",
        )
        # When uvicorn exits, clean up
        _shutdown(signal.SIGTERM, None)
    else:
        print("Press Ctrl+C to stop.\n")

        # Block main thread until shutdown signal.
        # Use a polling loop because on Windows, Event.wait() without timeout
        # cannot be interrupted by signals (Ctrl+C).
        try:
            while not stop_event.is_set():
                stop_event.wait(timeout=1.0)
        except KeyboardInterrupt:
            _shutdown(signal.SIGINT, None)
