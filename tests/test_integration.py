"""Integration test — verify the full pipeline without a real Plex server.

Run:  python -m pytest tests/ -v
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from plexchtsubs.config import Config, load_config
from plexchtsubs.detector import SubtitleInfo, SubtitleCategory, classify, select_best
from plexchtsubs.display import display_width, pad, truncate, ScanStats


# ===================================================================
# 1. Config layer merging
# ===================================================================

class TestConfigMerge:
    """Verify config priority: CLI > env > yaml > defaults."""

    def test_defaults(self):
        """No input at all → defaults should apply."""
        with patch("plexchtsubs.config._prompt_token", return_value="fake-token"):
            cfg = load_config(config_path=Path("/nonexistent/config.yaml"))
        assert cfg.plex_url == "http://localhost:32400"
        assert cfg.fallback == "chs"
        assert cfg.scan_range_days == 30
        assert cfg.workers == 8
        assert cfg.dry_run is False

    def test_env_overrides_defaults(self):
        """Environment variables override defaults."""
        env = {"PLEX_URL": "http://mynas:32400", "PLEX_TOKEN": "test-token", "FALLBACK": "english"}
        with patch.dict("os.environ", env, clear=False):
            cfg = load_config()
        assert cfg.plex_url == "http://mynas:32400"
        assert cfg.plex_token == "test-token"
        assert cfg.fallback == "english"

    def test_cli_overrides_env(self):
        """CLI args take highest priority."""
        env = {"PLEX_TOKEN": "env-token", "FALLBACK": "chs"}
        cli = MagicMock()
        cli.plex_url = None
        cli.plex_token = "cli-token"
        cli.scan_range = 7
        cli.fallback = "none"
        cli.force = True
        cli.workers = 4
        cli.dry_run = True
        cli.verbose = None
        cli.log_file = None
        cli.schedule_enabled = None
        cli.schedule_cron = None
        cli.watch_enabled = None
        cli.watch_debounce = None
        cli.web_enabled = None
        cli.web_port = None
        with patch.dict("os.environ", env, clear=False):
            cfg = load_config(cli_args=cli)
        assert cfg.plex_token == "cli-token"  # CLI wins over env
        assert cfg.fallback == "none"          # CLI wins over env
        assert cfg.scan_range_days == 7
        assert cfg.force_overwrite is True
        assert cfg.dry_run is True

    def test_scan_range_zero_means_full(self):
        """--scan-range 0 should be converted to None (full scan)."""
        cli = MagicMock()
        cli.plex_url = None
        cli.plex_token = "tok"
        cli.scan_range = 0
        cli.fallback = None
        cli.force = None
        cli.workers = None
        cli.dry_run = None
        cli.verbose = None
        cli.log_file = None
        cli.schedule_enabled = None
        cli.schedule_cron = None
        cli.watch_enabled = None
        cli.watch_debounce = None
        cli.web_enabled = None
        cli.web_port = None
        cfg = load_config(cli_args=cli)
        assert cfg.scan_range_days is None

    def test_defaults_include_watch_fields(self):
        """Default config should include watch fields."""
        with patch("plexchtsubs.config._prompt_token", return_value="fake-token"):
            cfg = load_config(config_path=Path("/nonexistent/config.yaml"))
        assert cfg.watch_enabled is False
        assert cfg.watch_debounce == 5.0

    def test_watch_env_overrides(self):
        """WATCH_ENABLED and WATCH_DEBOUNCE env vars should work."""
        env = {"PLEX_TOKEN": "tok", "WATCH_ENABLED": "true", "WATCH_DEBOUNCE": "10.0"}
        with patch.dict("os.environ", env, clear=False):
            cfg = load_config(config_path=Path("/nonexistent/config.yaml"))
        assert cfg.watch_enabled is True
        assert cfg.watch_debounce == 10.0

    def test_defaults_include_web_fields(self):
        """Default config should include web fields."""
        with patch("plexchtsubs.config._prompt_token", return_value="fake-token"):
            cfg = load_config(config_path=Path("/nonexistent/config.yaml"))
        assert cfg.web_enabled is False
        assert cfg.web_port == 9527
        assert cfg.web_host == "0.0.0.0"
        assert cfg.web_username is None
        assert cfg.web_password is None

    def test_web_env_overrides(self):
        """WEB_ENABLED and WEB_PORT env vars should work."""
        env = {"PLEX_TOKEN": "tok", "WEB_ENABLED": "true", "WEB_PORT": "3000"}
        with patch.dict("os.environ", env, clear=False):
            cfg = load_config(config_path=Path("/nonexistent/config.yaml"))
        assert cfg.web_enabled is True
        assert cfg.web_port == 3000


# ===================================================================
# 2. Real-world subtitle scenarios
# ===================================================================

class TestRealWorldScenarios:
    """Simulate actual subtitle combinations commonly found in media files."""

    def test_japanese_anime_with_cht_and_chs(self):
        """Typical anime: has both 繁中 and 简中 tracks."""
        streams = [
            SubtitleInfo(stream_id=1, title="简日双语", language_code="chi", language="Chinese", forced=False),
            SubtitleInfo(stream_id=2, title="繁日雙語", language_code="chi", language="Chinese", forced=False),
            SubtitleInfo(stream_id=3, title=None, language_code="jpn", language="Japanese", forced=False),
        ]
        result = select_best(streams, fallback="skip")
        assert result is not None
        assert result.info.stream_id == 2
        assert result.category == SubtitleCategory.CHT

    def test_hollywood_movie_english_only(self):
        """Western movie with only English subs — fallback decides."""
        streams = [
            SubtitleInfo(stream_id=1, title="English", language_code="eng", language="English", forced=False),
            SubtitleInfo(stream_id=2, title="English (Forced)", language_code="eng", language="English", forced=True),
        ]
        # fallback=skip → no change
        assert select_best(streams, fallback="skip") is None
        # fallback=english → pick non-forced English
        result = select_best(streams, fallback="english")
        assert result is not None
        assert result.info.stream_id == 1

    def test_generic_chinese_no_title(self):
        """Two Chinese tracks with no title — "second generic" heuristic picks second."""
        streams = [
            SubtitleInfo(stream_id=1, title=None, language_code="chi", language="Chinese", forced=False),
            SubtitleInfo(stream_id=2, title=None, language_code="chi", language="Chinese", forced=False),
        ]
        # 2 UNKNOWN_ZH tracks → "second generic" heuristic picks stream 2
        result = select_best(streams, fallback="skip")
        assert result is not None
        assert result.info.stream_id == 2

    def test_plex_metadata_traditional(self):
        """Plex sometimes puts variant info in the language description."""
        streams = [
            SubtitleInfo(stream_id=1, title=None, language_code="chi",
                         language="Chinese (Traditional)", forced=False),
            SubtitleInfo(stream_id=2, title=None, language_code="chi",
                         language="Chinese (Simplified)", forced=False),
        ]
        result = select_best(streams, fallback="skip")
        assert result is not None
        assert result.info.stream_id == 1
        assert result.score == 90

    def test_forced_cht_still_selected(self):
        """Forced CHT (score=50) should still be selected — it's still CHT."""
        streams = [
            SubtitleInfo(stream_id=1, title="繁體中文", language_code="chi",
                         language="Chinese", forced=True),
        ]
        result = select_best(streams, fallback="skip")
        # Category-based selection: CHT is detected regardless of score
        assert result is not None
        assert result.info.stream_id == 1
        assert result.category == SubtitleCategory.CHT
        assert result.score == 50  # 100 - 50 forced penalty

    def test_forced_and_non_forced_cht(self):
        """Both forced and non-forced CHT — should prefer non-forced."""
        streams = [
            SubtitleInfo(stream_id=1, title="繁體中文 Forced", language_code="chi",
                         language="Chinese", forced=True),
            SubtitleInfo(stream_id=2, title="繁體中文", language_code="chi",
                         language="Chinese", forced=False),
        ]
        result = select_best(streams, fallback="skip")
        assert result is not None
        assert result.info.stream_id == 2
        assert result.score == 100


