"""Service mode: cron scheduling and/or real-time watcher.

Uses APScheduler for cron-based periodic scans and PlexWatcher
for WebSocket-based real-time media change detection.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plexchtsubs.config import Config

logger = logging.getLogger(__name__)


def _parse_cron(expr: str) -> dict:
    """Parse a standard 5-field cron expression into APScheduler kwargs.

    Format: minute hour day month day_of_week
    Example: '0 3 * * *' → every day at 03:00
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
    """Start persistent service with cron scheduling and/or real-time watcher."""
    from plexapi.server import PlexServer

    # Connect once to verify credentials
    print(f"Connecting to {config.plex_url} ...")
    try:
        plex = PlexServer(config.plex_url, config.plex_token)
    except Exception as e:
        print(f"Error: Failed to connect to Plex server: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Connected: {plex.friendlyName} (v{plex.version})")

    watcher = None
    scheduler = None
    stop_event = threading.Event()

    # --- Watcher (if enabled) ---
    if config.watch_enabled:
        try:
            from plexchtsubs.watcher import PlexWatcher
        except ImportError:
            print("Error: websocket-client is required for watch mode.", file=sys.stderr)
            print("Install it with: pip install websocket-client", file=sys.stderr)
            sys.exit(1)
        watcher = PlexWatcher(plex, config)
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

        def _job():
            """Reconnect and scan (connection may go stale between runs)."""
            try:
                p = PlexServer(config.plex_url, config.plex_token)
                logger.info("Scheduled scan starting...")
                scan_library(p, config)
            except Exception as e:
                logger.error("Scheduled scan failed: %s", e)

        scheduler = BackgroundScheduler()
        scheduler.add_job(_job, trigger, id="plexchtsubs_scan", name="PlexPreferCHTSubs scan")
        scheduler.start()

        print(f"Scheduler started. Cron: {config.schedule_cron}")

        # Run initial scan immediately
        _job()

    print("Press Ctrl+C to stop.\n")

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

    # Block main thread until shutdown signal
    stop_event.wait()
