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
        help="Strategy when no CHT subtitle found (default: skip)",
    )
    scan.add_argument("--force", action="store_true", default=None, help="Force overwrite existing selections")
    scan.add_argument("--workers", type=int, help="Number of parallel threads (default: 8)")

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


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    config_path = Path(args.config_file) if args.config_file else None
    config = load_config(cli_args=args, config_path=config_path)
    _setup_logging(config)

    if not config.plex_token:
        print("Error: Plex token is required. Use --plex-token, PLEX_TOKEN env var, or config.yaml.", file=sys.stderr)
        sys.exit(1)

    # Import here to avoid import error when plexapi is not installed but --help is requested
    from plexapi.server import PlexServer
    from plexchtsubs.scanner import scan_library

    print(f"\nPlexPreferCHTSubs v{__version__}")
    print(f"Connecting to {config.plex_url} ...")

    try:
        plex = PlexServer(config.plex_url, config.plex_token)
    except Exception as e:
        print(f"Error: Failed to connect to Plex server: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Connected: {plex.friendlyName} (v{plex.version})")
    scan_library(plex, config)
