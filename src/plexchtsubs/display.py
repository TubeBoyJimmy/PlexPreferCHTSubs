"""Terminal output formatting with CJK-aware column widths."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# CJK display width (ported from PlexPreferCHTSubs_OPT.py, verified correct)
# ---------------------------------------------------------------------------

def display_width(text: str) -> int:
    """Calculate the display width of a string, accounting for East Asian wide chars."""
    width = 0
    for char in text:
        if unicodedata.east_asian_width(char) in ("W", "F"):
            width += 2
        else:
            width += 1
    return width


def pad(text: str, target_width: int) -> str:
    """Pad text to target display width with spaces."""
    current = display_width(text)
    remaining = target_width - current
    return text + " " * max(0, remaining)


def truncate(text: str, max_width: int, suffix: str = "...") -> str:
    """Truncate text to fit within max display width, adding suffix if truncated."""
    if display_width(text) <= max_width:
        return text
    suffix_w = display_width(suffix)
    result = []
    w = 0
    for char in text:
        cw = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        if w + cw + suffix_w > max_width:
            break
        result.append(char)
        w += cw
    return "".join(result) + suffix


# ---------------------------------------------------------------------------
# ANSI color helpers
# ---------------------------------------------------------------------------

class Color:
    GREEN = "\033[92m"
    CYAN = "\033[96m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    DIM = "\033[90m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def colorize(text: str, color: str) -> str:
    return f"{color}{text}{Color.RESET}"


# ---------------------------------------------------------------------------
# Table output
# ---------------------------------------------------------------------------

@dataclass
class ColumnDef:
    header: str
    width: int


# Default column layout
COLUMNS = [
    ColumnDef("Title", 70),
    ColumnDef("Year", 6),
    ColumnDef("Selected Sub (Score)", 30),
    ColumnDef("Changed", 8),
]

SEPARATOR_WIDTH = sum(c.width for c in COLUMNS) + (len(COLUMNS) - 1) * 3  # " | " between cols


def print_header(section_name: Optional[str] = None) -> None:
    """Print table header with optional section name."""
    if section_name:
        print(f"\n{'─' * SEPARATOR_WIDTH}")
        print(f"  {section_name}")
    print("─" * SEPARATOR_WIDTH)
    header_parts = [pad(c.header, c.width) for c in COLUMNS]
    print(colorize(" | ".join(header_parts), Color.BOLD + Color.CYAN))
    print("─" * SEPARATOR_WIDTH)


@dataclass
class RowData:
    title: str
    year: str
    status: str
    changed: str
    color: str = ""  # ANSI color code, empty = default


def print_row(row: RowData) -> None:
    """Print a single table row."""
    t = pad(truncate(row.title, COLUMNS[0].width), COLUMNS[0].width)
    y = pad(row.year, COLUMNS[1].width)
    s = pad(truncate(row.status, COLUMNS[2].width), COLUMNS[2].width)
    c = pad(row.changed, COLUMNS[3].width)
    line = f"{t} | {y} | {s} | {c}"
    if row.color:
        print(colorize(line, row.color))
    else:
        print(line)


@dataclass
class ScanStats:
    total: int = 0
    changed: int = 0
    skipped: int = 0
    no_subtitle: int = 0
    fallback_used: int = 0
    errors: int = 0


def print_summary(stats: ScanStats, duration: float) -> None:
    """Print scan summary after processing."""
    print(f"\n{'─' * SEPARATOR_WIDTH}")
    print(f"  Scan complete in {duration:.1f}s")
    print(f"  Total: {stats.total}  |  "
          f"Changed: {colorize(str(stats.changed), Color.GREEN)}  |  "
          f"Skipped: {stats.skipped}  |  "
          f"No Sub: {stats.no_subtitle}  |  "
          f"Fallback: {stats.fallback_used}  |  "
          f"Errors: {colorize(str(stats.errors), Color.RED) if stats.errors else '0'}")
    print("─" * SEPARATOR_WIDTH)
