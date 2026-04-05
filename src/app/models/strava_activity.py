from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StravaActivity(Base):
    __tablename__ = "strava_activities"
    __table_args__ = (UniqueConstraint("provider_activity_id", name="uq_strava_activities_provider_activity_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), index=True)
    provider_activity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    athlete_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sport_type: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    timezone: Mapped[str | None] = mapped_column(String(128), nullable=True)
    distance_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    moving_time_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    elapsed_time_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_elevation_gain: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_json: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
