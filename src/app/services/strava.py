from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlparse, urlunparse

import httpx
from fastapi import HTTPException, status

from app.core.config import get_settings
from app.core.security import (
    create_signed_state,
    decode_signed_state,
    decrypt_secret,
    encrypt_secret,
)
from app.models.oauth_connection import OAuthConnection
from app.models.sync_job import SyncJob
from app.repositories.oauth_connection import OAuthConnectionRepository
from app.repositories.strava_activity import StravaActivityRepository
from app.schemas.strava import (
    StravaConnectionStatus,
    StravaConnectUrlResponse,
    StravaOAuthCallbackResponse,
    StravaSyncJobResponse,
)

settings = get_settings()


class StravaService:
    def __init__(self, db):
        self.db = db
        self.connections = OAuthConnectionRepository(db) if db is not None else None
        self.activities = StravaActivityRepository(db) if db is not None else None

    def build_connect_url(self, *, user_id: str) -> StravaConnectUrlResponse:
        if not settings.strava_client_id or not settings.strava_redirect_uri:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Strava OAuth not configured",
            )

        state = create_signed_state(
            {"user_id": user_id, "nonce": secrets.token_urlsafe(12)},
            expires_in_minutes=settings.strava_oauth_state_ttl_minutes,
        )
        params = {
            "client_id": settings.strava_client_id,
            "redirect_uri": settings.strava_redirect_uri,
            "response_type": "code",
            "approval_prompt": "auto",
            "scope": "read,activity:read_all,profile:read_all",
            "state": state,
        }
        authorize_url = f"https://www.strava.com/oauth/authorize?{urlencode(params)}"
        return StravaConnectUrlResponse(authorize_url=authorize_url, state=state)

    def handle_callback(
        self, *, code: str, state: str, scope: str | None
    ) -> StravaOAuthCallbackResponse:
        if self.db is None or self.connections is None:
            raise RuntimeError("Database session required")

        payload = decode_signed_state(state)
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Missing user in OAuth state"
            )

        token_payload = self._exchange_code_for_token(code)
        athlete = token_payload.get("athlete") or {}
        athlete_id = str(athlete.get("id") or "")
        if not athlete_id:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="Strava response missing athlete id"
            )

        raw_scope = scope if scope is not None else token_payload.get("scope")
        scopes = [item.strip() for item in str(raw_scope or "").split(",") if item.strip()]
        expires_at = datetime.fromtimestamp(int(token_payload["expires_at"]), tz=UTC)
        athlete_name = (
            " ".join(filter(None, [athlete.get("firstname"), athlete.get("lastname")])).strip()
            or None
        )

        self.connections.upsert_strava_connection(
            user_id=str(user_id),
            provider_user_id=athlete_id,
            access_token=encrypt_secret(str(token_payload["access_token"])),
            refresh_token=encrypt_secret(str(token_payload["refresh_token"])),
            token_expires_at=expires_at,
            scopes=scopes,
            metadata_json={
                "athlete": athlete,
                "token_type": token_payload.get("token_type"),
                "scope": scopes,
            },
        )
        self.db.commit()

        redirect_to = self._build_frontend_callback_redirect(
            state=state,
            connected=True,
            athlete_id=athlete_id,
            scopes=scopes,
            token_expires_at=expires_at,
        )
        return StravaOAuthCallbackResponse(
            connected=True,
            athlete_id=athlete_id,
            athlete_name=athlete_name,
            scopes=scopes,
            token_expires_at=expires_at,
            redirect_to=redirect_to,
        )

    def get_connection_status(self, user_id: str) -> StravaConnectionStatus:
        if self.connections is None:
            raise RuntimeError("Database session required")
        connection = self.connections.get_active_for_user(user_id=user_id, provider="strava")
        if connection is None:
            return StravaConnectionStatus(connected=False)
        athlete = (
            (connection.metadata_json or {}).get("athlete") if connection.metadata_json else None
        )
        athlete_name = None
        if isinstance(athlete, dict):
            athlete_name = (
                " ".join(filter(None, [athlete.get("firstname"), athlete.get("lastname")])).strip()
                or None
            )
        return StravaConnectionStatus(
            connected=True,
            athlete_id=connection.provider_user_id,
            athlete_name=athlete_name,
            scopes=connection.scopes or [],
            token_expires_at=connection.token_expires_at,
            last_sync_at=connection.last_sync_at,
        )

    def enqueue_sync(self, user_id: str, *, full_sync: bool) -> StravaSyncJobResponse:
        if self.db is None or self.connections is None or self.activities is None:
            raise RuntimeError("Database session required")

        connection = self.connections.get_active_for_user(user_id=user_id, provider="strava")
        if connection is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Strava not connected")

        has_existing_activities = self.activities.has_any_for_athlete(
            user_id=user_id,
            athlete_id=connection.provider_user_id,
        )
        effective_full_sync = full_sync or connection.last_sync_at is None or not has_existing_activities

        started_at = datetime.now(UTC)
        try:
            access_token = self._get_valid_access_token(connection)
            activity_payload = self._fetch_activities(
                access_token=access_token,
                connection=connection,
                full_sync=effective_full_sync,
            )
            created, updated = self.activities.upsert_many(
                user_id=user_id,
                athlete_id=connection.provider_user_id,
                activities=activity_payload,
            )

            job_type = "historical_import" if effective_full_sync else "incremental_sync"
            job = SyncJob(
                user_id=user_id,
                provider="strava",
                job_type=job_type,
                status="completed",
                payload_json={
                    "full_sync": effective_full_sync,
                    "requested_at": started_at.isoformat(),
                    "imported_count": created,
                    "updated_count": updated,
                    "activity_count": len(activity_payload),
                },
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )
            self.db.add(job)
            connection.last_sync_at = datetime.now(UTC)
            self.db.add(connection)
            self.db.commit()
            self.db.refresh(job)
            return StravaSyncJobResponse(
                job_id=str(job.id),
                status=job.status,
                job_type=job.job_type,
                imported_count=created,
                updated_count=updated,
            )
        except HTTPException as exc:
            self._record_sync_failure(
                user_id=user_id,
                full_sync=effective_full_sync,
                started_at=started_at,
                error_message=str(exc.detail),
            )
            raise

    def _exchange_code_for_token(self, code: str) -> dict[str, object]:
        if (
            not settings.strava_client_id
            or not settings.strava_client_secret
            or not settings.strava_redirect_uri
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Strava OAuth not configured",
            )

        response = httpx.post(
            "https://www.strava.com/oauth/token",
            data={
                "client_id": settings.strava_client_id,
                "client_secret": settings.strava_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": settings.strava_redirect_uri,
            },
            timeout=20.0,
        )
        if response.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="Strava token exchange failed"
            )
        return response.json()

    def _refresh_access_token(self, connection: OAuthConnection) -> str:
        if not settings.strava_client_id or not settings.strava_client_secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Strava OAuth not configured",
            )

        response = httpx.post(
            "https://www.strava.com/oauth/token",
            data={
                "client_id": settings.strava_client_id,
                "client_secret": settings.strava_client_secret,
                "grant_type": "refresh_token",
                "refresh_token": decrypt_secret(connection.refresh_token),
            },
            timeout=20.0,
        )
        if response.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="Strava token refresh failed"
            )

        payload = response.json()
        connection.access_token = encrypt_secret(str(payload["access_token"]))
        refresh_token = payload.get("refresh_token")
        if refresh_token:
            connection.refresh_token = encrypt_secret(str(refresh_token))
        connection.token_expires_at = datetime.fromtimestamp(int(payload["expires_at"]), tz=UTC)
        metadata_json = dict(connection.metadata_json or {})
        if payload.get("token_type"):
            metadata_json["token_type"] = payload["token_type"]
        if payload.get("scope"):
            metadata_json["scope"] = [
                item.strip() for item in str(payload["scope"]).split(",") if item.strip()
            ]
            connection.scopes = metadata_json["scope"]
        connection.metadata_json = metadata_json
        self.db.add(connection)
        self.db.flush()
        return str(payload["access_token"])

    def _get_valid_access_token(self, connection: OAuthConnection) -> str:
        refresh_before = timedelta(seconds=settings.strava_token_refresh_skew_seconds)
        if connection.token_expires_at <= datetime.now(UTC) + refresh_before:
            return self._refresh_access_token(connection)
        return decrypt_secret(connection.access_token)

    def _fetch_activities(
        self,
        *,
        access_token: str,
        connection: OAuthConnection,
        full_sync: bool,
    ) -> list[dict[str, object]]:
        per_page = min(max(settings.strava_default_activity_limit, 1), 200)
        if full_sync:
            per_page = 200
        after = (
            None
            if full_sync or connection.last_sync_at is None
            else int(connection.last_sync_at.timestamp())
        )

        activities: list[dict[str, object]] = []
        max_pages = (
            settings.strava_full_sync_max_pages
            if full_sync
            else max(settings.strava_full_sync_max_pages, 1)
        )
        for page in range(1, max_pages + 1):
            page_payload = self._fetch_activity_page(
                access_token=access_token,
                page=page,
                per_page=per_page,
                after=after,
            )
            activities.extend(page_payload)
            if len(page_payload) < per_page:
                break
        return activities

    def _fetch_activity_page(
        self,
        *,
        access_token: str,
        page: int,
        per_page: int,
        after: int | None,
    ) -> list[dict[str, object]]:
        params: dict[str, int] = {"page": page, "per_page": per_page}
        if after is not None:
            params["after"] = after

        response = httpx.get(
            "https://www.strava.com/api/v3/athlete/activities",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
            timeout=20.0,
        )
        if response.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="Strava activities fetch failed"
            )
        payload = response.json()
        if not isinstance(payload, list):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unexpected Strava activities payload",
            )
        return payload

    def _record_sync_failure(
        self, *, user_id: str, full_sync: bool, started_at: datetime, error_message: str
    ) -> None:
        if self.db is None:
            return
        job = SyncJob(
            user_id=user_id,
            provider="strava",
            job_type="historical_import" if full_sync else "incremental_sync",
            status="failed",
            error_message=error_message,
            payload_json={"full_sync": full_sync, "requested_at": started_at.isoformat()},
            started_at=started_at,
            finished_at=datetime.now(UTC),
        )
        self.db.add(job)
        self.db.commit()

    def build_frontend_callback_error_redirect(
        self, *, state: str | None = None, error: str = "oauth_callback_failed", message: str
    ) -> str | None:
        return self._build_frontend_callback_redirect(
            state=state,
            connected=False,
            error=error,
            message=message,
        )

    def _build_frontend_callback_redirect(
        self,
        *,
        state: str | None = None,
        connected: bool,
        athlete_id: str | None = None,
        scopes: list[str] | None = None,
        token_expires_at: datetime | None = None,
        error: str | None = None,
        message: str | None = None,
    ) -> str | None:
        if not settings.strava_frontend_redirect_uri:
            return None

        parsed = urlparse(settings.strava_frontend_redirect_uri)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="STRAVA_FRONTEND_REDIRECT_URI is invalid",
            )

        query_params = {
            "provider": "strava",
            "status": "connected" if connected else "error",
            "connected": "true" if connected else "false",
        }
        if state:
            query_params["state"] = state
        if athlete_id:
            query_params["athlete_id"] = athlete_id
        if scopes:
            query_params["scopes"] = ",".join(scopes)
        if token_expires_at is not None:
            query_params["token_expires_at"] = token_expires_at.isoformat()
        if error:
            query_params["error"] = error
        if message:
            query_params["message"] = message

        query = urlencode(query_params)
        return urlunparse(parsed._replace(query=query))
