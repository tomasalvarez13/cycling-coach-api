from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.oauth_connection import OAuthConnection


class OAuthConnectionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_active_for_user(self, *, user_id: str, provider: str) -> OAuthConnection | None:
        stmt = select(OAuthConnection).where(
            OAuthConnection.user_id == user_id,
            OAuthConnection.provider == provider,
            OAuthConnection.is_active.is_(True),
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_active_by_provider_user_id(
        self, *, provider: str, provider_user_id: str
    ) -> OAuthConnection | None:
        stmt = select(OAuthConnection).where(
            OAuthConnection.provider == provider,
            OAuthConnection.provider_user_id == provider_user_id,
            OAuthConnection.is_active.is_(True),
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def upsert_strava_connection(
        self,
        *,
        user_id: str,
        provider_user_id: str,
        access_token: str,
        refresh_token: str,
        token_expires_at: datetime,
        scopes: list[str],
        metadata_json: dict[str, object],
    ) -> OAuthConnection:
        connection = self.get_active_for_user(user_id=user_id, provider="strava")
        if connection is None:
            connection = OAuthConnection(
                user_id=user_id,
                provider="strava",
                provider_user_id=provider_user_id,
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=token_expires_at,
                scopes=scopes,
                metadata_json=metadata_json,
                is_active=True,
            )
            self.db.add(connection)
        else:
            connection.provider_user_id = provider_user_id
            connection.access_token = access_token
            connection.refresh_token = refresh_token
            connection.token_expires_at = token_expires_at
            connection.scopes = scopes
            connection.metadata_json = metadata_json
            connection.is_active = True
            self.db.add(connection)
        self.db.flush()
        return connection
