from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class StravaConnectUrlResponse(BaseModel):
    authorize_url: HttpUrl
    state: str


class StravaConnectionStatus(BaseModel):
    connected: bool
    provider: str = "strava"
    athlete_id: str | None = None
    athlete_name: str | None = None
    scopes: list[str] = Field(default_factory=list)
    token_expires_at: datetime | None = None
    last_sync_at: datetime | None = None


class StravaSyncRequest(BaseModel):
    full_sync: bool = False


class StravaSyncJobResponse(BaseModel):
    job_id: str
    status: str
    provider: str = "strava"
    job_type: str
    imported_count: int = 0
    updated_count: int = 0


class StravaOAuthCallbackResponse(BaseModel):
    connected: bool
    provider: str = "strava"
    athlete_id: str
    athlete_name: str | None = None
    scopes: list[str] = Field(default_factory=list)
    token_expires_at: datetime
    redirect_to: HttpUrl | None = None
