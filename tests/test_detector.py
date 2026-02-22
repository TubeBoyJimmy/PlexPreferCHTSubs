"""Unit tests for plexchtsubs.detector — no Plex server needed."""

import pytest
from plexchtsubs.detector import (
    SubtitleCategory,
    SubtitleInfo,
    SubtitleResult,
    analyze_subtitle_text,
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
        "繁体中文",       # simplified chars for 繁體
        "繁体",           # standalone simplified form
        "中文（繁体）",   # parenthesized simplified form
        "[BML] 繁体",     # tagged simplified form
        "繁中",
        "繁日雙語",
        "繁英@Prejudice-Studio",  # Traditional+English bilingual
        "正體中文",
        "正体中文",       # simplified chars for 正體
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
        "fanti",          # pinyin for 繁體
        "JPTC",           # fansub: JP Traditional Chinese
        "NekomoeKissaten-JPTC",  # fansub compound
        "官方台湾话字幕",  # Taiwan in Chinese chars (simplified)
        "台灣國語字幕",    # Taiwan in Chinese chars (traditional)
        "香港字幕",        # Hong Kong in Chinese chars
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
        "簡體",           # standalone traditional form
        "CHS",
        "chs subtitle",
        "Simplified Chinese",
        "zh-Hans",
        "zh_CN",
        "GB2312",
        "GBK",
        "jianti",         # pinyin for 簡體
        "JPSC",           # fansub: JP Simplified Chinese
        "NekomoeKissaten-JPSC",  # fansub compound
        "简日字幕",        # Simplified+Japanese bilingual
        "简英@Prejudice-Studio",  # Simplified+English bilingual
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

    def test_forced_cht_still_selected(self):
        """Forced CHT (score 50) should still be selected over UNKNOWN_ZH.

        Regression test for 龍貓 case: forced CHT was excluded by old
        score > 50 threshold. Now uses category-based selection.
        """
        streams = [
            _sub(stream_id=1, title="诸神繁日字幕", language_code="chi", forced=True),  # CHT, score 50
            _sub(stream_id=2, language_code="chi", language="Chinese"),  # UNKNOWN_ZH, score 10
            _sub(stream_id=3, language_code="chi", language="Chinese"),  # UNKNOWN_ZH, score 10
        ]
        result = select_best(streams, fallback="skip")
        assert result is not None
        assert result.info.stream_id == 1
        assert result.category == SubtitleCategory.CHT
        assert result.score == 50  # 100 - 50 forced

    def test_forced_cht_by_content_analysis_selected(self):
        """CHT detected via content analysis + forced → score 35, still selected."""
        streams = [
            _sub(stream_id=1, language_code="chi", language="Chinese", forced=True),
            _sub(stream_id=2, language_code="eng", language="English"),
        ]
        content_map = {
            1: "你好，這是一個測試。我們今天要學習的課題是關於電影的歷史。",
        }
        result = select_best(streams, fallback="skip", content_map=content_map)
        assert result is not None
        assert result.info.stream_id == 1
        assert result.category == SubtitleCategory.CHT
        assert result.score == 35  # 85 - 50 forced

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

    def test_fallback_chs_accepts_unknown_zh(self):
        """CHS fallback should accept generic Chinese (UNKNOWN_ZH) tracks."""
        streams = [
            _sub(stream_id=1, language_code="chi", language="Chinese"),
            _sub(stream_id=2, language_code="eng", language="English"),
        ]
        result = select_best(streams, fallback="chs")
        assert result is not None
        assert result.info.stream_id == 1
        assert result.category == SubtitleCategory.UNKNOWN_ZH

    def test_fallback_chs_prefers_unknown_zh_over_confirmed_chs(self):
        """UNKNOWN_ZH (score +10) should be preferred over CHS (score -100)."""
        streams = [
            _sub(stream_id=1, title="简体中文", language_code="chi"),  # CHS: -100
            _sub(stream_id=2, language_code="chi", language="Chinese"),  # UNKNOWN_ZH: +10
            _sub(stream_id=3, language_code="eng", language="English"),
        ]
        result = select_best(streams, fallback="chs")
        assert result is not None
        assert result.info.stream_id == 2
        assert result.category == SubtitleCategory.UNKNOWN_ZH

    def test_fallback_chs_still_picks_chs_when_no_unknown(self):
        """When only confirmed CHS exists, still picks it."""
        streams = [
            _sub(stream_id=1, title="简体中文", language_code="chi"),
            _sub(stream_id=2, language_code="eng", language="English"),
        ]
        result = select_best(streams, fallback="chs")
        assert result is not None
        assert result.info.stream_id == 1
        assert result.category == SubtitleCategory.CHS


# ===================================================================
# select_best() — "Second Generic" heuristic
# ===================================================================

class TestSecondGeneric:
    """When 2+ unknown Chinese tracks exist, pick the second by stream order."""

    def test_two_unknown_zh_picks_second(self):
        """Classic MKV layout: CHS first, CHT second — heuristic picks second."""
        streams = [
            _sub(stream_id=10, language_code="chi", language="Chinese"),
            _sub(stream_id=20, language_code="chi", language="Chinese"),
            _sub(stream_id=30, language_code="eng", language="English"),
        ]
        result = select_best(streams, fallback="skip")
        assert result is not None
        assert result.info.stream_id == 20

    def test_three_unknown_zh_still_picks_second(self):
        streams = [
            _sub(stream_id=10, language_code="chi", language="Chinese"),
            _sub(stream_id=20, language_code="chi", language="Chinese"),
            _sub(stream_id=30, language_code="chi", language="Chinese"),
        ]
        result = select_best(streams, fallback="skip")
        assert result is not None
        assert result.info.stream_id == 20

    def test_one_unknown_zh_no_heuristic(self):
        """Only 1 unknown Chinese → heuristic doesn't fire, falls to fallback."""
        streams = [
            _sub(stream_id=1, language_code="chi", language="Chinese"),
            _sub(stream_id=2, language_code="eng", language="English"),
        ]
        result = select_best(streams, fallback="skip")
        assert result is None  # skip fallback, no heuristic

    def test_heuristic_fires_even_with_fallback_skip(self):
        """Second-generic applies before fallback — even fallback=skip gets a result."""
        streams = [
            _sub(stream_id=1, language_code="chi", language="Chinese"),
            _sub(stream_id=2, language_code="chi", language="Chinese"),
        ]
        result = select_best(streams, fallback="skip")
        assert result is not None
        assert result.info.stream_id == 2

    def test_heuristic_skipped_when_cht_found(self):
        """If CHT is confidently detected, heuristic is irrelevant."""
        streams = [
            _sub(stream_id=1, language_code="chi", language="Chinese"),
            _sub(stream_id=2, language_code="chi", language="Chinese"),
            _sub(stream_id=3, title="繁體中文", language_code="chi"),
        ]
        result = select_best(streams, fallback="skip")
        assert result is not None
        assert result.info.stream_id == 3  # confident CHT wins
        assert result.score == 100

    def test_confirmed_chs_not_counted_as_unknown(self):
        """CHS + 1 UNKNOWN_ZH → only 1 unknown, heuristic doesn't fire."""
        streams = [
            _sub(stream_id=1, title="简体中文", language_code="chi"),  # CHS
            _sub(stream_id=2, language_code="chi", language="Chinese"),  # UNKNOWN_ZH
        ]
        result = select_best(streams, fallback="skip")
        assert result is None  # 1 unknown, no heuristic, skip

    def test_external_preferred_over_embedded_unknown(self):
        """External SRT (+2 bonus) should beat embedded PGS in 2nd-generic.

        Regression test for 猩球崛起 case: 2 embedded PGS + 1 external SRT,
        all UNKNOWN_ZH. External SRT (score 12) should be preferred over
        the stream_id[1] heuristic (score 10).
        """
        streams = [
            SubtitleInfo(stream_id=100, title=None, language_code="chi",
                         language="Chinese"),  # embedded PGS, score 10
            SubtitleInfo(stream_id=200, title=None, language_code="chi",
                         language="Chinese"),  # embedded PGS, score 10
            SubtitleInfo(stream_id=300, title=None, language_code="chi",
                         language="Chinese", key="/library/streams/99"),  # external SRT, score 12
        ]
        result = select_best(streams, fallback="skip")
        assert result is not None
        assert result.info.stream_id == 300  # external wins
        assert result.score == 12  # 10 + 2 external bonus

    def test_all_embedded_still_uses_stream_order(self):
        """When all UNKNOWN_ZH are embedded (same score), stream_id[1] heuristic applies."""
        streams = [
            SubtitleInfo(stream_id=100, title=None, language_code="chi",
                         language="Chinese"),
            SubtitleInfo(stream_id=200, title=None, language_code="chi",
                         language="Chinese"),
            SubtitleInfo(stream_id=300, title=None, language_code="chi",
                         language="Chinese"),
        ]
        result = select_best(streams, fallback="skip")
        assert result is not None
        assert result.info.stream_id == 200  # second by stream_id


# ===================================================================
# analyze_subtitle_text() — Character frequency analysis
# ===================================================================

class TestAnalyzeSubtitleText:

    def test_traditional_text(self):
        text = "你好，這是一個測試。我們今天要學習的課題是關於電影的歷史。請問你覺得這部電影怎麼樣？我認為導演的選擇很專業。"
        result = analyze_subtitle_text(text)
        assert result is not None
        cat, score = result
        assert cat == SubtitleCategory.CHT
        assert score == 85

    def test_simplified_text(self):
        text = "你好，这是一个测试。我们今天要学习的课题是关于电影的历史。请问你觉得这部电影怎么样？我认为导演的选择很专业。"
        result = analyze_subtitle_text(text)
        assert result is not None
        cat, score = result
        assert cat == SubtitleCategory.CHS
        assert score == -100

    def test_insufficient_data(self):
        text = "Hello World"  # no Chinese chars at all
        assert analyze_subtitle_text(text) is None

    def test_too_few_distinguishing_chars(self):
        text = "你好嗎"  # common chars, no distinguishing ones
        assert analyze_subtitle_text(text) is None

    def test_ambiguous_mix(self):
        """50/50 mix of Traditional and Simplified → ambiguous."""
        text = "這們時從開" + "这们时从开"  # 5 trad + 5 simp
        assert analyze_subtitle_text(text) is None

    def test_mostly_traditional_with_noise(self):
        """80% trad chars should still classify as CHT."""
        text = "這們時從開長問進動現" + "这们"  # 10 trad + 2 simp
        result = analyze_subtitle_text(text)
        assert result is not None
        assert result[0] == SubtitleCategory.CHT


# ===================================================================
# classify() with content analysis
# ===================================================================

class TestClassifyWithContent:

    def test_unknown_zh_with_cht_content(self):
        """UNKNOWN_ZH + Traditional content → CHT 85."""
        content = "你好，這是一個測試。我們今天要學習的課題。"
        result = classify(
            _sub(language_code="chi", language="Chinese"),
            content=content,
        )
        assert result.category == SubtitleCategory.CHT
        assert result.score == 85

    def test_unknown_zh_with_chs_content(self):
        """UNKNOWN_ZH + Simplified content → CHS -100."""
        content = "你好，这是一个测试。我们今天要学习的课题。"
        result = classify(
            _sub(language_code="chi", language="Chinese"),
            content=content,
        )
        assert result.category == SubtitleCategory.CHS
        assert result.score == -100

    def test_unknown_zh_with_insufficient_content(self):
        """UNKNOWN_ZH + too little content → stays UNKNOWN_ZH 10."""
        result = classify(
            _sub(language_code="chi", language="Chinese"),
            content="Hello",
        )
        assert result.category == SubtitleCategory.UNKNOWN_ZH
        assert result.score == 10

    def test_content_ignored_when_not_unknown_zh(self):
        """Content is only used for UNKNOWN_ZH — CHT by title stays 100."""
        content = "这是简体中文内容这们时从开长问进动现"
        result = classify(
            _sub(title="繁體中文", language_code="chi"),
            content=content,
        )
        assert result.category == SubtitleCategory.CHT
        assert result.score == 100  # title match, content ignored

    def test_forced_penalty_with_content_analysis(self):
        """Forced penalty applies on top of content analysis score."""
        content = "你好，這是一個測試。我們今天要學習的課題。"
        result = classify(
            _sub(language_code="chi", language="Chinese", forced=True),
            content=content,
        )
        assert result.category == SubtitleCategory.CHT
        assert result.score == 35  # 85 - 50


# ===================================================================
# select_best() with content_map
# ===================================================================

class TestSelectBestWithContentMap:

    def test_content_map_promotes_unknown_to_cht(self):
        """UNKNOWN_ZH stream gets promoted to CHT via content analysis."""
        streams = [
            _sub(stream_id=1, language_code="chi", language="Chinese"),
            _sub(stream_id=2, language_code="eng", language="English"),
        ]
        content_map = {
            1: "你好，這是一個測試。我們今天要學習的課題是關於電影的歷史。",
        }
        result = select_best(streams, fallback="skip", content_map=content_map)
        assert result is not None
        assert result.info.stream_id == 1
        assert result.category == SubtitleCategory.CHT
        assert result.score == 85

    def test_content_map_detects_chs_triggers_fallback(self):
        """UNKNOWN_ZH detected as CHS via content → fallback to English."""
        streams = [
            _sub(stream_id=1, language_code="chi", language="Chinese"),
            _sub(stream_id=2, language_code="eng", language="English"),
        ]
        content_map = {
            1: "你好，这是一个测试。我们今天要学习的课题是关于电影的历史。",
        }
        result = select_best(streams, fallback="english", content_map=content_map)
        assert result is not None
        assert result.category == SubtitleCategory.ENGLISH
        assert result.info.stream_id == 2

    def test_no_content_map_falls_back(self):
        """Without content_map, UNKNOWN_ZH triggers fallback as before."""
        streams = [
            _sub(stream_id=1, language_code="chi", language="Chinese"),
            _sub(stream_id=2, language_code="eng", language="English"),
        ]
        result = select_best(streams, fallback="english")
        assert result is not None
        assert result.category == SubtitleCategory.ENGLISH


# ===================================================================
# External subtitle bonus (tiebreaker)
# ===================================================================

class TestExternalBonus:

    def test_external_gets_bonus(self):
        """Subtitle with key (external) gets +2 bonus."""
        embedded = classify(SubtitleInfo(
            stream_id=1, title="繁體中文", language_code="chi", language="Chinese",
        ))
        external = classify(SubtitleInfo(
            stream_id=2, title="繁體中文", language_code="chi", language="Chinese",
            key="/library/streams/123",
        ))
        assert external.score == embedded.score + 2

    def test_external_wins_tiebreaker(self):
        """When both embedded and external are CHT, external is preferred."""
        cht_content = "你好，這是一個測試。我們今天要學習的課題是關於電影的歷史。"
        streams = [
            SubtitleInfo(stream_id=1, title=None, language_code="chi",
                         language="Chinese"),  # embedded, no key
            SubtitleInfo(stream_id=2, title=None, language_code="chi",
                         language="Chinese", key="/library/streams/99"),  # external
        ]
        content_map = {
            1: cht_content,
            2: cht_content,
        }
        result = select_best(streams, fallback="skip", content_map=content_map)
        assert result is not None
        assert result.info.stream_id == 2  # external wins
        assert result.score == 87  # 85 + 2
