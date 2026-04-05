from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import DBSession, get_current_user
from app.schemas.auth import LoginRequest, LogoutRequest, MeResponse, RefreshRequest, RegisterRequest, SessionResponse
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, db: DBSession) -> SessionResponse:
    service = AuthService(db)
    return service.register(
        payload,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )


@router.post("/login", response_model=SessionResponse, status_code=status.HTTP_200_OK)
def login(payload: LoginRequest, request: Request, db: DBSession) -> SessionResponse:
    service = AuthService(db)
    return service.login(
        payload,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )


@router.post("/refresh", response_model=SessionResponse, status_code=status.HTTP_200_OK)
def refresh(payload: RefreshRequest, db: DBSession) -> SessionResponse:
    return AuthService(db).refresh(payload.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: LogoutRequest, db: DBSession) -> None:
    AuthService(db).logout(payload.refresh_token)
    return None


@router.get("/me", response_model=MeResponse)
def me(current_user=Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        user={
            "id": current_user.id,
            "email": current_user.email,
            "full_name": current_user.full_name,
            "role": current_user.role,
            "timezone": current_user.timezone,
        }
    )
