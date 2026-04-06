from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class StravaConnectUrlResponse(BaseModel):
    authorize_url: HttpUrl
    state: str


class StravaWebhookSubscriptionChallengeResponse(BaseModel):
    hub_challenge: str = Field(alias="hub.challenge")

    model_config = {"populate_by_name": True}


class StravaWebhookEvent(BaseModel):
    aspect_type: str
    event_time: int
    object_id: int
    object_type: str
    owner_id: int
    subscription_id: int
    updates: dict[str, Any] = Field(default_factory=dict)


class StravaWebhookEventResponse(BaseModel):
    accepted: bool
    processed: bool
    reason: str | None = None
    user_id: str | None = None
    provider_activity_id: str | None = None
    imported_count: int = 0
    updated_count: int = 0


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
    last_sync_at: datetime | None = None
    initial_sync_completed: bool = False
    initial_sync_error: str | None = None
    imported_count: int = 0
    updated_count: int = 0
    redirect_to: HttpUrl | None = None


class StravaActivitySummary(BaseModel):
    id: str
    provider_activity_id: str
    athlete_id: str
    name: str
    sport_type: str | None = None
    start_date: datetime
    timezone: str | None = None
    distance_meters: float | None = None
    moving_time_seconds: int | None = None
    elapsed_time_seconds: int | None = None
    total_elevation_gain: float | None = None
    average_speed_mps: float | None = None
    max_speed_mps: float | None = None
    has_map: bool = False
    map_summary_polyline: str | None = None
    start_latlng: list[float] | None = None
    end_latlng: list[float] | None = None
    synced_at: datetime


class StravaActivityDetail(StravaActivitySummary):
    map_polyline: str | None = None
    raw_json: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class StravaActivityListResponse(BaseModel):
    items: list[StravaActivitySummary] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class StravaRecentVolume(BaseModel):
    days: int
    activity_count: int = 0
    distance_meters: float = 0
    moving_time_seconds: int = 0
    elevation_gain: float = 0


class StravaActivitiesOverview(BaseModel):
    connected: bool
    athlete_id: str | None = None
    athlete_name: str | None = None
    last_sync_at: datetime | None = None
    total_activities: int = 0
    latest_activities: list[StravaActivitySummary] = Field(default_factory=list)
    recent_volume: list[StravaRecentVolume] = Field(default_factory=list)
