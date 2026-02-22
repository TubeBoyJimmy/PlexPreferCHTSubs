"""CLI entry point for PlexPreferCHTSubs."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from plexchtsubs import __version__
from plexchtsubs.config import VALID_FALLBACKS, load_config


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="plexchtsubs",
        description="Set Traditional Chinese (繁體中文) as the preferred subtitle in Plex.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    conn = p.add_argument_group("connection")
    conn.add_argument("--plex-url", help="Plex server URL (default: http://localhost:32400)")
    conn.add_argument("--plex-token", help="Plex authentication token")
    conn.add_argument("--config", dest="config_file", help="Path to config.yaml")

    scan = p.add_argument_group("scan options")
    scan.add_argument(
        "--scan-range", type=int, metavar="DAYS",
        help="Scan items updated within N days (0 = full scan, default: 30)",
    )
    scan.add_argument(
        "--fallback", choices=VALID_FALLBACKS,
        help="Strategy when no CHT subtitle found (default: chs)",
    )
    scan.add_argument("--force", action="store_true", default=None, help="Force overwrite existing selections")
    scan.add_argument("--workers", type=int, help="Number of parallel threads (default: 8)")

    sched = p.add_argument_group("schedule")
    sched.add_argument(
        "--schedule", action="store_true", default=None,
        help="Run as a persistent service with cron scheduling (requires apscheduler)",
    )
    sched.add_argument("--cron", help='Cron expression for schedule (default: "0 3 * * 0", weekly Sun 3AM)')

    watch = p.add_argument_group("watch")
    watch.add_argument(
        "--watch", action="store_true", default=None,
        help="Enable real-time watcher via WebSocket (no Plex Pass required)",
    )
    watch.add_argument(
        "--no-watch", action="store_true", default=None,
        help="Disable watcher even if enabled in config",
    )
    watch.add_argument(
        "--watch-debounce", type=float, metavar="SECONDS",
        help="Debounce delay for watcher batching (default: 5.0)",
    )

    web = p.add_argument_group("web ui")
    web.add_argument(
        "--web", action="store_true", default=None,
        help="Enable web UI dashboard (default port: 9527)",
    )
    web.add_argument(
        "--web-port", type=int, metavar="PORT",
        help="Web UI port (default: 9527)",
    )

    output = p.add_argument_group("output")
    output.add_argument("--dry-run", action="store_true", default=None, help="Preview changes without applying")
    output.add_argument("--log-file", help="Write logs to file")
    output.add_argument("-v", "--verbose", action="store_true", default=None, help="Verbose output")

    return p


def _setup_logging(config) -> None:
    level = logging.DEBUG if config.verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if config.log_file:
        handlers.append(logging.FileHandler(config.log_file, encoding="utf-8"))
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s", handlers=handlers)
    # Suppress noisy HTTP debug logs from urllib3/requests
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Map --schedule and --cron to config fields
    if getattr(args, "schedule", None):
        args.schedule_enabled = True
    else:
        args.schedule_enabled = None
    if getattr(args, "cron", None):
        args.schedule_cron = args.cron
    else:
        args.schedule_cron = None

    # Map --watch/--no-watch to config field
    if getattr(args, "watch", None):
        args.watch_enabled = True
    elif getattr(args, "no_watch", None):
        args.watch_enabled = False
    else:
        args.watch_enabled = None
    if getattr(args, "watch_debounce", None) is not None:
        pass  # already set on args
    else:
        args.watch_debounce = None

    # Map --web/--web-port to config fields
    if getattr(args, "web", None):
        args.web_enabled = True
    else:
        args.web_enabled = None
    if getattr(args, "web_port", None) is not None:
        pass  # already set on args
    else:
        args.web_port = None

    config_path = Path(args.config_file) if args.config_file else None
    config = load_config(cli_args=args, config_path=config_path)
    _setup_logging(config)

    # --schedule implies --watch unless explicitly --no-watch
    if config.schedule_enabled and args.watch_enabled is None:
        config.watch_enabled = True

    if not config.plex_token:
        print("Error: Plex token is required. Use --plex-token, PLEX_TOKEN env var, or config.yaml.", file=sys.stderr)
        sys.exit(1)

    print(f"\nPlexPreferCHTSubs v{__version__}")

    # Service mode: schedule, watch, and/or web
    if config.schedule_enabled or config.watch_enabled or config.web_enabled:
        from plexchtsubs.scheduler import run_service
        run_service(config)
        return

    # One-shot mode: scan once and exit
    from plexapi.server import PlexServer
    from plexchtsubs.scanner import scan_library

    print(f"Connecting to {config.plex_url} ...")

    try:
        plex = PlexServer(config.plex_url, config.plex_token)
    except Exception as e:
        print(f"Error: Failed to connect to Plex server: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Connected: {plex.friendlyName} (v{plex.version})")
    scan_library(plex, config)
