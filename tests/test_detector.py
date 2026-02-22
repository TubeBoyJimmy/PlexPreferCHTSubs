"""Unit tests for plexchtsubs.detector — no Plex server needed."""

import pytest
from plexchtsubs.detector import (
    SubtitleCategory,
    SubtitleInfo,
    SubtitleResult,
    classify,
    select_best,
)


# ---------------------------------------------------------------------------
# Helper to create SubtitleInfo quickly
# ---------------------------------------------------------------------------

def _sub(
    stream_id: int = 1,
    title: str | None = None,
    language_code: str | None = None,
    language: str | None = None,
    forced: bool = False,
    selected: bool = False,
) -> SubtitleInfo:
    return SubtitleInfo(
        stream_id=stream_id,
        title=title,
        language_code=language_code,
        language=language,
        forced=forced,
        selected=selected,
    )


# ===================================================================
# classify() — Title-based CHT detection
# ===================================================================

class TestClassifyCHT:
    """Title contains clear CHT indicators → score 100."""

    @pytest.mark.parametrize("title", [
        "繁體中文",
        "繁中",
        "繁日雙語",
        "正體中文",
        "CHT",
        "cht subtitle",
        "Traditional Chinese",
        "zh-Hant",
        "zh_Hant",
        "zh-TW subtitle",
        "BIG5",
        "Taiwan",
        "Hong Kong",
        "HK subtitle",
        "TC",
    ])
    def test_title_cht_keywords(self, title: str):
        result = classify(_sub(title=title, language_code="chi"))
        assert result.category == SubtitleCategory.CHT
        assert result.score == 100

    def test_cht_is_case_insensitive(self):
        result = classify(_sub(title="traditional chinese"))
        assert result.category == SubtitleCategory.CHT


# ===================================================================
# classify() — Title-based CHS detection
# ===================================================================

class TestClassifyCHS:
    """Title contains CHS indicators → score -100."""

    @pytest.mark.parametrize("title", [
        "简体中文",
        "简中",
        "簡體中文",
        "CHS",
        "chs subtitle",
        "Simplified Chinese",
        "zh-Hans",
        "zh_CN",
        "GB2312",
        "GBK",
    ])
    def test_title_chs_keywords(self, title: str):
        result = classify(_sub(title=title, language_code="chi"))
        assert result.category == SubtitleCategory.CHS
        assert result.score == -100


# ===================================================================
# classify() — False positive prevention
# ===================================================================

class TestFalsePositives:
    """Ensure short patterns don't match unrelated words."""

    def test_tc_does_not_match_etc(self):
        result = classify(_sub(title="Dutch subtitle"))
        assert result.category != SubtitleCategory.CHT

    def test_tc_does_not_match_match(self):
        result = classify(_sub(title="match"))
        assert result.category != SubtitleCategory.CHT

    def test_sc_does_not_match_oscar(self):
        result = classify(_sub(title="Oscar"))
        assert result.category != SubtitleCategory.CHS

    def test_cn_does_not_match_scene(self):
        result = classify(_sub(title="scene"))
        assert result.category != SubtitleCategory.CHS

    def test_hk_does_not_match_think(self):
        result = classify(_sub(title="think"))
        assert result.category != SubtitleCategory.CHT

    def test_machine_not_flagged_as_chs(self):
        """The old regex had 'machine' as CHS — should no longer match."""
        result = classify(_sub(title="machine translated"))
        assert result.category != SubtitleCategory.CHS


# ===================================================================
# classify() — Language code detection
# ===================================================================

class TestLanguageCode:

    def test_zh_tw_lang_code(self):
        result = classify(_sub(language_code="zh-tw"))
        assert result.category == SubtitleCategory.CHT
        assert result.score == 95

    def test_zh_hant_lang_code(self):
        result = classify(_sub(language_code="zh-hant"))
        assert result.category == SubtitleCategory.CHT
        assert result.score == 95

    def test_zh_cn_lang_code(self):
        result = classify(_sub(language_code="zh-cn"))
        assert result.category == SubtitleCategory.CHS
        assert result.score == -100

    def test_zh_hans_lang_code(self):
        result = classify(_sub(language_code="zh-hans"))
        assert result.category == SubtitleCategory.CHS
        assert result.score == -100


# ===================================================================
# classify() — Language description detection (generic chi/zho/zh)
# ===================================================================

