#!/usr/bin/env python3
"""Diagnostic script — analyze subtitle streams across your Plex library.

Outputs a report of all items with Chinese subtitles, showing:
- What streams exist and how they're classified
- Whether content analysis could/did run
- What the algorithm would select
- Items that might be problematic

Usage:
    python diagnose.py                  # Scan recent 30 days
    python diagnose.py --full           # Full library scan
    python diagnose.py --full --csv     # Output as CSV
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from io import StringIO

from plexapi.server import PlexServer

from plexchtsubs.config import load_config
from plexchtsubs.detector import (
    SubtitleCategory,
    SubtitleInfo,
    SubtitleResult,
    classify,
    select_best,
)
from plexchtsubs.scanner import _to_subtitle_info, _fetch_subtitle_content

# ── Helpers ──────────────────────────────────────────────────────────

def _classify_stream(s: SubtitleInfo, content: str | None = None) -> SubtitleResult:
    return classify(s, content=content)


def _describe_category(cat: SubtitleCategory) -> str:
    return {
        SubtitleCategory.CHT: "CHT",
        SubtitleCategory.CHS: "CHS",
        SubtitleCategory.UNKNOWN_ZH: "ZH?",
        SubtitleCategory.ENGLISH: "ENG",
        SubtitleCategory.OTHER: "---",
    }.get(cat, "???")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Diagnose subtitle detection")
    parser.add_argument("--full", action="store_true", help="Full library scan (default: 30 days)")
    parser.add_argument("--csv", action="store_true", help="Output CSV format")
    parser.add_argument("--problems-only", action="store_true", help="Only show items with potential issues")
    args = parser.parse_args()

    config = load_config()

    print(f"Connecting to {config.plex_url}...", file=sys.stderr)
    plex = PlexServer(config.plex_url, config.plex_token)
    print(f"Connected: {plex.friendlyName} (v{plex.version})", file=sys.stderr)

    cutoff = None
    if not args.full:
        cutoff = datetime.now() - timedelta(days=30)
        print(f"Scanning items updated after {cutoff.strftime('%Y-%m-%d')}", file=sys.stderr)
    else:
        print("Full library scan", file=sys.stderr)

    # Collect items
    items = []
    for section in plex.library.sections():
        if section.type not in ("movie", "show"):
            continue
        print(f"  Section: {section.title} ({section.type})", file=sys.stderr)

        source = section.search(sort="updatedAt:desc") if cutoff else section.all()
        for item in source:
            if cutoff:
                updated = getattr(item, "updatedAt", None)
                added = getattr(item, "addedAt", None)
                if not ((updated and updated >= cutoff) or (added and added >= cutoff)):
                    continue

            if section.type == "movie":
                items.append(item.key)
            elif section.type == "show":
                try:
                    for ep in item.episodes():
                        if cutoff:
                            eu = getattr(ep, "updatedAt", None)
                            ea = getattr(ep, "addedAt", None)
                            if not ((eu and eu >= cutoff) or (ea and ea >= cutoff)):
                                continue
                        items.append(ep.key)
                except Exception:
                    continue

    print(f"\nFound {len(items)} items to analyze.\n", file=sys.stderr)

    # Analyze
    rows = []
    category_counts = Counter()
    problem_types = Counter()

    for i, key in enumerate(items):
        if (i + 1) % 200 == 0:
            print(f"  Progress: {i+1}/{len(items)}...", file=sys.stderr)

        try:
            video = plex.fetchItem(key)
            video.reload()
        except Exception:
            continue

        if video.type == "episode":
            title = f"{video.grandparentTitle} S{video.seasonNumber:02d}E{video.index:02d}"
        else:
            title = str(video.title)
        year = str(video.year) if video.year else ""

        raw_streams = video.subtitleStreams()
        if not raw_streams:
            continue

        streams = [_to_subtitle_info(s) for s in raw_streams]

        # Classify all streams
        results = []
        content_map = {}
        for s in streams:
            quick = classify(s)
            # Try content analysis for UNKNOWN_ZH
            content = None
            has_key = bool(s.key)
            if quick.category == SubtitleCategory.UNKNOWN_ZH and s.key:
                content = _fetch_subtitle_content(config.plex_url, config.plex_token, s)
                if content:
                    content_map[s.stream_id] = content

            full_result = classify(s, content=content_map.get(s.stream_id))
            results.append((s, full_result, has_key))

        # What would select_best pick?
        best = select_best(streams, fallback=config.fallback, content_map=content_map)

        # Count categories
        zh_streams = [(s, r, k) for s, r, k in results
                      if r.category in (SubtitleCategory.CHT, SubtitleCategory.CHS, SubtitleCategory.UNKNOWN_ZH)]

        if not zh_streams:
            continue

        # Determine the situation
        cht_count = sum(1 for _, r, _ in results if r.category == SubtitleCategory.CHT)
        chs_count = sum(1 for _, r, _ in results if r.category == SubtitleCategory.CHS)
        unknown_count = sum(1 for _, r, _ in results if r.category == SubtitleCategory.UNKNOWN_ZH)
        has_key_count = sum(1 for s, r, _ in results
                           if r.category == SubtitleCategory.UNKNOWN_ZH and s.key)

        # Currently selected
        selected_stream = None
        for s in streams:
            if s.selected:
                selected_stream = s
                break

        # Identify problems
        problems = []
        if cht_count == 0 and unknown_count >= 1:
            if unknown_count >= 2:
                problems.append("2nd-generic")
            elif unknown_count == 1 and has_key_count == 0:
                problems.append("no-key-no-heuristic")
            elif unknown_count == 1:
                problems.append("single-unknown")

        if best and best.score <= 10:
            problems.append(f"low-score({best.score})")

        if not best:
            problems.append("no-match")

        category_counts[f"CHT={cht_count} CHS={chs_count} ZH?={unknown_count}"] += 1
        for p in problems:
            problem_types[p] += 1

        # Build stream detail string
        stream_details = []
        for s, r, has_key in results:
            if r.category == SubtitleCategory.OTHER:
                continue
            sel_mark = "*" if s.selected else " "
            key_mark = "K" if has_key else "-"
            codec_str = (s.codec or "?")[:8]
            title_str = (s.title or "")[:20]
            stream_details.append(
                f"  {sel_mark} [{r.info.stream_id:>5}] "
                f"{_describe_category(r.category):>4} {r.score:>4}  "
                f"{key_mark} {codec_str:<8} {title_str}"
            )

        best_str = "None"
        if best:
            best_str = f"stream={best.info.stream_id} {_describe_category(best.category)} score={best.score}"

        problem_str = ", ".join(problems) if problems else "ok"

        if args.problems_only and not problems:
            continue

        rows.append({
            "title": title,
            "year": year,
            "cht": cht_count,
            "chs": chs_count,
            "unknown": unknown_count,
            "best": best_str,
            "problems": problem_str,
            "streams": "\n".join(stream_details),
        })

    # ── Output ───────────────────────────────────────────────────────

    if args.csv:
        out = StringIO()
        writer = csv.DictWriter(out, fieldnames=["title", "year", "cht", "chs", "unknown", "best", "problems"])
        writer.writeheader()
        for r in rows:
            writer.writerow({k: v for k, v in r.items() if k != "streams"})
        print(out.getvalue())
    else:
        for r in rows:
            print(f"{'─'*80}")
            print(f"{r['title']} ({r['year']})  [{r['problems']}]")
            print(f"  CHT={r['cht']} CHS={r['chs']} ZH?={r['unknown']}  →  {r['best']}")
            if r["streams"]:
                print(f"  Streams (sel/id/cat/score/key/codec/title):")
                print(r["streams"])

    # Summary
    print(f"\n{'='*80}", file=sys.stderr)
    print(f"SUMMARY: {len(rows)} items with Chinese subtitles", file=sys.stderr)
    print(f"\nSubtitle composition:", file=sys.stderr)
    for combo, count in category_counts.most_common():
        print(f"  {combo}: {count}", file=sys.stderr)
    print(f"\nProblem breakdown:", file=sys.stderr)
    for prob, count in problem_types.most_common():
        print(f"  {prob}: {count}", file=sys.stderr)
    if not problem_types:
        print(f"  (none — all items have confident detection)", file=sys.stderr)


if __name__ == "__main__":
    main()
