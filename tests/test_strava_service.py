from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services import strava as strava_module
from app.services.strava import StravaService


class DummyDB:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.flushes = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commits += 1

    def flush(self) -> None:
        self.flushes += 1

    def refresh(self, _: object) -> None:
        return None


class FakeConnections:
    def __init__(self, connection) -> None:
        self.connection = connection

    def get_active_for_user(self, *, user_id: str, provider: str):
        assert user_id == "user-abc"
        assert provider == "strava"
        return self.connection


class FakeActivities:
    def __init__(
        self,
        *,
        has_any: bool = False,
        upsert_result: tuple[int, int] = (0, 0),
        listed: list[object] | None = None,
        total: int = 0,
        detail: object | None = None,
        recent: list[object] | None = None,
        summary_by_days: dict[int, dict[str, object]] | None = None,
    ) -> None:
        self.has_any = has_any
        self.upsert_result = upsert_result
        self.listed = listed or []
        self.total = total
        self.detail = detail
        self.recent = recent or []
        self.summary_by_days = summary_by_days or {}
        self.has_any_calls: list[tuple[str, str]] = []
        self.upsert_calls: list[tuple[str, str, list[dict[str, object]]]] = []
        self.list_calls: list[tuple[str, int, int]] = []
        self.detail_calls: list[tuple[str, str]] = []
        self.recent_calls: list[tuple[str, int]] = []
        self.summary_calls: list[tuple[str, int]] = []

    def has_any_for_athlete(self, *, user_id: str, athlete_id: str) -> bool:
        self.has_any_calls.append((user_id, athlete_id))
        return self.has_any

    def upsert_many(self, *, user_id: str, athlete_id: str, activities: list[dict[str, object]]):
        self.upsert_calls.append((user_id, athlete_id, activities))
        return self.upsert_result

    def list_for_user(self, *, user_id: str, limit: int, offset: int):
        self.list_calls.append((user_id, limit, offset))
        return self.listed

    def count_for_user(self, *, user_id: str) -> int:
        assert user_id == "user-abc"
        return self.total

    def get_for_user_by_provider_activity_id(self, *, user_id: str, provider_activity_id: str):
        self.detail_calls.append((user_id, provider_activity_id))
        return self.detail

    def list_recent_for_user(self, *, user_id: str, limit: int):
        self.recent_calls.append((user_id, limit))
        return self.recent

    def summarize_recent_volume(self, *, user_id: str, days: int):
        self.summary_calls.append((user_id, days))
        return self.summary_by_days[days]


def _make_activity(*, provider_activity_id: str, name: str = "Morning Ride"):
    return SimpleNamespace(
        id=uuid4(),
        provider_activity_id=provider_activity_id,
        athlete_id="athlete-1",
        name=name,
        sport_type="Ride",
        start_date=datetime(2026, 4, 5, 7, 0, tzinfo=UTC),
        timezone="(GMT+00:00) UTC",
        distance_meters=42000.0,
        moving_time_seconds=5400,
        elapsed_time_seconds=5700,
        total_elevation_gain=680.0,
        average_speed_mps=7.8,
        max_speed_mps=15.2,
        synced_at=datetime(2026, 4, 5, 9, 0, tzinfo=UTC),
        raw_json={"id": int(provider_activity_id), "name": name},
        created_at=datetime(2026, 4, 5, 9, 0, tzinfo=UTC),
        updated_at=datetime(2026, 4, 5, 9, 5, tzinfo=UTC),
    )


def test_build_connect_url_includes_signed_state(monkeypatch) -> None:
    monkeypatch.setattr(strava_module.settings, "strava_client_id", "12345")
    monkeypatch.setattr(
        strava_module.settings,
        "strava_redirect_uri",
        "http://localhost:8000/api/v1/strava/callback",
    )

    response = StravaService(None).build_connect_url(user_id="user-abc")

    assert "client_id=12345" in str(response.authorize_url)
    assert response.state


def test_get_connection_status_without_connection() -> None:
    class FakeConnectionsWithoutConnection:
        def get_active_for_user(self, *, user_id: str, provider: str):
            assert user_id == "user-abc"
            assert provider == "strava"
            return None

    service = StravaService(db=object())
    service.connections = FakeConnectionsWithoutConnection()

    response = service.get_connection_status("user-abc")

    assert response.connected is False


def test_list_activities_returns_paginated_real_data() -> None:
    service = StravaService(db=DummyDB())
    first = _make_activity(provider_activity_id="101")
    second = _make_activity(provider_activity_id="102", name="Evening Ride")
    service.activities = FakeActivities(listed=[first, second], total=7)

    response = service.list_activities("user-abc", limit=2, offset=4)

    assert response.total == 7
    assert response.limit == 2
    assert response.offset == 4
    assert [item.provider_activity_id for item in response.items] == ["101", "102"]


def test_get_activity_detail_returns_raw_payload() -> None:
    service = StravaService(db=DummyDB())
    activity = _make_activity(provider_activity_id="555")
    service.activities = FakeActivities(detail=activity)

    response = service.get_activity_detail("user-abc", provider_activity_id="555")

    assert response.provider_activity_id == "555"
    assert response.raw_json == {"id": 555, "name": "Morning Ride"}


