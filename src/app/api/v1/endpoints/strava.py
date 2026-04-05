from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse

from app.api.deps import DBSession, get_current_user
from app.schemas.strava import (
    StravaConnectionStatus,
    StravaConnectUrlResponse,
    StravaOAuthCallbackResponse,
    StravaSyncJobResponse,
    StravaSyncRequest,
)
from app.services.strava import StravaService

router = APIRouter(prefix="/strava", tags=["strava"])


@router.get("/connect-url", response_model=StravaConnectUrlResponse)
def connect_url(current_user: Any = Depends(get_current_user)) -> StravaConnectUrlResponse:
    return StravaService(None).build_connect_url(user_id=str(current_user.id))


@router.get("/callback", response_model=StravaOAuthCallbackResponse)
def oauth_callback(
    request: Request,
    db: DBSession,
    code: str = Query(..., min_length=1),
    state: str = Query(..., min_length=1),
    scope: str | None = Query(default=None),
) -> StravaOAuthCallbackResponse | RedirectResponse:
    service = StravaService(db)
    accepts_json = "application/json" in request.headers.get("accept", "")

    try:
        response = service.handle_callback(code=code, state=state, scope=scope)
    except HTTPException as exc:
        redirect_to = None
        if not accepts_json:
            redirect_to = service.build_frontend_callback_error_redirect(
                state=state,
                error="oauth_callback_failed",
                message=str(exc.detail),
            )
        if redirect_to:
            return RedirectResponse(url=redirect_to, status_code=status.HTTP_302_FOUND)
        raise

    if response.redirect_to and not accepts_json:
        return RedirectResponse(url=str(response.redirect_to), status_code=status.HTTP_302_FOUND)
    return response


@router.get("/status", response_model=StravaConnectionStatus)
def get_status(
    db: DBSession, current_user: Any = Depends(get_current_user)
) -> StravaConnectionStatus:
    return StravaService(db).get_connection_status(str(current_user.id))


@router.post("/sync", response_model=StravaSyncJobResponse, status_code=status.HTTP_202_ACCEPTED)
def sync(
    payload: StravaSyncRequest, db: DBSession, current_user: Any = Depends(get_current_user)
) -> StravaSyncJobResponse:
    return StravaService(db).enqueue_sync(str(current_user.id), full_sync=payload.full_sync)