class TestLanguageDescription:

    def test_chi_with_traditional_desc(self):
        result = classify(_sub(language_code="chi", language="Chinese (Traditional)"))
        assert result.category == SubtitleCategory.CHT
        assert result.score == 90

    def test_chi_with_taiwan_desc(self):
        result = classify(_sub(language_code="zho", language="Chinese (Taiwan)"))
        assert result.category == SubtitleCategory.CHT
        assert result.score == 90

    def test_chi_with_simplified_desc(self):
        result = classify(_sub(language_code="chi", language="Chinese (Simplified)"))
        assert result.category == SubtitleCategory.CHS
        assert result.score == -100

    def test_chi_with_no_desc(self):
        """Generic Chinese with no description → unknown."""
        result = classify(_sub(language_code="chi", language="Chinese"))
        assert result.category == SubtitleCategory.UNKNOWN_ZH
        assert result.score == 10

    def test_chi_with_none_desc(self):
        result = classify(_sub(language_code="chi", language=None))
        assert result.category == SubtitleCategory.UNKNOWN_ZH
        assert result.score == 10


# ===================================================================
# classify() — Forced subtitle penalty
# ===================================================================

class TestForcedPenalty:

    def test_forced_flag_reduces_score(self):
        normal = classify(_sub(title="繁體中文", forced=False))
        forced = classify(_sub(title="繁體中文", forced=True))
        assert normal.score == 100
        assert forced.score == 50

    def test_forced_in_title_reduces_score(self):
        result = classify(_sub(title="繁體中文 Forced", forced=False))
        assert result.score == 50

    def test_forced_chs_goes_more_negative(self):
        result = classify(_sub(title="简体中文", forced=True))
        assert result.score == -150


# ===================================================================
# classify() — English detection
# ===================================================================

class TestEnglish:

    def test_eng_lang_code(self):
        result = classify(_sub(language_code="eng", language="English"))
        assert result.category == SubtitleCategory.ENGLISH

    def test_non_chinese_non_english(self):
        result = classify(_sub(language_code="jpn", language="Japanese"))
        assert result.category == SubtitleCategory.OTHER
        assert result.score == 0


# ===================================================================
# select_best() — CHT selection
# ===================================================================

class TestSelectBestCHT:

    def test_picks_highest_score_cht(self):
        streams = [
            _sub(stream_id=1, title="简体中文", language_code="chi"),
            _sub(stream_id=2, title="繁體中文", language_code="chi"),
            _sub(stream_id=3, language_code="eng", language="English"),
        ]
        result = select_best(streams)
        assert result is not None
        assert result.info.stream_id == 2
        assert result.category == SubtitleCategory.CHT

    def test_cht_by_lang_code_when_no_title(self):
        streams = [
            _sub(stream_id=1, language_code="zh-cn"),
            _sub(stream_id=2, language_code="zh-tw"),
        ]
        result = select_best(streams)
        assert result is not None
        assert result.info.stream_id == 2

    def test_prefers_non_forced_cht(self):
        streams = [
            _sub(stream_id=1, title="繁體中文", forced=True),
            _sub(stream_id=2, title="繁體中文", forced=False),
        ]
        result = select_best(streams)
        assert result is not None
        assert result.info.stream_id == 2
        assert result.score == 100

    def test_empty_streams(self):
        assert select_best([]) is None


# ===================================================================
# select_best() — Fallback strategies
# ===================================================================

class TestSelectBestFallback:

    def _no_cht_streams(self):
        """Streams with no CHT — only CHS, English, Japanese."""
        return [
            _sub(stream_id=1, title="简体中文", language_code="chi"),
            _sub(stream_id=2, language_code="eng", language="English"),
            _sub(stream_id=3, language_code="jpn", language="Japanese"),
        ]

    def test_fallback_skip(self):
        result = select_best(self._no_cht_streams(), fallback="skip")
        assert result is None

    def test_fallback_english(self):
        result = select_best(self._no_cht_streams(), fallback="english")
        assert result is not None
        assert result.category == SubtitleCategory.ENGLISH
        assert result.info.stream_id == 2

    def test_fallback_english_when_no_english(self):
        streams = [_sub(stream_id=1, title="简体中文", language_code="chi")]
        result = select_best(streams, fallback="english")
        assert result is None

    def test_fallback_chs(self):
        result = select_best(self._no_cht_streams(), fallback="chs")
        assert result is not None
        assert result.category == SubtitleCategory.CHS
        assert result.info.stream_id == 1

    def test_fallback_none_returns_sentinel(self):
        result = select_best(self._no_cht_streams(), fallback="none")
        assert result is not None
        assert result.score == -999

    def test_unknown_zh_triggers_fallback(self):
        """Score 10 (unknown Chinese) should NOT be selected as CHT."""
        streams = [
            _sub(stream_id=1, language_code="chi", language="Chinese"),
            _sub(stream_id=2, language_code="eng", language="English"),
        ]
        result = select_best(streams, fallback="english")
        assert result is not None
        assert result.category == SubtitleCategory.ENGLISH
