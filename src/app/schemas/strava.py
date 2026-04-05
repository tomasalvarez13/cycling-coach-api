from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, HttpUrl


class StravaConnectUrlResponse(BaseModel):
    authorize_url: HttpUrl
    state: str


class StravaConnectionStatus(BaseModel):
    connected: bool
    provider: str = "strava"
    athlete_id: str | None = None
    scopes: list[str] = []
    last_sync_at: datetime | None = None


class StravaSyncRequest(BaseModel):
    full_sync: bool = False


class StravaSyncJobResponse(BaseModel):
    job_id: str
    status: str
    provider: str = "strava"
    job_type: str
