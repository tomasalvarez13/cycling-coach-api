from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.deps import DBSession, get_current_user
from app.schemas.strava import StravaConnectUrlResponse, StravaConnectionStatus, StravaSyncJobResponse, StravaSyncRequest
from app.services.strava import StravaService

router = APIRouter(prefix="/strava", tags=["strava"])


@router.get("/connect-url", response_model=StravaConnectUrlResponse)
def connect_url() -> StravaConnectUrlResponse:
    return StravaService(None).build_connect_url()


@router.get("/status", response_model=StravaConnectionStatus)
def status(current_user=Depends(get_current_user), db: DBSession = None) -> StravaConnectionStatus:
    db = db or current_user._sa_instance_state.session
    return StravaService(db).get_connection_status(str(current_user.id))


@router.post("/sync", response_model=StravaSyncJobResponse, status_code=status.HTTP_202_ACCEPTED)
def sync(payload: StravaSyncRequest, current_user=Depends(get_current_user), db: DBSession = None) -> StravaSyncJobResponse:
    db = db or current_user._sa_instance_state.session
    return StravaService(db).enqueue_sync(str(current_user.id), full_sync=payload.full_sync)