def test_get_activity_detail_raises_404_when_missing() -> None:
    service = StravaService(db=DummyDB())
    service.activities = FakeActivities(detail=None)

    with pytest.raises(HTTPException) as exc_info:
        service.get_activity_detail("user-abc", provider_activity_id="999")

    assert exc_info.value.status_code == 404


def test_get_activities_overview_returns_minimum_useful_summary() -> None:
    db = DummyDB()
    service = StravaService(db=db)
    connection = SimpleNamespace(
        provider_user_id="athlete-1",
        last_sync_at=datetime(2026, 4, 5, 12, 0, tzinfo=UTC),
        metadata_json={"athlete": {"firstname": "Tom", "lastname": "Alvarez"}},
    )
    service.connections = FakeConnections(connection)
    latest = [
        _make_activity(provider_activity_id="701"),
        _make_activity(provider_activity_id="702"),
    ]
    service.activities = FakeActivities(
        total=12,
        recent=latest,
        summary_by_days={
            7: {
                "days": 7,
                "activity_count": 3,
                "distance_meters": 120000.0,
                "moving_time_seconds": 14400,
                "elevation_gain": 1800.0,
            },
            30: {
                "days": 30,
                "activity_count": 12,
                "distance_meters": 480000.0,
                "moving_time_seconds": 57600,
                "elevation_gain": 7200.0,
            },
        },
    )

    response = service.get_activities_overview("user-abc")

    assert response.connected is True
    assert response.athlete_name == "Tom Alvarez"
    assert response.total_activities == 12
    assert [item.provider_activity_id for item in response.latest_activities] == ["701", "702"]
    assert [
        (item.days, item.activity_count) for item in response.recent_volume
    ] == [(7, 3), (30, 12)]


def test_get_activities_overview_without_connection_returns_disconnected() -> None:
    service = StravaService(db=DummyDB())
    service.connections = FakeConnections(None)
    service.activities = FakeActivities()

    response = service.get_activities_overview("user-abc")

    assert response.connected is False
    assert response.total_activities == 0
    assert response.latest_activities == []


def test_refresh_access_token_keeps_existing_refresh_token_when_provider_omits_rotation(
    monkeypatch,
) -> None:
    db = DummyDB()
    service = StravaService(db=db)
    monkeypatch.setattr(strava_module.settings, "strava_client_id", "client-id")
    monkeypatch.setattr(strava_module.settings, "strava_client_secret", "client-secret")

    existing_refresh_token = strava_module.encrypt_secret("refresh-1")
    connection = SimpleNamespace(
        refresh_token=existing_refresh_token,
        access_token=strava_module.encrypt_secret("old-access"),
        token_expires_at=datetime.now(UTC),
        metadata_json={"token_type": "Bearer"},
        scopes=["read"],
    )

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {
                "access_token": "new-access",
                "expires_at": int((datetime.now(UTC) + timedelta(hours=6)).timestamp()),
                "token_type": "Bearer",
                "scope": "read,activity:read_all",
            }

    monkeypatch.setattr(strava_module.httpx, "post", lambda *args, **kwargs: FakeResponse())

    access_token = service._refresh_access_token(connection)

    assert access_token == "new-access"  # noqa: S105
    assert strava_module.decrypt_secret(connection.refresh_token) == "refresh-1"
    assert connection.scopes == ["read", "activity:read_all"]
    assert db.flushes == 1


def test_get_valid_access_token_refreshes_before_expiry_skew(monkeypatch) -> None:
    service = StravaService(db=DummyDB())
    monkeypatch.setattr(strava_module.settings, "strava_token_refresh_skew_seconds", 300)
    connection = SimpleNamespace(
        token_expires_at=datetime.now(UTC) + timedelta(seconds=120),
        access_token=strava_module.encrypt_secret("still-cached"),
    )
    monkeypatch.setattr(service, "_refresh_access_token", lambda _: "refreshed-token")

    access_token = service._get_valid_access_token(connection)

    assert access_token == "refreshed-token"  # noqa: S105


def test_fetch_activities_uses_incremental_after_and_stops_on_short_page(monkeypatch) -> None:
    service = StravaService(db=DummyDB())
    monkeypatch.setattr(strava_module.settings, "strava_default_activity_limit", 2)
    monkeypatch.setattr(strava_module.settings, "strava_full_sync_max_pages", 5)
    connection = SimpleNamespace(last_sync_at=datetime(2026, 4, 5, 12, 0, tzinfo=UTC))
    calls: list[tuple[int, int, int | None]] = []

    def fake_fetch_page(*, access_token: str, page: int, per_page: int, after: int | None):
        assert access_token == "access-1"  # noqa: S105
        calls.append((page, per_page, after))
        if page == 1:
            return [{"id": 1}, {"id": 2}]
        return [{"id": 3}]

    monkeypatch.setattr(service, "_fetch_activity_page", fake_fetch_page)

    payload = service._fetch_activities(
        access_token="access-1",  # noqa: S106
        connection=connection,
        full_sync=False,
    )

    assert [item["id"] for item in payload] == [1, 2, 3]
    assert calls == [
        (1, 2, int(connection.last_sync_at.timestamp())),
        (2, 2, int(connection.last_sync_at.timestamp())),
    ]