# ===================================================================
# 2b. _process_item early-exit for no subtitle streams
# ===================================================================

class TestProcessItemNoSubs:
    """Items with zero subtitle streams should be skipped silently."""

    def test_no_subtitle_streams_skips(self):
        """A video with no subtitle streams (burned-in only) should skip."""
        from unittest.mock import MagicMock
        from plexchtsubs.scanner import _process_item
        from plexchtsubs.display import ScanStats

        plex = MagicMock()
        video = MagicMock()
        video.title = "Some Movie"
        video.subtitleStreams.return_value = []
        plex.fetchItem.return_value = video

        config = MagicMock()
        config.fallback = "skip"
        stats = ScanStats()
        stats_lock = __import__("threading").Lock()

        _process_item(plex, 12345, config, stats, stats_lock)
        assert stats.total == 1
        assert stats.skipped == 1
        assert stats.changed == 0

    def test_with_subtitle_streams_processes(self):
        """A video WITH subtitle streams should proceed normally (not early-exit)."""
        from unittest.mock import MagicMock, PropertyMock
        from plexchtsubs.scanner import _process_item
        from plexchtsubs.display import ScanStats

        plex = MagicMock()
        video = MagicMock()
        video.title = "Anime Movie"
        video.type = "movie"
        video.year = 2024

        # Simulate one CHT subtitle stream
        stream = MagicMock()
        stream.id = 1
        stream.title = "繁體中文"
        stream.languageCode = "chi"
        stream.language = "Chinese"
        stream.forced = False
        stream.selected = True
        stream.codec = "srt"
        video.subtitleStreams.return_value = [stream]
        plex.fetchItem.return_value = video

        config = MagicMock()
        config.fallback = "skip"
        config.force_overwrite = False
        config.dry_run = False
        stats = ScanStats()
        stats_lock = __import__("threading").Lock()

        _process_item(plex, 12345, config, stats, stats_lock)
        # Should have processed (not early-exited) — "already set" counts as total+skipped
        assert stats.total == 1
        assert stats.skipped == 1  # already selected, not forced


# ===================================================================
# 3. Display utilities
# ===================================================================

class TestDisplay:

    def test_cjk_width(self):
        assert display_width("Hello") == 5
        assert display_width("繁體中文") == 8  # 4 chars × 2
        assert display_width("abc繁體") == 7   # 3 + 4

    def test_pad(self):
        result = pad("Hi", 10)
        assert len(result) == 10

    def test_truncate_short_string(self):
        assert truncate("short", 20) == "short"

    def test_truncate_long_string(self):
        result = truncate("This is a very long title", 15)
        assert result.endswith("...")
        assert display_width(result) <= 15

    def test_truncate_cjk(self):
        result = truncate("繁體中文字幕測試標題很長", 15)
        assert result.endswith("...")
        assert display_width(result) <= 15
