"""Configuration management with layered resolution.

Priority (highest first):
    1. CLI arguments (argparse namespace)
    2. Environment variables (PLEX_URL, PLEX_TOKEN, etc.)
    3. Config file (config.yaml)
    4. Built-in defaults
    5. Interactive prompt (only if running in a TTY and token is still missing)
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

VALID_FALLBACKS = ("skip", "english", "chs", "none")

_DEFAULTS = {
    "plex_url": "http://localhost:32400",
    "plex_token": None,
    "scan_range_days": 30,
    "fallback": "skip",
    "force_overwrite": False,
    "workers": 8,
    "dry_run": False,
    "verbose": False,
    "log_file": None,
    "watch_enabled": False,
    "watch_debounce": 5.0,
}


@dataclass
class Config:
    plex_url: str = _DEFAULTS["plex_url"]
    plex_token: Optional[str] = None
    scan_range_days: Optional[int] = _DEFAULTS["scan_range_days"]
    fallback: str = _DEFAULTS["fallback"]
    force_overwrite: bool = _DEFAULTS["force_overwrite"]
    workers: int = _DEFAULTS["workers"]
    dry_run: bool = _DEFAULTS["dry_run"]
    verbose: bool = _DEFAULTS["verbose"]
    log_file: Optional[str] = None
    # Schedule (Phase 2)
    schedule_enabled: bool = False
    schedule_cron: str = "0 3 * * *"  # default: daily at 3 AM
    # Watch mode (real-time WebSocket listener)
    watch_enabled: bool = False
    watch_debounce: float = 5.0  # seconds to batch events before processing


def _load_yaml(path: Path) -> dict:
    """Load a YAML config file, returning {} on any error."""
    try:
        import yaml
    except ImportError:
        logger.debug("PyYAML not installed, skipping config file.")
        return {}

    if not path.is_file():
        logger.debug("Config file not found: %s", path)
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning("Failed to parse config file %s: %s", path, e)
        return {}


def _flatten_yaml(data: dict) -> dict:
    """Flatten nested YAML structure to flat config keys."""
    flat = {}
    plex = data.get("plex", {})
    if isinstance(plex, dict):
        if "url" in plex:
            flat["plex_url"] = plex["url"]
        if "token" in plex:
            flat["plex_token"] = plex["token"]

    scan = data.get("scan", {})
    if isinstance(scan, dict):
        if "range_days" in scan:
            flat["scan_range_days"] = scan["range_days"]
        if "fallback" in scan:
            flat["fallback"] = scan["fallback"]
        if "force_overwrite" in scan:
            flat["force_overwrite"] = scan["force_overwrite"]

    if "workers" in data:
        flat["workers"] = data["workers"]

    schedule = data.get("schedule", {})
    if isinstance(schedule, dict):
        if "enabled" in schedule:
            flat["schedule_enabled"] = bool(schedule["enabled"])
        if "cron" in schedule:
            flat["schedule_cron"] = schedule["cron"]

    watch = data.get("watch", {})
    if isinstance(watch, dict):
        if "enabled" in watch:
            flat["watch_enabled"] = bool(watch["enabled"])
        if "debounce" in watch:
            flat["watch_debounce"] = float(watch["debounce"])

    return flat


def _from_env() -> dict:
    """Read config from environment variables."""
    env_map = {
        "PLEX_URL": "plex_url",
        "PLEX_TOKEN": "plex_token",
        "SCAN_RANGE_DAYS": "scan_range_days",
        "FALLBACK": "fallback",
        "FORCE_OVERWRITE": "force_overwrite",
        "WORKERS": "workers",
        "SCHEDULE_ENABLED": "schedule_enabled",
        "SCHEDULE_CRON": "schedule_cron",
        "WATCH_ENABLED": "watch_enabled",
        "WATCH_DEBOUNCE": "watch_debounce",
    }
    result = {}
    for env_key, config_key in env_map.items():
        val = os.environ.get(env_key)
        if val is None:
            continue
        # Type coercion
        if config_key == "scan_range_days":
            result[config_key] = int(val) if val else None
        elif config_key == "workers":
            result[config_key] = int(val)
        elif config_key in ("force_overwrite", "schedule_enabled", "watch_enabled"):
            result[config_key] = val.lower() in ("1", "true", "yes")
        elif config_key == "watch_debounce":
            result[config_key] = float(val)
        else:
            result[config_key] = val
    return result


def _from_cli(args) -> dict:
    """Extract config from argparse namespace, ignoring None (unset) values."""
    mapping = {
        "plex_url": "plex_url",
        "plex_token": "plex_token",
        "scan_range": "scan_range_days",
        "fallback": "fallback",
        "force": "force_overwrite",
        "workers": "workers",
        "dry_run": "dry_run",
        "verbose": "verbose",
        "log_file": "log_file",
        "schedule_enabled": "schedule_enabled",
        "schedule_cron": "schedule_cron",
        "watch_enabled": "watch_enabled",
        "watch_debounce": "watch_debounce",
    }
    result = {}
    for arg_name, config_key in mapping.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            result[config_key] = val
    return result


def _prompt_token() -> Optional[str]:
    """Interactively ask for token if running in a TTY."""
    if not sys.stdin.isatty():
        return None
    print("\nPlex token is required.")
    print("How to get your token: https://www.plexopedia.com/plex-media-server/general/plex-token/\n")
    try:
        token = input("Enter your Plex token: ").strip()
        return token if token else None
    except (EOFError, KeyboardInterrupt):
        return None


def load_config(cli_args=None, config_path: Optional[Path] = None) -> Config:
    """Build a Config by merging all layers.

    Args:
        cli_args: argparse.Namespace or None.
        config_path: Explicit path to config.yaml, or auto-detect.
    """
    merged = dict(_DEFAULTS)

    # Layer 3: Config file
    if config_path is None:
        config_path = Path("config.yaml")
    yaml_data = _load_yaml(config_path)
    yaml_flat = _flatten_yaml(yaml_data)
    for k, v in yaml_flat.items():
        if v is not None:
            merged[k] = v

    # Layer 2: Environment variables
    env_data = _from_env()
    for k, v in env_data.items():
        if v is not None:
            merged[k] = v

    # Layer 1: CLI arguments (highest priority)
    if cli_args is not None:
        cli_data = _from_cli(cli_args)
        for k, v in cli_data.items():
            merged[k] = v

    # Layer 5: Interactive fallback for token
    if not merged.get("plex_token"):
        token = _prompt_token()
        if token:
            merged["plex_token"] = token

    # Validate fallback value
    fb = merged.get("fallback", "skip")
    if fb not in VALID_FALLBACKS:
        logger.warning("Invalid fallback '%s', using 'skip'.", fb)
        merged["fallback"] = "skip"

    # scan_range_days: 0 means full scan → None
    if merged.get("scan_range_days") == 0:
        merged["scan_range_days"] = None

    return Config(**{k: v for k, v in merged.items() if k in Config.__dataclass_fields__})
