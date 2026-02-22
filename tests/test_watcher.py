"""Tests for PlexWatcher (event filtering, debounce, reconnect) and _put_with_retry."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from plexchtsubs.config import Config
from plexchtsubs.scanner import _put_with_retry
from plexchtsubs.watcher import PlexWatcher, _STATE_DONE, _TYPE_MOVIE, _TYPE_EPISODE


def _config(**overrides) -> Config:
    defaults = dict(
        plex_url="http://localhost:32400",
        plex_token="test-token",
        watch_enabled=True,
        watch_debounce=0.2,  # fast debounce for tests
        workers=2,
        fallback="skip",
        dry_run=True,
    )
    defaults.update(overrides)
    return Config(**defaults)


def _make_timeline(item_id, state=_STATE_DONE, item_type=_TYPE_EPISODE):
    return {
        "type": "timeline",
        "TimelineEntry": [{"state": state, "type": item_type, "itemID": item_id}],
    }


# ---------------------------------------------------------------------------
# Event Filtering
# ---------------------------------------------------------------------------


class TestEventFiltering:
    def test_ignores_non_timeline(self):
        plex = MagicMock()
        w = PlexWatcher(plex, _config())
        w._on_alert({"type": "playing", "PlaySessionStateNotification": []})
        assert len(w._pending) == 0

    def test_ignores_non_done_state(self):
        plex = MagicMock()
        w = PlexWatcher(plex, _config())
        w._on_alert(_make_timeline(100, state=2))
        assert len(w._pending) == 0

    def test_ignores_non_video_type(self):
        plex = MagicMock()
        w = PlexWatcher(plex, _config())
        # type=2 is show (not movie/episode)
        w._on_alert(_make_timeline(100, item_type=2))
        assert len(w._pending) == 0

    def test_accepts_movie(self):
        plex = MagicMock()
        w = PlexWatcher(plex, _config())
        w._on_alert(_make_timeline(100, item_type=_TYPE_MOVIE))
        assert 100 in w._pending

    def test_accepts_episode(self):
        plex = MagicMock()
        w = PlexWatcher(plex, _config())
        w._on_alert(_make_timeline(200, item_type=_TYPE_EPISODE))
        assert 200 in w._pending

    def test_deduplicates(self):
        plex = MagicMock()
        w = PlexWatcher(plex, _config())
        w._on_alert(_make_timeline(100))
        w._on_alert(_make_timeline(100))
        assert len(w._pending) == 1

    def test_multiple_entries(self):
        plex = MagicMock()
        w = PlexWatcher(plex, _config())
        w._on_alert({
            "type": "timeline",
            "TimelineEntry": [
                {"state": _STATE_DONE, "type": _TYPE_MOVIE, "itemID": 10},
                {"state": _STATE_DONE, "type": _TYPE_EPISODE, "itemID": 20},
                {"state": 2, "type": _TYPE_EPISODE, "itemID": 30},  # ignored
            ],
        })
        assert w._pending == {10, 20}


# ---------------------------------------------------------------------------
# Debounce
# ---------------------------------------------------------------------------


class TestDebounce:
    @patch("plexchtsubs.watcher.PlexWatcher._flush_pending")
    def test_single_event_flushes_after_debounce(self, mock_flush):
        plex = MagicMock()
        w = PlexWatcher(plex, _config(watch_debounce=0.15))
        w._on_alert(_make_timeline(100))
        assert len(w._pending) == 1
        time.sleep(0.3)
        mock_flush.assert_called_once()

    @patch("plexchtsubs.watcher.PlexWatcher._flush_pending")
    def test_rapid_events_batch(self, mock_flush):
        plex = MagicMock()
        w = PlexWatcher(plex, _config(watch_debounce=0.2))
        for i in range(5):
            w._on_alert(_make_timeline(i + 1))
            time.sleep(0.05)
        # All 5 should be pending, flush not yet called
        assert len(w._pending) == 5
        time.sleep(0.4)
        mock_flush.assert_called_once()

    @patch("plexchtsubs.watcher.PlexWatcher._flush_pending")
    def test_timer_resets_on_new_event(self, mock_flush):
        plex = MagicMock()
        w = PlexWatcher(plex, _config(watch_debounce=0.2))
        w._on_alert(_make_timeline(1))
        time.sleep(0.15)
        w._on_alert(_make_timeline(2))  # resets timer
        time.sleep(0.15)
        # Should NOT have flushed yet (timer was reset)
        mock_flush.assert_not_called()
        time.sleep(0.15)
        mock_flush.assert_called_once()


# ---------------------------------------------------------------------------
# Start / Stop
# ---------------------------------------------------------------------------


class TestStartStop:
    def test_stop_cancels_timer(self):
        plex = MagicMock()
        w = PlexWatcher(plex, _config(watch_debounce=10))
        w._on_alert(_make_timeline(100))
        assert w._timer is not None
        w.stop()
        assert w._timer is None

    def test_double_stop_is_safe(self):
        plex = MagicMock()
        w = PlexWatcher(plex, _config())
        w.stop()
        w.stop()  # should not raise


# ---------------------------------------------------------------------------
# Auto-reconnect
# ---------------------------------------------------------------------------


class TestReconnect:
    def test_on_error_triggers_reconnect(self):
        plex = MagicMock()
        w = PlexWatcher(plex, _config())
        w._running = True
        with patch.object(w, "_reconnect"):
            w._on_error(Exception("connection lost"))
        assert not w._running

    def test_stop_interrupts_reconnect(self):
        plex = MagicMock()
        w = PlexWatcher(plex, _config())
        w._running = False
        # Start reconnect in background, then immediately stop
        thread = threading.Thread(target=w._reconnect, daemon=True)
        thread.start()
        time.sleep(0.1)
        w.stop()  # sets _stop_event
        thread.join(timeout=2)
        assert not thread.is_alive()


# ---------------------------------------------------------------------------
# _put_with_retry
# ---------------------------------------------------------------------------


class TestPutWithRetry:
    def test_success_first_attempt(self):
        with patch("plexchtsubs.scanner.requests.put") as mock_put:
            mock_put.return_value = MagicMock(status_code=200)
            resp = _put_with_retry("http://test", {}, max_retries=3, base_delay=0.01)
            assert resp.status_code == 200
            assert mock_put.call_count == 1

    def test_retries_on_connection_error(self):
        with patch("plexchtsubs.scanner.requests.put") as mock_put:
            mock_put.side_effect = [
                requests.ConnectionError("fail"),
                MagicMock(status_code=200),
            ]
            resp = _put_with_retry("http://test", {}, max_retries=3, base_delay=0.01)
            assert resp.status_code == 200
            assert mock_put.call_count == 2

    def test_retries_on_timeout(self):
        with patch("plexchtsubs.scanner.requests.put") as mock_put:
            mock_put.side_effect = [
                requests.Timeout("timeout"),
                MagicMock(status_code=200),
            ]
            resp = _put_with_retry("http://test", {}, max_retries=3, base_delay=0.01)
            assert resp.status_code == 200
            assert mock_put.call_count == 2

    def test_retries_on_500(self):
        with patch("plexchtsubs.scanner.requests.put") as mock_put:
            mock_put.side_effect = [
                MagicMock(status_code=500),
                MagicMock(status_code=200),
            ]
            resp = _put_with_retry("http://test", {}, max_retries=3, base_delay=0.01)
            assert resp.status_code == 200
            assert mock_put.call_count == 2

    def test_no_retry_on_400(self):
        with patch("plexchtsubs.scanner.requests.put") as mock_put:
            mock_put.return_value = MagicMock(status_code=400)
            resp = _put_with_retry("http://test", {}, max_retries=3, base_delay=0.01)
            assert resp.status_code == 400
            assert mock_put.call_count == 1

    def test_raises_after_max_retries(self):
        with patch("plexchtsubs.scanner.requests.put") as mock_put:
            mock_put.side_effect = requests.ConnectionError("fail")
            with pytest.raises(requests.ConnectionError):
                _put_with_retry("http://test", {}, max_retries=2, base_delay=0.01)
            assert mock_put.call_count == 3  # initial + 2 retries
