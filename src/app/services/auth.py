from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.repositories.session import SessionRepository
from app.repositories.user import UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest, SessionResponse, SessionUser


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.users = UserRepository(db)
        self.sessions = SessionRepository(db)

    def _build_session_response(self, user, refresh_token: str, session_created_at) -> SessionResponse:
        access_token, expires_at = create_access_token(user.id, user.role)
        return SessionResponse(
            user=SessionUser(
                id=user.id,
                email=user.email,
                full_name=user.full_name,
                role=user.role,
                timezone=user.timezone,
            ),
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=int((expires_at - session_created_at).total_seconds()) if session_created_at else 1800,
        )

    def register_initial_admin_if_missing(self, *, email: str, password: str, full_name: str = "") -> None:
        existing = self.users.get_by_email(email)
        if existing is not None:
            return
        self.users.create(email=email, password_hash=hash_password(password), full_name=full_name, role="admin")
        self.db.commit()

    def register(self, input_data: RegisterRequest, *, user_agent: str | None = None, ip_address: str | None = None) -> SessionResponse:
        existing = self.users.get_by_email(input_data.email)
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already exists")

        user = self.users.create(
            email=input_data.email,
            password_hash=hash_password(input_data.password),
            full_name=input_data.full_name,
            role="user",
        )
        refresh_token = create_refresh_token()
        session = self.sessions.create(
            user_id=str(user.id),
            refresh_token_hash=hash_refresh_token(refresh_token),
            user_agent=user_agent,
            ip_address=ip_address,
        )
        self.db.commit()
        return self._build_session_response(user, refresh_token, session.created_at)

    def login(self, input_data: LoginRequest, *, user_agent: str | None = None, ip_address: str | None = None) -> SessionResponse:
        user = self.users.get_by_email(input_data.email)
        if user is None or not verify_password(input_data.password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User inactive")

        refresh_token = create_refresh_token()
        refresh_token_hash = hash_refresh_token(refresh_token)
        session = self.sessions.create(
            user_id=str(user.id),
            refresh_token_hash=refresh_token_hash,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        self.db.commit()

        return self._build_session_response(user, refresh_token, session.created_at)

    def refresh(self, refresh_token: str) -> SessionResponse:
        session = self.sessions.get_active_by_refresh_hash(hash_refresh_token(refresh_token))
        if session is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

        user = self.users.get_by_id(str(session.user_id))
        if user is None or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session user")

        return self._build_session_response(user, refresh_token, session.created_at)

    def logout(self, refresh_token: str) -> None:
        session = self.sessions.get_active_by_refresh_hash(hash_refresh_token(refresh_token))
        if session is None:
            return
        self.sessions.revoke(session)
        self.db.commit()

    def get_user_by_id(self, user_id: str):
        user = self.users.get_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return user
