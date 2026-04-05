from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

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
    class FakeConnections:
        def get_active_for_user(self, *, user_id: str, provider: str):
            assert user_id == "user-abc"
            assert provider == "strava"
            return None

    service = StravaService(db=object())
    service.connections = FakeConnections()

    response = service.get_connection_status("user-abc")

    assert response.connected is False


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

