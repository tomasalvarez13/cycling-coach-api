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
from app.models.strava_activity import StravaActivity
from app.models.sync_job import SyncJob
from app.repositories.oauth_connection import OAuthConnectionRepository
from app.repositories.strava_activity import StravaActivityRepository
from app.schemas.strava import (
    StravaActivitiesOverview,
    StravaActivityDetail,
    StravaActivityListResponse,
    StravaActivitySummary,
    StravaConnectionStatus,
    StravaConnectUrlResponse,
    StravaOAuthCallbackResponse,
    StravaRecentVolume,
    StravaSyncJobResponse,
    StravaWebhookEvent,
    StravaWebhookEventResponse,
    StravaWebhookSubscriptionChallengeResponse,
)

settings = get_settings()


class StravaService:
    def __init__(self, db):
        self.db = db
        self.connections = OAuthConnectionRepository(db) if db is not None else None
        self.activities = StravaActivityRepository(db) if db is not None else None

    def verify_webhook_subscription(
        self, *, mode: str, verify_token: str, challenge: str
    ) -> StravaWebhookSubscriptionChallengeResponse:
        if mode != "subscribe":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported Strava webhook mode",
            )
        if not settings.strava_webhook_verify_token:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Strava webhook verify token not configured",
            )
        if verify_token != settings.strava_webhook_verify_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid Strava webhook verify token",
            )
        return StravaWebhookSubscriptionChallengeResponse.model_validate(
            {"hub.challenge": challenge}
        )

    def handle_webhook_event(self, payload: StravaWebhookEvent) -> StravaWebhookEventResponse:
        if self.db is None or self.connections is None or self.activities is None:
            raise RuntimeError("Database session required")

        if payload.object_type != "activity":
            return StravaWebhookEventResponse(
                accepted=False,
                processed=False,
                reason="unsupported_object_type",
            )

        if payload.aspect_type not in {"create", "update"}:
            return StravaWebhookEventResponse(
                accepted=True,
                processed=False,
                reason="ignored_aspect_type",
                provider_activity_id=str(payload.object_id),
            )

        connection = self.connections.get_active_by_provider_user_id(
            provider="strava",
            provider_user_id=str(payload.owner_id),
        )
        if connection is None:
            return StravaWebhookEventResponse(
                accepted=True,
                processed=False,
                reason="connection_not_found",
                provider_activity_id=str(payload.object_id),
            )

        started_at = datetime.now(UTC)
        try:
            access_token = self._get_valid_access_token(connection)
            activity_payload = self._fetch_activity_detail_from_provider(
                access_token=access_token,
                provider_activity_id=str(payload.object_id),
            )
            created, updated = self.activities.upsert_many(
                user_id=str(connection.user_id),
                athlete_id=connection.provider_user_id,
                activities=[activity_payload],
            )
            connection.last_sync_at = datetime.now(UTC)
            self.db.add(connection)
            self.db.add(
                SyncJob(
                    user_id=connection.user_id,
                    provider="strava",
                    job_type="webhook_activity_upsert",
                    status="completed",
                    payload_json={
                        "event": payload.model_dump(),
                        "provider_activity_id": str(payload.object_id),
                        "imported_count": created,
                        "updated_count": updated,
                    },
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                )
            )
            self.db.commit()
            return StravaWebhookEventResponse(
                accepted=True,
                processed=True,
                user_id=str(connection.user_id),
                provider_activity_id=str(payload.object_id),
                imported_count=created,
                updated_count=updated,
            )
        except HTTPException as exc:
            self._record_webhook_failure(
                user_id=str(connection.user_id),
                started_at=started_at,
                payload=payload,
                error_message=str(exc.detail),
            )
            raise

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

        connection = self.connections.upsert_strava_connection(
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

        imported_count = 0
        updated_count = 0
        initial_sync_completed = False
        initial_sync_error = None

        try:
            sync_result = self._run_sync(
                user_id=str(user_id),
                connection=connection,
                full_sync=True,
            )
        except HTTPException as exc:
            initial_sync_error = str(exc.detail)
        else:
            imported_count = sync_result.imported_count
            updated_count = sync_result.updated_count
            initial_sync_completed = True
            connection = self.connections.get_active_for_user(
                user_id=str(user_id), provider="strava"
            ) or connection

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
            last_sync_at=connection.last_sync_at,
            initial_sync_completed=initial_sync_completed,
            initial_sync_error=initial_sync_error,
            imported_count=imported_count,
            updated_count=updated_count,
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

    def list_activities(
        self, user_id: str, *, limit: int, offset: int
    ) -> StravaActivityListResponse:
        repository = self._require_activities_repository()
        items = repository.list_for_user(user_id=user_id, limit=limit, offset=offset)
        total = repository.count_for_user(user_id=user_id)
        return StravaActivityListResponse(
            items=[self._serialize_activity_summary(item) for item in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    def get_activity_detail(
        self, user_id: str, *, provider_activity_id: str
    ) -> StravaActivityDetail:
        repository = self._require_activities_repository()
        activity = repository.get_for_user_by_provider_activity_id(
            user_id=user_id,
            provider_activity_id=provider_activity_id,
        )
        if activity is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
        return self._serialize_activity_detail(activity)

    def get_activities_overview(self, user_id: str) -> StravaActivitiesOverview:
        if self.connections is None:
            raise RuntimeError("Database session required")
        repository = self._require_activities_repository()
        connection = self.connections.get_active_for_user(user_id=user_id, provider="strava")
        if connection is None:
            return StravaActivitiesOverview(connected=False)

        athlete = (
            (connection.metadata_json or {}).get("athlete") if connection.metadata_json else None
        )
        athlete_name = None
        if isinstance(athlete, dict):
            athlete_name = (
                " ".join(filter(None, [athlete.get("firstname"), athlete.get("lastname")])).strip()
                or None
            )

        latest_activities = repository.list_recent_for_user(user_id=user_id, limit=5)
        recent_volume = [
            StravaRecentVolume.model_validate(
                repository.summarize_recent_volume(user_id=user_id, days=7)
            ),
            StravaRecentVolume.model_validate(
                repository.summarize_recent_volume(user_id=user_id, days=30)
            ),
        ]
        return StravaActivitiesOverview(
            connected=True,
            athlete_id=connection.provider_user_id,
            athlete_name=athlete_name,
            last_sync_at=connection.last_sync_at,
            total_activities=repository.count_for_user(user_id=user_id),
            latest_activities=[
                self._serialize_activity_summary(item) for item in latest_activities
            ],
            recent_volume=recent_volume,
        )

    def enqueue_sync(self, user_id: str, *, full_sync: bool) -> StravaSyncJobResponse:
        if self.db is None or self.connections is None or self.activities is None:
            raise RuntimeError("Database session required")

        connection = self.connections.get_active_for_user(user_id=user_id, provider="strava")
        if connection is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Strava not connected")

        return self._run_sync(user_id=user_id, connection=connection, full_sync=full_sync)

    def _run_sync(
        self, *, user_id: str, connection: OAuthConnection, full_sync: bool
    ) -> StravaSyncJobResponse:
        if self.db is None or self.activities is None:
            raise RuntimeError("Database session required")

        has_existing_activities = self.activities.has_any_for_athlete(
            user_id=user_id,
            athlete_id=connection.provider_user_id,
        )
        effective_full_sync = (
            full_sync or connection.last_sync_at is None or not has_existing_activities
        )

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

    def _fetch_activity_detail_from_provider(
        self, *, access_token: str, provider_activity_id: str
    ) -> dict[str, object]:
        response = httpx.get(
            f"https://www.strava.com/api/v3/activities/{provider_activity_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20.0,
        )
        if response.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Strava activity detail fetch failed",
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unexpected Strava activity detail payload",
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

    def _record_webhook_failure(
        self,
        *,
        user_id: str,
        started_at: datetime,
        payload: StravaWebhookEvent,
        error_message: str,
    ) -> None:
        if self.db is None:
            return
        self.db.add(
            SyncJob(
                user_id=user_id,
                provider="strava",
                job_type="webhook_activity_upsert",
                status="failed",
                error_message=error_message,
                payload_json={"event": payload.model_dump(), "requested_at": started_at.isoformat()},
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )
        )
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

    def _require_activities_repository(self) -> StravaActivityRepository:
        if self.activities is None:
            raise RuntimeError("Database session required")
        return self.activities

    def _serialize_activity_summary(self, activity: StravaActivity) -> StravaActivitySummary:
        map_data = _extract_map_data(activity.raw_json)
        return StravaActivitySummary(
            id=str(activity.id),
            provider_activity_id=activity.provider_activity_id,
            athlete_id=activity.athlete_id,
            name=activity.name,
            sport_type=activity.sport_type,
            start_date=activity.start_date,
            timezone=activity.timezone,
            distance_meters=activity.distance_meters,
            moving_time_seconds=activity.moving_time_seconds,
            elapsed_time_seconds=activity.elapsed_time_seconds,
            total_elevation_gain=activity.total_elevation_gain,
            average_speed_mps=activity.average_speed_mps,
            max_speed_mps=activity.max_speed_mps,
            has_map=map_data["has_map"],
            map_summary_polyline=map_data["summary_polyline"],
            start_latlng=map_data["start_latlng"],
            end_latlng=map_data["end_latlng"],
            synced_at=activity.synced_at,
        )

    def _serialize_activity_detail(self, activity: StravaActivity) -> StravaActivityDetail:
        map_data = _extract_map_data(activity.raw_json)
        return StravaActivityDetail(
            **self._serialize_activity_summary(activity).model_dump(),
            map_polyline=map_data["polyline"],
            raw_json=activity.raw_json,
            created_at=activity.created_at,
            updated_at=activity.updated_at,
        )


def _extract_map_data(raw_json: dict[str, object] | None) -> dict[str, object]:
    map_payload = raw_json.get("map") if isinstance(raw_json, dict) else None
    if not isinstance(map_payload, dict):
        return {
            "has_map": False,
            "summary_polyline": None,
            "polyline": None,
            "start_latlng": None,
            "end_latlng": None,
        }

    summary_polyline = _optional_str(map_payload.get("summary_polyline"))
    polyline = _optional_str(map_payload.get("polyline"))
    start_latlng = _optional_latlng(raw_json.get("start_latlng")) if isinstance(raw_json, dict) else None
    end_latlng = _optional_latlng(raw_json.get("end_latlng")) if isinstance(raw_json, dict) else None
    return {
        "has_map": bool(summary_polyline or polyline),
        "summary_polyline": summary_polyline,
        "polyline": polyline,
        "start_latlng": start_latlng,
        "end_latlng": end_latlng,
    }


def _optional_latlng(value: object) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        return [float(value[0]), float(value[1])]
    except (TypeError, ValueError):
        return None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None
