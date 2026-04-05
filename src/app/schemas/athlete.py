from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, EmailStr

from app.schemas.common import APIModel, TimestampedModel


class AthleteCreate(BaseModel):
    email: EmailStr
    display_name: str
    timezone: str = "UTC"


class AthleteRead(TimestampedModel):
    email: EmailStr
    display_name: str
    timezone: str
    strava_athlete_id: int | None = None


class AthleteSummary(APIModel):
    id: UUID
    display_name: str
