"""Built-in scheduler for running scans on a cron schedule.

Uses APScheduler for lightweight, in-process scheduling.
The process stays alive and triggers scan_library() on the configured cron.
"""

from __future__ import annotations

import logging
import signal
import sys
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


def run_scheduled(config: Config) -> None:
    """Start the scheduler and block until interrupted."""
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        print("Error: apscheduler is required for scheduled mode.", file=sys.stderr)
        print("Install it with: pip install apscheduler", file=sys.stderr)
        sys.exit(1)

    from plexapi.server import PlexServer
    from plexchtsubs.scanner import scan_library

    # Connect once to verify credentials
    print(f"Connecting to {config.plex_url} ...")
    try:
        plex = PlexServer(config.plex_url, config.plex_token)
    except Exception as e:
        print(f"Error: Failed to connect to Plex server: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Connected: {plex.friendlyName} (v{plex.version})")

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

    scheduler = BlockingScheduler()
    scheduler.add_job(_job, trigger, id="plexchtsubs_scan", name="PlexPreferCHTSubs scan")

    # Graceful shutdown on SIGTERM (Docker stop)
    def _shutdown(signum, frame):
        logger.info("Received signal %s, shutting down scheduler...", signum)
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    print(f"\nScheduler started. Cron: {config.schedule_cron}")
    print("Press Ctrl+C to stop.\n")

    # Run once immediately on startup, then follow cron
    _job()

    scheduler.start()
