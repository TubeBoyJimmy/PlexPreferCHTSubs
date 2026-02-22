"""Plex library scanning and subtitle setting logic."""

from __future__ import annotations

import logging
import threading
import time
import concurrent.futures
from datetime import datetime, timedelta
from typing import Optional, Union

import requests
from plexapi.server import PlexServer

from plexchtsubs.config import Config
from plexchtsubs.detector import (
    SubtitleCategory,
    SubtitleInfo,
    SubtitleResult,
    classify,
    select_best,
)
from plexchtsubs.display import (
    Color,
    RowData,
    ScanStats,
    print_header,
    print_row,
    print_summary,
)

logger = logging.getLogger(__name__)
_print_lock = threading.Lock()


# ---------------------------------------------------------------------------
# HTTP retry helper
# ---------------------------------------------------------------------------

def _put_with_retry(
    url: str,
    headers: dict,
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    timeout: float = 15.0,
) -> requests.Response:
    """PUT request with exponential backoff retry.

    Retries on ConnectionError, Timeout, and HTTP 5xx.
    Does NOT retry on 4xx (client error).
    """
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.put(url, headers=headers, timeout=timeout)
            if resp.status_code < 500:
                return resp
            last_exc = requests.HTTPError(
                f"HTTP {resp.status_code}", response=resp
            )
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e

        if attempt < max_retries:
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "PUT %s failed (attempt %d/%d), retrying in %.1fs: %s",
                url, attempt + 1, max_retries + 1, delay, last_exc,
            )
            time.sleep(delay)

    raise last_exc


# ---------------------------------------------------------------------------
# Convert plexapi stream objects → our SubtitleInfo dataclass
# ---------------------------------------------------------------------------

def _to_subtitle_info(stream) -> SubtitleInfo:
    """Convert a plexapi SubtitleStream to our decoupled SubtitleInfo."""
    return SubtitleInfo(
        stream_id=stream.id,
        title=getattr(stream, "title", None),
        language_code=getattr(stream, "languageCode", None),
        language=getattr(stream, "language", None),
        forced=getattr(stream, "forced", False),
        selected=getattr(stream, "selected", False),
        codec=getattr(stream, "codec", None),
        key=getattr(stream, "key", None),
    )


# ---------------------------------------------------------------------------
# Content analysis helpers
# ---------------------------------------------------------------------------

# Image-based subtitle codecs — cannot be text-analyzed.
_IMAGE_CODECS = frozenset({"pgs", "hdmv_pgs_subtitle", "vobsub", "dvd_subtitle", "dvdsub"})


def _fetch_subtitle_content(
    plex_url: str, plex_token: str, info: SubtitleInfo, max_bytes: int = 50_000,
) -> Optional[str]:
    """Download subtitle text content for character-frequency analysis.

    Returns decoded text, or None if the stream has no download key,
    is image-based, or the download fails.
    """
    if not info.key:
        return None
    if info.codec and info.codec.lower() in _IMAGE_CODECS:
        return None

    url = f"{plex_url}{info.key}"
    headers = {"X-Plex-Token": plex_token}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        raw = resp.content[:max_bytes]
        for enc in ("utf-8", "utf-8-sig", "big5", "gb18030"):
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return None
    except Exception as e:
        logger.debug("Failed to fetch subtitle content for stream %d: %s", info.stream_id, e)
        return None


# ---------------------------------------------------------------------------
# Process a single media item (movie or episode)
# ---------------------------------------------------------------------------

