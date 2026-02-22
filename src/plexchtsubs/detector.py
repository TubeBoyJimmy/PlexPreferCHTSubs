"""CHT/CHS subtitle detection and scoring.

Pure functions with no side effects — all Plex API details stay in scanner.py.
This module only works with SubtitleInfo dataclass instances.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence


class SubtitleCategory(Enum):
    CHT = "cht"           # Traditional Chinese (繁體中文)
    CHS = "chs"           # Simplified Chinese (簡體中文)
    UNKNOWN_ZH = "zh"     # Chinese, variant unknown
    ENGLISH = "english"
    OTHER = "other"


@dataclass(frozen=True)
class SubtitleInfo:
    """Normalized subtitle stream data, decoupled from plexapi objects."""
    stream_id: int
    title: Optional[str]       # e.g. "繁體中文", "English", None
    language_code: Optional[str]  # e.g. "chi", "zho", "zh", "eng"
    language: Optional[str]    # e.g. "Chinese", "Chinese (Traditional)", "English"
    forced: bool = False
    selected: bool = False
    codec: Optional[str] = None


@dataclass(frozen=True)
class SubtitleResult:
    """Scoring result for a single subtitle stream."""
    info: SubtitleInfo
    category: SubtitleCategory
    score: int


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Word boundaries (\b) prevent false positives: "tc" won't match "etc"
RE_CHT = re.compile(
    r'\bcht\b|\btc\b|zh[_-]?hant|zh[_-]?tw'
    r'|traditional|big5'
    r'|繁體|繁中|繁日|正體'
    r'|taiwan|hong\s*kong|\bhk\b',
    re.IGNORECASE,
)

RE_CHS = re.compile(
    r'\bchs\b|\bsc\b|zh[_-]?hans|zh[_-]?cn'
    r'|simplified'
    r'|简体|简中|簡體中文'
    r'|gb2312|gbk',
    re.IGNORECASE,
)

RE_FORCED = re.compile(r'\bforced\b', re.IGNORECASE)

# Language codes that indicate "some kind of Chinese"
_ZH_LANG_CODES = frozenset({"chi", "zho", "zh"})

# Language codes that are definitively CHT
_ZH_CHT_LANG_CODES = frozenset({"zh-tw", "zh-hant", "zht"})

# Language codes that are definitively CHS
_ZH_CHS_LANG_CODES = frozenset({"zh-cn", "zh-hans", "zhs"})


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def classify(info: SubtitleInfo) -> SubtitleResult:
    """Classify a subtitle stream and assign a confidence score.

    Score ranges:
        +100   Definite CHT (title regex match)
         +95   CHT by language code (zh-tw, zh-hant)
         +90   CHT by language description ("Traditional", "Taiwan", "Hong Kong")
         +10   Unknown Chinese variant — treated as "no CHT found"
           0   Not Chinese at all
        -100   Definite CHS (title regex or language code/description)

    Forced subtitles receive a -50 penalty on top of the base score.
    """
    title = (info.title or "").strip()
    lang_code = (info.language_code or "").strip().lower()
    lang_desc = (info.language or "").strip().lower()

    is_forced = info.forced or bool(RE_FORCED.search(title))

    score = 0
    category = SubtitleCategory.OTHER

    # 1) Title-based detection (most reliable signal)
    if RE_CHT.search(title):
        score, category = 100, SubtitleCategory.CHT
    elif RE_CHS.search(title):
        score, category = -100, SubtitleCategory.CHS

    # 2) Explicit language code
    elif lang_code in _ZH_CHT_LANG_CODES:
        score, category = 95, SubtitleCategory.CHT
    elif lang_code in _ZH_CHS_LANG_CODES:
        score, category = -100, SubtitleCategory.CHS

    # 3) Generic Chinese language code — inspect description
    elif lang_code in _ZH_LANG_CODES:
        if any(kw in lang_desc for kw in ("traditional", "taiwan", "hong kong")):
            score, category = 90, SubtitleCategory.CHT
        elif any(kw in lang_desc for kw in ("simplified", "china")):
            score, category = -100, SubtitleCategory.CHS
        else:
            score, category = 10, SubtitleCategory.UNKNOWN_ZH

    # 4) English detection (for fallback purposes)
    elif lang_code == "eng" or "english" in lang_desc:
        score, category = 0, SubtitleCategory.ENGLISH

    # Forced penalty
    if is_forced:
        score -= 50

    return SubtitleResult(info=info, category=category, score=score)


def select_best(
    streams: Sequence[SubtitleInfo],
    *,
    fallback: str = "skip",
) -> Optional[SubtitleResult]:
    """Pick the best subtitle from a list of streams.

    Returns the best CHT subtitle if one exists (score > 50).
    Otherwise, applies the fallback strategy:
        "skip"    → return None (don't change anything)
        "english" → return best English subtitle, or None
        "chs"     → return best CHS subtitle, or None
        "none"    → return a sentinel meaning "disable subtitles"
    """
    if not streams:
        return None

    results = [classify(s) for s in streams]

    # Find best CHT candidate (score > 50 means confident CHT)
    cht_candidates = [r for r in results if r.score > 50]
    if cht_candidates:
        return max(cht_candidates, key=lambda r: r.score)

    # No confident CHT found — apply fallback
    if fallback == "skip":
        return None

    if fallback == "english":
        eng = [r for r in results if r.category == SubtitleCategory.ENGLISH]
        if eng:
            # Prefer non-forced English
            return max(eng, key=lambda r: r.score)
        return None

    if fallback == "chs":
        chs = [r for r in results if r.category == SubtitleCategory.CHS]
        if chs:
            # Pick the "least negative" CHS (closest to 0)
            return max(chs, key=lambda r: r.score)
        return None

    if fallback == "none":
        # Return a sentinel result — scanner.py will interpret this as "disable subs"
        return SubtitleResult(
            info=SubtitleInfo(stream_id=0, title=None, language_code=None, language=None),
            category=SubtitleCategory.OTHER,
            score=-999,
        )

    return None
