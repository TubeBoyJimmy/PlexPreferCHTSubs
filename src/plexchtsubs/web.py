"""Web UI dashboard — FastAPI application."""

from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from plexchtsubs import __version__
from plexchtsubs.display import ScanStats
from plexchtsubs.history import ScanHistoryStore

if TYPE_CHECKING:
    from plexapi.server import PlexServer
    from plexchtsubs.config import Config
    from plexchtsubs.watcher import PlexWatcher

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


class AppState:
    """Shared mutable state between web routes and background tasks."""

    def __init__(
        self,
        plex: PlexServer,
        config: Config,
        history: ScanHistoryStore,
        watcher: Optional[PlexWatcher] = None,
    ) -> None:
        self.plex = plex
        self.config = config
        self.history = history
        self.watcher = watcher
        self.scan_running = False
        self.scan_started_at: Optional[float] = None
        self.current_scan_stats: Optional[ScanStats] = None
        self.current_scan_id: Optional[int] = None
        self._lock = threading.Lock()


def create_app(
    plex: PlexServer,
    config: Config,
    history: ScanHistoryStore,
    watcher: Optional[PlexWatcher] = None,
) -> FastAPI:
    """Build and return the FastAPI application."""
    app = FastAPI(
        title="PlexPreferCHTSubs",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
    )
    state = AppState(plex, config, history, watcher)
    app.state.app = state

    # --- Auth ---
    security = HTTPBasic()

    def _check_auth(credentials: HTTPBasicCredentials = Depends(security)):
        if not (config.web_username and config.web_password):
            return  # auth disabled
        correct_user = secrets.compare_digest(
            credentials.username.encode(), config.web_username.encode()
        )
        correct_pass = secrets.compare_digest(
            credentials.password.encode(), config.web_password.encode()
        )
        if not (correct_user and correct_pass):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Basic"},
            )

    def _optional_auth():
        """Return the auth dependency only if credentials are configured."""
        if config.web_username and config.web_password:
            return [Depends(_check_auth)]
        return []

    deps = _optional_auth()

    # --- Routes ---

    @app.get("/", include_in_schema=False)
    async def dashboard():
        return FileResponse(_STATIC_DIR / "index.html")

    @app.get("/api/health", dependencies=deps)
    async def health():
        return {"status": "ok"}

    @app.get("/api/status", dependencies=deps)
    async def get_status():
        s = state
        try:
            server_name = s.plex.friendlyName
            server_version = s.plex.version
            plex_connected = True
        except Exception:
            server_name = None
            server_version = None
            plex_connected = False

        watcher_info = None
        if s.watcher is not None:
            watcher_info = {
                "running": s.watcher.is_running,
                "debounce": s.config.watch_debounce,
            }

        scan_info = {"running": s.scan_running}
        if s.scan_running and s.current_scan_stats is not None:
            scan_info["started_at"] = s.scan_started_at
            scan_info["processed"] = s.current_scan_stats.total

        return {
            "version": __version__,
            "plex": {
                "connected": plex_connected,
                "server_name": server_name,
                "server_version": server_version,
                "url": s.config.plex_url,
            },
            "watcher": watcher_info,
            "scan": scan_info,
            "schedule": {
                "enabled": s.config.schedule_enabled,
                "cron": s.config.schedule_cron if s.config.schedule_enabled else None,
            },
        }

    @app.post("/api/scan", dependencies=deps)
    async def trigger_scan(request: Request):
        s = state
        if s.scan_running:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A scan is already running.",
            )

        body = {}
        try:
            body = await request.json()
        except Exception:
            pass

        dry_run = body.get("dry_run", s.config.dry_run)
        scan_range = body.get("scan_range", s.config.scan_range_days)
        fallback = body.get("fallback", s.config.fallback)

        def _run():
            from dataclasses import replace as dc_replace
            from plexapi.server import PlexServer as PS

            from plexchtsubs.scanner import scan_library

            s.scan_running = True
            s.scan_started_at = time.time()
            stats = ScanStats()
            s.current_scan_stats = stats
            scan_id = s.history.start_scan(
                trigger="manual", dry_run=dry_run,
            )
            s.current_scan_id = scan_id

            try:
                # Build a scan-specific config override
                from plexchtsubs.config import Config

                scan_config = Config(
                    plex_url=s.config.plex_url,
                    plex_token=s.config.plex_token,
                    scan_range_days=scan_range if scan_range != 0 else None,
                    fallback=fallback,
                    force_overwrite=s.config.force_overwrite,
                    workers=s.config.workers,
                    dry_run=dry_run,
                    verbose=s.config.verbose,
                )

                # Reconnect to avoid stale connection
                plex_conn = PS(s.config.plex_url, s.config.plex_token)
                result = scan_library(plex_conn, scan_config)

                duration = time.time() - s.scan_started_at
                s.history.finish_scan(
                    scan_id,
                    duration=duration,
                    total=result.total,
                    changed=result.changed,
                    skipped=result.skipped,
                    fallback_used=result.fallback_used,
                    errors=result.errors,
                )
            except Exception as e:
                logger.error("Web-triggered scan failed: %s", e)
                duration = time.time() - s.scan_started_at
                s.history.finish_scan(
                    scan_id, duration=duration,
                    errors=1,
                )
            finally:
                s.scan_running = False
                s.current_scan_stats = None
                s.current_scan_id = None
                s.scan_started_at = None

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        return {"status": "started", "message": "Scan triggered successfully."}

    @app.get("/api/scan/status", dependencies=deps)
    async def scan_status():
        s = state
        result = {"running": s.scan_running}
        if s.scan_running:
            result["started_at"] = s.scan_started_at
            if s.current_scan_stats is not None:
                result["processed"] = s.current_scan_stats.total
            if s.scan_started_at:
                result["elapsed"] = round(time.time() - s.scan_started_at, 1)
        return result

    @app.get("/api/history", dependencies=deps)
    async def get_history(limit: int = 50):
        return state.history.list_recent(limit=limit)

    @app.get("/api/config", dependencies=deps)
    async def get_config():
        c = state.config
        return {
            "plex_url": c.plex_url,
            "scan_range_days": c.scan_range_days,
            "fallback": c.fallback,
            "force_overwrite": c.force_overwrite,
            "workers": c.workers,
            "dry_run": c.dry_run,
            "schedule_enabled": c.schedule_enabled,
            "schedule_cron": c.schedule_cron,
            "watch_enabled": c.watch_enabled,
            "watch_debounce": c.watch_debounce,
            "web_host": c.web_host,
            "web_port": c.web_port,
            "web_auth_enabled": bool(c.web_username and c.web_password),
        }

    return app
