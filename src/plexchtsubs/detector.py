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
    key: Optional[str] = None  # Plex download path for content analysis


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
    r'|traditional|big5|\bfanti\b'
    r'|繁體|繁体|繁中|繁日|繁英|正體|正体'
    r'|taiwan|hong\s*kong|\bhk\b|台灣|台湾|香港'
    r'|jptc',
    re.IGNORECASE,
)

RE_CHS = re.compile(
    r'\bchs\b|\bsc\b|zh[_-]?hans|zh[_-]?cn'
    r'|simplified|\bjianti\b'
    r'|简体|简中|簡體|简日|简英'
    r'|gb2312|gbk'
    r'|jpsc',
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
# Content analysis — detect CHT vs CHS by character frequency
# ---------------------------------------------------------------------------

# High-frequency character pairs where Traditional and Simplified forms differ.
# Each tuple: (Traditional, Simplified). These are distinct Unicode codepoints.
_TRAD_SIMP_PAIRS = [
    ("們", "们"), ("這", "这"), ("會", "会"), ("對", "对"), ("說", "说"),
    ("過", "过"), ("還", "还"), ("時", "时"), ("從", "从"), ("開", "开"),
    ("長", "长"), ("問", "问"), ("進", "进"), ("動", "动"), ("現", "现"),
    ("發", "发"), ("讓", "让"), ("給", "给"), ("種", "种"), ("應", "应"),
    ("實", "实"), ("書", "书"), ("關", "关"), ("點", "点"), ("經", "经"),
    ("學", "学"), ("認", "认"), ("間", "间"), ("話", "话"), ("頭", "头"),
    ("該", "该"), ("車", "车"), ("電", "电"), ("東", "东"), ("樣", "样"),
    ("難", "难"), ("達", "达"), ("運", "运"), ("連", "连"), ("類", "类"),
    ("選", "选"), ("語", "语"), ("調", "调"), ("邊", "边"), ("圖", "图"),
    ("場", "场"), ("報", "报"), ("聽", "听"), ("義", "义"), ("區", "区"),
    ("雙", "双"), ("華", "华"), ("廣", "广"), ("寫", "写"), ("結", "结"),
    ("處", "处"), ("證", "证"), ("號", "号"), ("議", "议"), ("錢", "钱"),
    ("離", "离"), ("線", "线"), ("條", "条"), ("國", "国"), ("體", "体"),
    ("變", "变"), ("題", "题"), ("視", "视"), ("覺", "觉"), ("響", "响"),
    ("環", "环"), ("機", "机"), ("歷", "历"), ("練", "练"), ("課", "课"),
    ("專", "专"), ("導", "导"), ("傳", "传"), ("節", "节"), ("計", "计"),
    ("紅", "红"), ("飛", "飞"), ("龍", "龙"), ("門", "门"), ("後", "后"),
    ("個", "个"), ("來", "来"), ("無", "无"), ("見", "见"), ("愛", "爱"),
    ("買", "买"), ("錯", "错"), ("滿", "满"), ("準", "准"),
]

_TRAD_CHARS = frozenset(t for t, _ in _TRAD_SIMP_PAIRS)
_SIMP_CHARS = frozenset(s for _, s in _TRAD_SIMP_PAIRS)

# Minimum distinguishing characters needed for a reliable verdict.
_MIN_CONTENT_CHARS = 5


def analyze_subtitle_text(text: str) -> Optional[tuple[SubtitleCategory, int]]:
    """Determine CHT vs CHS by counting distinguishing characters.

    Returns (category, base_score) or None if insufficient data.
    Score +85 for CHT, -100 for CHS (forced penalty applied separately).
    """
    trad = sum(1 for c in text if c in _TRAD_CHARS)
    simp = sum(1 for c in text if c in _SIMP_CHARS)
    total = trad + simp

    if total < _MIN_CONTENT_CHARS:
        return None

    ratio = trad / total
    if ratio >= 0.7:
        return (SubtitleCategory.CHT, 85)
    elif ratio <= 0.3:
        return (SubtitleCategory.CHS, -100)
    return None  # ambiguous mix


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def classify(info: SubtitleInfo, content: Optional[str] = None) -> SubtitleResult:
    """Classify a subtitle stream and assign a confidence score.

    Score ranges:
        +100   Definite CHT (title regex match)
         +95   CHT by language code (zh-tw, zh-hant)
         +90   CHT by language description ("Traditional", "Taiwan", "Hong Kong")
         +85   CHT by content analysis (character frequency)
         +10   Unknown Chinese variant — treated as "no CHT found"
           0   Not Chinese at all
        -100   Definite CHS (title regex or language code/description or content)

    If *content* is provided and the stream is UNKNOWN_ZH, character frequency
    analysis is used to refine the classification.

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
            if content is not None:
                analysis = analyze_subtitle_text(content)
                if analysis is not None:
                    category, score = analysis

    # 4) English detection (for fallback purposes)
    elif lang_code == "eng" or "english" in lang_desc:
        score, category = 0, SubtitleCategory.ENGLISH

    # Forced penalty
    if is_forced:
        score -= 50

    # External subtitle bonus (tiebreaker: prefer external over embedded)
    if info.key:
        score += 2

    return SubtitleResult(info=info, category=category, score=score)


def select_best(
    streams: Sequence[SubtitleInfo],
    *,
    fallback: str = "skip",
    content_map: Optional[dict[int, str]] = None,
) -> Optional[SubtitleResult]:
    """Pick the best subtitle from a list of streams.

    Returns the best CHT subtitle if one exists (by category).
    Otherwise, applies the fallback strategy:
        "skip"    → return None (don't change anything)
        "english" → return best English subtitle, or None
        "chs"     → return best CHS subtitle, or None
        "none"    → return a sentinel meaning "disable subtitles"

    If *content_map* is provided (stream_id → subtitle text), it is passed
    to classify() for content-based analysis of UNKNOWN_ZH streams.
    """
    if not streams:
        return None

    _cmap = content_map or {}
    results = [classify(s, content=_cmap.get(s.stream_id)) for s in streams]

    # Find best CHT candidate (by category — score is only for ranking)
    cht_candidates = [r for r in results if r.category == SubtitleCategory.CHT]
    if cht_candidates:
        return max(cht_candidates, key=lambda r: r.score)

    # "Second Generic" heuristic: when 2+ unknown Chinese tracks exist
    # with no distinguishing metadata, the second track by stream order
    # is typically CHT (common MKV convention: CHS first, CHT second).
    # Exception: if an external subtitle (has key → +2 bonus) scores higher,
    # prefer it — the user likely added it intentionally, and the scanner
    # can attempt content analysis on it.
    unknown_zh = [r for r in results if r.category == SubtitleCategory.UNKNOWN_ZH]
    if len(unknown_zh) >= 2:
        top_score = max(r.score for r in unknown_zh)
        top_candidates = [r for r in unknown_zh if r.score == top_score]
        if len(top_candidates) < len(unknown_zh):
            # Score difference exists (e.g., external bonus) — pick highest
            return max(unknown_zh, key=lambda r: r.score)
        # All equal scores — fall back to second-by-stream-order heuristic
        unknown_zh.sort(key=lambda r: r.info.stream_id)
        return unknown_zh[1]

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
        # Accept both confirmed-CHS and unknown-variant Chinese
        # (UNKNOWN_ZH are generic "中文" tracks — "at least it's Chinese").
        chs = [
            r for r in results
            if r.category in (SubtitleCategory.CHS, SubtitleCategory.UNKNOWN_ZH)
        ]
        if chs:
            # Highest score wins: UNKNOWN_ZH (+10) preferred over CHS (-100),
            # since an unknown track might actually be Traditional.
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
