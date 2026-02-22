"""Scan history persistence using SQLite."""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class ScanHistoryStore:
    """Thread-safe SQLite store for scan history records."""

    def __init__(self, db_path: str = "scan_history.db") -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS scan_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        started_at TEXT NOT NULL,
                        finished_at TEXT,
                        duration REAL,
                        total INTEGER DEFAULT 0,
                        changed INTEGER DEFAULT 0,
                        skipped INTEGER DEFAULT 0,
                        fallback_used INTEGER DEFAULT 0,
                        errors INTEGER DEFAULT 0,
                        dry_run BOOLEAN DEFAULT 0,
                        trigger TEXT DEFAULT 'manual'
                    )
                """)
                conn.commit()
            finally:
                conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def start_scan(self, trigger: str = "manual", dry_run: bool = False) -> int:
        """Record the start of a scan. Returns the scan ID."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "INSERT INTO scan_history (started_at, trigger, dry_run) VALUES (?, ?, ?)",
                    (now, trigger, dry_run),
                )
                conn.commit()
                return cur.lastrowid
            finally:
                conn.close()

    def finish_scan(
        self,
        scan_id: int,
        *,
        duration: float,
        total: int = 0,
        changed: int = 0,
        skipped: int = 0,
        fallback_used: int = 0,
        errors: int = 0,
    ) -> None:
        """Update a scan record with final results."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """UPDATE scan_history
                       SET finished_at=?, duration=?, total=?, changed=?,
                           skipped=?, fallback_used=?, errors=?
                       WHERE id=?""",
                    (now, duration, total, changed, skipped, fallback_used, errors, scan_id),
                )
                conn.commit()
            finally:
                conn.close()

    def record(
        self,
        *,
        duration: float,
        total: int = 0,
        changed: int = 0,
        skipped: int = 0,
        fallback_used: int = 0,
        errors: int = 0,
        dry_run: bool = False,
        trigger: str = "manual",
    ) -> int:
        """Convenience: record a completed scan in one call."""
        scan_id = self.start_scan(trigger=trigger, dry_run=dry_run)
        self.finish_scan(
            scan_id,
            duration=duration,
            total=total,
            changed=changed,
            skipped=skipped,
            fallback_used=fallback_used,
            errors=errors,
        )
        return scan_id

    def list_recent(self, limit: int = 50) -> list[dict]:
        """Return the most recent scan records."""
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM scan_history ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                return [dict(row) for row in rows]
            finally:
                conn.close()

    def get(self, scan_id: int) -> Optional[dict]:
        """Return a single scan record by ID."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM scan_history WHERE id=?",
                    (scan_id,),
                ).fetchone()
                return dict(row) if row else None
            finally:
                conn.close()
