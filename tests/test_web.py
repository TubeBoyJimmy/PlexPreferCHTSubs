"""Tests for web UI API endpoints."""

import threading
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from fastapi.testclient import TestClient

from plexchtsubs.config import Config
from plexchtsubs.display import ScanStats
from plexchtsubs.history import ScanHistoryStore
from plexchtsubs.web import create_app


@pytest.fixture
def mock_plex():
    plex = MagicMock()
    plex.friendlyName = "TestPlex"
    plex.version = "1.32.0"
    return plex


@pytest.fixture
def config():
    return Config(
        plex_url="http://localhost:32400",
        plex_token="test-token",
        fallback="chs",
        scan_range_days=30,
        workers=4,
    )


@pytest.fixture
def history(tmp_path):
    return ScanHistoryStore(str(tmp_path / "test.db"))


@pytest.fixture
def client(mock_plex, config, history):
    app = create_app(mock_plex, config, history=history)
    return TestClient(app)


class TestHealth:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class TestStatus:
    def test_status_connected(self, client):
        r = client.get("/api/status")
        assert r.status_code == 200
        data = r.json()
        assert data["version"] is not None
        assert data["plex"]["connected"] is True
        assert data["plex"]["server_name"] == "TestPlex"
        assert data["plex"]["server_version"] == "1.32.0"
        assert data["scan"]["running"] is False
        assert data["watcher"] is None  # no watcher provided

    def test_status_with_watcher(self, mock_plex, config, history):
        watcher = MagicMock()
        watcher.is_running = True
        app = create_app(mock_plex, config, history=history, watcher=watcher)
        client = TestClient(app)
        r = client.get("/api/status")
        data = r.json()
        assert data["watcher"]["running"] is True


class TestConfig:
    def test_config_no_token(self, client):
        """Config endpoint should not expose the Plex token."""
        r = client.get("/api/config")
        assert r.status_code == 200
        data = r.json()
        assert "plex_token" not in data
        assert "token" not in data
        assert data["plex_url"] == "http://localhost:32400"
        assert data["fallback"] == "chs"
        assert data["workers"] == 4

    def test_config_values(self, client):
        r = client.get("/api/config")
        data = r.json()
        assert data["scan_range_days"] == 30
        assert data["web_auth_enabled"] is False


class TestHistory:
    def test_empty_history(self, client):
        r = client.get("/api/history")
        assert r.status_code == 200
        assert r.json() == []

    def test_history_with_records(self, client, history):
        history.record(duration=5.0, total=50, changed=3, trigger="manual")
        history.record(duration=10.0, total=100, changed=8, trigger="cron")

        r = client.get("/api/history")
        data = r.json()
        assert len(data) == 2
        assert data[0]["trigger"] == "cron"  # newest first
        assert data[1]["trigger"] == "manual"

    def test_history_limit(self, client, history):
        for _ in range(5):
            history.record(duration=1.0, total=10, trigger="manual")

        r = client.get("/api/history?limit=2")
        assert len(r.json()) == 2


class TestScan:
    def test_trigger_scan(self, client):
        """Scan should start in a background thread."""
        with patch("plexchtsubs.scanner.scan_library") as mock_scan:
            mock_scan.return_value = ScanStats()
            r = client.post("/api/scan", json={"dry_run": True, "scan_range": 7})
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "started"

    def test_scan_conflict(self, client):
        """Should reject if a scan is already running."""
        # Simulate a running scan
        client.app.state.app.scan_running = True
        r = client.post("/api/scan", json={})
        assert r.status_code == 409
        client.app.state.app.scan_running = False

    def test_scan_status_idle(self, client):
        r = client.get("/api/scan/status")
        assert r.status_code == 200
        data = r.json()
        assert data["running"] is False


class TestDashboard:
    def test_serve_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "PlexPreferCHTSubs" in r.text


class TestBasicAuth:
    def test_auth_required(self, mock_plex, history):
        config = Config(
            plex_url="http://localhost:32400",
            plex_token="test-token",
            web_username="admin",
            web_password="secret",
        )
        app = create_app(mock_plex, config, history=history)
        client = TestClient(app)

        # No auth → 401
        r = client.get("/api/status")
        assert r.status_code == 401

        # Wrong credentials → 401
        r = client.get("/api/status", auth=("wrong", "wrong"))
        assert r.status_code == 401

        # Correct credentials → 200
        r = client.get("/api/status", auth=("admin", "secret"))
        assert r.status_code == 200

    def test_no_auth_when_disabled(self, client):
        """Auth not required when username/password not set."""
        r = client.get("/api/status")
        assert r.status_code == 200
