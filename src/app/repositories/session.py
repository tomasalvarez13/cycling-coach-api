from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.core.config import get_settings
from app.models.session import Session

settings = get_settings()


class SessionRepository:
    def __init__(self, db: DBSession):
        self.db = db

    def create(self, *, user_id: str, refresh_token_hash: str, user_agent: str | None, ip_address: str | None) -> Session:
        expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days)
        session = Session(
            user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            user_agent=user_agent,
            ip_address=ip_address,
            expires_at=expires_at,
        )
        self.db.add(session)
        self.db.flush()
        return session

    def get_active_by_refresh_hash(self, refresh_token_hash: str) -> Session | None:
        stmt = select(Session).where(
            Session.refresh_token_hash == refresh_token_hash,
            Session.revoked_at.is_(None),
        )
        session = self.db.execute(stmt).scalar_one_or_none()
        if session is None:
            return None
        if session.expires_at <= datetime.now(UTC):
            return None
        return session

    def revoke(self, session: Session) -> None:
        session.revoked_at = datetime.now(UTC)
        self.db.add(session)
