from __future__ import annotations

import secrets
from datetime import UTC, datetime
from urllib.parse import urlencode

from app.core.config import get_settings
from app.models.oauth_connection import OAuthConnection
from app.repositories.session import SessionRepository
from app.schemas.strava import (
    StravaConnectUrlResponse,
    StravaConnectionStatus,
    StravaSyncJobResponse,
)
from app.models.sync_job import SyncJob

settings = get_settings()


class StravaService:
    def __init__(self, db):
        self.db = db

    def build_connect_url(self) -> StravaConnectUrlResponse:
        state = secrets.token_urlsafe(24)
        params = {
            "client_id": settings.strava_client_id or "set-in-env",
            "redirect_uri": settings.strava_redirect_uri or "http://localhost:8000/api/v1/strava/callback",
            "response_type": "code",
            "approval_prompt": "auto",
            "scope": "read,activity:read_all,profile:read_all",
            "state": state,
        }
        authorize_url = f"https://www.strava.com/oauth/authorize?{urlencode(params)}"
        return StravaConnectUrlResponse(authorize_url=authorize_url, state=state)

    def get_connection_status(self, user_id: str) -> StravaConnectionStatus:
        connection = (
            self.db.query(OAuthConnection)
            .filter(OAuthConnection.user_id == user_id, OAuthConnection.provider == "strava", OAuthConnection.is_active.is_(True))
            .one_or_none()
        )
        if connection is None:
            return StravaConnectionStatus(connected=False)
        return StravaConnectionStatus(
            connected=True,
            athlete_id=connection.provider_user_id,
            scopes=connection.scopes or [],
            last_sync_at=connection.last_sync_at,
        )

    def enqueue_sync(self, user_id: str, *, full_sync: bool) -> StravaSyncJobResponse:
        job_type = "historical_import" if full_sync else "incremental_sync"
        job = SyncJob(
            user_id=user_id,
            provider="strava",
            job_type=job_type,
            status="queued",
            payload_json={"full_sync": full_sync, "requested_at": datetime.now(UTC).isoformat()},
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return StravaSyncJobResponse(job_id=str(job.id), status=job.status, job_type=job.job_type)