def test_enqueue_sync_promotes_first_sync_to_historical(monkeypatch) -> None:
    db = DummyDB()
    service = StravaService(db=db)
    connection = SimpleNamespace(
        provider_user_id="athlete-1",
        last_sync_at=None,
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        access_token=strava_module.encrypt_secret("access-1"),
    )
    service.connections = FakeConnections(connection)
    service.activities = FakeActivities(has_any=True, upsert_result=(2, 0))

    captured: list[bool] = []

    def fake_fetch_activities(*, access_token: str, connection, full_sync: bool):
        assert access_token == "access-1"  # noqa: S105
        assert connection.provider_user_id == "athlete-1"
        captured.append(full_sync)
        return [{"id": 1}, {"id": 2}]

    monkeypatch.setattr(service, "_fetch_activities", fake_fetch_activities)

    response = service.enqueue_sync("user-abc", full_sync=False)

    assert captured == [True]
    assert response.job_type == "historical_import"
    assert response.imported_count == 2
    assert connection.last_sync_at is not None


def test_enqueue_sync_promotes_empty_local_dataset_to_historical(monkeypatch) -> None:
    db = DummyDB()
    service = StravaService(db=db)
    connection = SimpleNamespace(
        provider_user_id="athlete-1",
        last_sync_at=datetime(2026, 4, 5, 12, 0, tzinfo=UTC),
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        access_token=strava_module.encrypt_secret("access-1"),
    )
    service.connections = FakeConnections(connection)
    service.activities = FakeActivities(has_any=False, upsert_result=(1, 0))

    captured: list[bool] = []

    def fake_fetch_activities(*, access_token: str, connection, full_sync: bool):
        assert access_token == "access-1"  # noqa: S105
        captured.append(full_sync)
        return [{"id": 10}]

    monkeypatch.setattr(service, "_fetch_activities", fake_fetch_activities)

    response = service.enqueue_sync("user-abc", full_sync=False)

    assert captured == [True]
    assert response.job_type == "historical_import"
    assert response.imported_count == 1


def test_enqueue_sync_keeps_incremental_when_history_exists(monkeypatch) -> None:
    db = DummyDB()
    service = StravaService(db=db)
    connection = SimpleNamespace(
        provider_user_id="athlete-1",
        last_sync_at=datetime(2026, 4, 5, 12, 0, tzinfo=UTC),
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        access_token=strava_module.encrypt_secret("access-1"),
    )
    service.connections = FakeConnections(connection)
    service.activities = FakeActivities(has_any=True, upsert_result=(0, 1))

    captured: list[bool] = []

    def fake_fetch_activities(*, access_token: str, connection, full_sync: bool):
        assert access_token == "access-1"  # noqa: S105
        captured.append(full_sync)
        return [{"id": 20}]

    monkeypatch.setattr(service, "_fetch_activities", fake_fetch_activities)

    response = service.enqueue_sync("user-abc", full_sync=False)

    assert captured == [False]
    assert response.job_type == "incremental_sync"
    assert response.updated_count == 1


def test_build_frontend_callback_redirect_includes_status_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        strava_module.settings,
        "strava_frontend_redirect_uri",
        "http://localhost:3000/integrations/strava/callback",
    )
    redirect_to = StravaService(None)._build_frontend_callback_redirect(
        state="signed-state-1",
        connected=True,
        athlete_id="999",
        scopes=["read", "activity:read_all"],
        token_expires_at=datetime(2026, 4, 5, 15, 0, tzinfo=UTC),
    )

    assert redirect_to is not None
    assert "status=connected" in redirect_to
    assert "athlete_id=999" in redirect_to
    assert "provider=strava" in redirect_to
    assert "state=signed-state-1" in redirect_to


def test_build_frontend_callback_redirect_rejects_invalid_uri(monkeypatch) -> None:
    monkeypatch.setattr(
        strava_module.settings, "strava_frontend_redirect_uri", "javascript:alert(1)"
    )

    with pytest.raises(HTTPException) as exc_info:
        StravaService(None)._build_frontend_callback_redirect(
            connected=True,
            athlete_id="999",
            scopes=["read"],
            token_expires_at=datetime(2026, 4, 5, 15, 0, tzinfo=UTC),
        )

    assert exc_info.value.status_code == 500


def test_build_frontend_callback_error_redirect_includes_error_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        strava_module.settings,
        "strava_frontend_redirect_uri",
        "https://cycling-coach-web.vercel.app/integrations/strava/callback",
    )

    redirect_to = StravaService(None).build_frontend_callback_error_redirect(
        state="signed-state-2",
        error="oauth_callback_failed",
        message="Strava token exchange failed",
    )

    assert redirect_to is not None
    assert "status=error" in redirect_to
    assert "connected=false" in redirect_to
    assert "error=oauth_callback_failed" in redirect_to
    assert "message=Strava+token+exchange+failed" in redirect_to
    assert "state=signed-state-2" in redirect_to
