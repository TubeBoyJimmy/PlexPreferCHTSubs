"""Tests for scan history SQLite store."""

import os
import tempfile

import pytest

from plexchtsubs.history import ScanHistoryStore


@pytest.fixture
def store(tmp_path):
    """Create a history store backed by a temp database."""
    db_path = str(tmp_path / "test_history.db")
    return ScanHistoryStore(db_path)


class TestScanHistoryStore:

    def test_record_and_list(self, store):
        scan_id = store.record(
            duration=12.5,
            total=100,
            changed=10,
            skipped=85,
            fallback_used=3,
            errors=2,
            dry_run=False,
            trigger="manual",
        )
        assert scan_id == 1

        rows = store.list_recent()
        assert len(rows) == 1
        row = rows[0]
        assert row["total"] == 100
        assert row["changed"] == 10
        assert row["skipped"] == 85
        assert row["fallback_used"] == 3
        assert row["errors"] == 2
        assert row["dry_run"] == 0
        assert row["trigger"] == "manual"
        assert row["duration"] == 12.5
        assert row["finished_at"] is not None

    def test_start_and_finish(self, store):
        scan_id = store.start_scan(trigger="cron", dry_run=True)
        assert scan_id == 1

        # Before finish, should have started_at but no finished_at
        row = store.get(scan_id)
        assert row["started_at"] is not None
        assert row["finished_at"] is None
        assert row["trigger"] == "cron"
        assert row["dry_run"] == 1

        store.finish_scan(
            scan_id, duration=5.0, total=50, changed=3,
        )
        row = store.get(scan_id)
        assert row["finished_at"] is not None
        assert row["duration"] == 5.0
        assert row["total"] == 50
        assert row["changed"] == 3

    def test_list_recent_ordering(self, store):
        """Most recent scans should be first."""
        for i in range(5):
            store.record(duration=float(i), total=i * 10, trigger="cron")

        rows = store.list_recent(limit=3)
        assert len(rows) == 3
        # Newest first (highest ID)
        assert rows[0]["id"] == 5
        assert rows[1]["id"] == 4
        assert rows[2]["id"] == 3

    def test_list_recent_limit(self, store):
        for i in range(10):
            store.record(duration=1.0, total=10, trigger="manual")

        assert len(store.list_recent(limit=5)) == 5
        assert len(store.list_recent(limit=50)) == 10

    def test_get_nonexistent(self, store):
        assert store.get(999) is None

    def test_empty_list(self, store):
        assert store.list_recent() == []

    def test_multiple_triggers(self, store):
        store.record(duration=1.0, total=10, trigger="manual")
        store.record(duration=2.0, total=20, trigger="cron")
        store.record(duration=3.0, total=30, trigger="watcher")

        rows = store.list_recent()
        triggers = [r["trigger"] for r in rows]
        assert triggers == ["watcher", "cron", "manual"]