def _process_item(
    plex: PlexServer,
    item_key: Union[str, int],
    config: Config,
    stats: ScanStats,
    stats_lock: threading.Lock,
) -> None:
    """Evaluate and optionally set the subtitle for one media item."""
    try:
        video = plex.fetchItem(item_key)
        video.reload()
    except Exception as e:
        logger.error("Failed to load item %s: %s", item_key, e)
        with stats_lock:
            stats.errors += 1
        return

    # Build display title early (used in both skip and process paths)
    if video.type == "episode":
        display_title = f"{video.grandparentTitle} S{video.seasonNumber:02d}E{video.index:02d}"
        year_str = str(video.year) if video.year else ""
    else:
        display_title = str(video.title)
        year_str = str(video.year) if video.year else ""

    streams = [_to_subtitle_info(s) for s in video.subtitleStreams()]

    # No subtitle streams at all (e.g., burned-in / hardcoded subs only) → skip
    if not streams:
        logger.debug("No subtitle streams: %s", display_title)
        with stats_lock:
            stats.total += 1
            stats.skipped += 1
        return

    # Content analysis: fetch subtitle text for unknown Chinese streams
    content_map: dict[int, str] = {}
    for s in streams:
        quick = classify(s)
        if quick.category == SubtitleCategory.UNKNOWN_ZH and s.key:
            text = _fetch_subtitle_content(config.plex_url, config.plex_token, s)
            if text:
                content_map[s.stream_id] = text
                logger.debug("Content analysis for %s stream %d: %d bytes",
                             display_title, s.stream_id, len(text))

    result = select_best(streams, fallback=config.fallback, content_map=content_map)

    # Case 1: No result (fallback=skip or no matching subtitle at all)
    if result is None:
        row = RowData(
            title=display_title, year=year_str,
            status="No CHT found (skipped)", changed="-", color=Color.DIM,
        )
        with _print_lock:
            print_row(row)
        with stats_lock:
            stats.total += 1
            stats.skipped += 1
        return

    # Case 2: "none" sentinel — disable subtitles
    if result.score == -999:
        if config.dry_run:
            row = RowData(
                title=display_title, year=year_str,
                status="[DRY-RUN] Would disable subs", changed="-", color=Color.YELLOW,
            )
        else:
            try:
                part = video.media[0].parts[0]
                url = f"{config.plex_url}/library/parts/{part.id}?subtitleStreamID=0&allParts=1"
                headers = {"X-Plex-Token": config.plex_token}
                _put_with_retry(url, headers)
                row = RowData(
                    title=display_title, year=year_str,
                    status="Subtitles disabled (fallback)", changed="Y", color=Color.YELLOW,
                )
            except Exception as e:
                logger.error("Failed to disable subs for %s: %s", display_title, e)
                row = RowData(
                    title=display_title, year=year_str,
                    status=f"Error: {e}", changed="ERR", color=Color.RED,
                )
                with stats_lock:
                    stats.errors += 1

        with _print_lock:
            print_row(row)
        with stats_lock:
            stats.total += 1
            stats.fallback_used += 1
        return

    # Case 3: A real subtitle was selected
    sub = result.info
    is_cht = result.category == SubtitleCategory.CHT
    status_label = f"{sub.title or sub.language or sub.language_code} ({result.score})"

    # Check if already selected
    if sub.selected and not config.force_overwrite:
        row = RowData(
            title=display_title, year=year_str,
            status=f"Already set: {status_label}", changed="-", color=Color.DIM,
        )
        with _print_lock:
            print_row(row)
        with stats_lock:
            stats.total += 1
            stats.skipped += 1
        return

    if config.dry_run:
        prefix = "[DRY-RUN] "
        color = Color.YELLOW
        changed = "-"
    else:
        try:
            part = video.media[0].parts[0]
            url = f"{config.plex_url}/library/parts/{part.id}?subtitleStreamID={sub.stream_id}&allParts=1"
            headers = {"X-Plex-Token": config.plex_token}
            _put_with_retry(url, headers)
            prefix = ""
            color = Color.GREEN if is_cht else Color.CYAN
            changed = "Y"
        except Exception as e:
            logger.error("Failed to set subtitle for %s: %s", display_title, e)
            row = RowData(
                title=display_title, year=year_str,
                status=f"Error: {e}", changed="ERR", color=Color.RED,
            )
            with _print_lock:
                print_row(row)
            with stats_lock:
                stats.total += 1
                stats.errors += 1
            return

    fallback_tag = " [fallback]" if not is_cht else ""
    row = RowData(
        title=display_title, year=year_str,
        status=f"{prefix}{status_label}{fallback_tag}", changed=changed,
        color=color,
    )
    with _print_lock:
        print_row(row)
    with stats_lock:
        stats.total += 1
        if changed == "Y":
            stats.changed += 1
            if not is_cht:
                stats.fallback_used += 1


# ---------------------------------------------------------------------------
# Library scanning — collect items, then process in parallel
# ---------------------------------------------------------------------------

def scan_library(plex: PlexServer, config: Config) -> ScanStats:
    """Scan Plex library sections and set preferred subtitles."""
    cutoff: Optional[datetime] = None
    if config.scan_range_days is not None:
        cutoff = datetime.now() - timedelta(days=config.scan_range_days)
        print(f"\nScanning items modified after: {cutoff.strftime('%Y-%m-%d')}")
    else:
        print("\nFull library scan...")

    if config.force_overwrite:
        print(f"\033[93mWARNING: Force overwrite is ON — existing selections will be re-evaluated.\033[0m")
    if config.dry_run:
        print(f"\033[93mDRY-RUN MODE — no changes will be made.\033[0m")

    # Collect tasks
    tasks: list[str] = []  # item keys

    for section in plex.library.sections():
        if section.type not in ("movie", "show"):
            continue

        print_header(f"Section: {section.title} ({section.type})")

        if cutoff is not None:
            items = section.search(sort="updatedAt:desc")
        else:
            items = section.all()

        for item in items:
            if cutoff is not None:
                updated = getattr(item, "updatedAt", None)
                added = getattr(item, "addedAt", None)
                # Skip if both dates are old (or missing)
                updated_recent = updated is not None and updated >= cutoff
                added_recent = added is not None and added >= cutoff
                if not updated_recent and not added_recent:
                    continue  # skip this item, but don't break — others may be recent

            if section.type == "movie":
                tasks.append(item.key)

            elif section.type == "show":
                try:
                    episodes = item.episodes()
                except Exception as e:
                    logger.error("Failed to list episodes for %s: %s", item.title, e)
                    continue
                for episode in episodes:
                    if cutoff is not None:
                        e_updated = getattr(episode, "updatedAt", None)
                        e_added = getattr(episode, "addedAt", None)
                        if not (
                            (e_updated is not None and e_updated >= cutoff)
                            or (e_added is not None and e_added >= cutoff)
                        ):
                            continue
                    tasks.append(episode.key)

    print(f"\nFound {len(tasks)} items. Processing with {config.workers} threads...\n")

    stats = ScanStats()
    stats_lock = threading.Lock()
    start_time = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=config.workers) as executor:
        futures = [
            executor.submit(_process_item, plex, key, config, stats, stats_lock)
            for key in tasks
        ]
        concurrent.futures.wait(futures)

    duration = time.time() - start_time
    print_summary(stats, duration)

    return stats
