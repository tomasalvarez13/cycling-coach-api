from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.strava_activity import StravaActivity


class StravaActivityRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def has_any_for_athlete(self, *, user_id: str, athlete_id: str) -> bool:
        stmt = select(StravaActivity.id).where(
            StravaActivity.user_id == user_id,
            StravaActivity.athlete_id == athlete_id,
        )
        return self.db.execute(stmt.limit(1)).scalar_one_or_none() is not None

    def list_for_user(self, *, user_id: str, limit: int, offset: int) -> list[StravaActivity]:
        stmt = (
            select(StravaActivity)
            .where(StravaActivity.user_id == user_id)
            .order_by(StravaActivity.start_date.desc(), StravaActivity.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.execute(stmt).scalars().all())

    def count_for_user(self, *, user_id: str) -> int:
        stmt = (
            select(func.count())
            .select_from(StravaActivity)
            .where(StravaActivity.user_id == user_id)
        )
        return int(self.db.execute(stmt).scalar_one())

    def get_for_user_by_provider_activity_id(
        self, *, user_id: str, provider_activity_id: str
    ) -> StravaActivity | None:
        stmt = select(StravaActivity).where(
            StravaActivity.user_id == user_id,
            StravaActivity.provider_activity_id == provider_activity_id,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_recent_for_user(self, *, user_id: str, limit: int) -> list[StravaActivity]:
        stmt = (
            select(StravaActivity)
            .where(StravaActivity.user_id == user_id)
            .order_by(StravaActivity.start_date.desc(), StravaActivity.created_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def summarize_recent_volume(self, *, user_id: str, days: int) -> dict[str, Any]:
        since = datetime.now(UTC) - timedelta(days=days)
        stmt = select(
            func.count(StravaActivity.id),
            func.coalesce(func.sum(StravaActivity.distance_meters), 0.0),
            func.coalesce(func.sum(StravaActivity.moving_time_seconds), 0),
            func.coalesce(func.sum(StravaActivity.total_elevation_gain), 0.0),
        ).where(
            StravaActivity.user_id == user_id,
            StravaActivity.start_date >= since,
        )
        activity_count, distance_meters, moving_time_seconds, elevation_gain = self.db.execute(
            stmt
        ).one()
        return {
            "days": days,
            "activity_count": int(activity_count or 0),
            "distance_meters": float(distance_meters or 0.0),
            "moving_time_seconds": int(moving_time_seconds or 0),
            "elevation_gain": float(elevation_gain or 0.0),
        }

    def upsert_many(
        self, *, user_id: str, athlete_id: str, activities: list[dict[str, object]]
    ) -> tuple[int, int]:
        created = 0
        updated = 0

        for item in activities:
            provider_activity_id = str(item["id"])
            stmt = select(StravaActivity).where(
                StravaActivity.provider_activity_id == provider_activity_id
            )
            existing = self.db.execute(stmt).scalar_one_or_none()
            if existing is None:
                activity = StravaActivity(
                    user_id=user_id,
                    athlete_id=athlete_id,
                    provider_activity_id=provider_activity_id,
                    name=str(item.get("name") or "Untitled activity"),
                    sport_type=_optional_str(item.get("sport_type") or item.get("type")),
                    start_date=_parse_datetime(item["start_date"]),
                    timezone=_optional_str(item.get("timezone")),
                    distance_meters=_optional_float(item.get("distance")),
                    moving_time_seconds=_optional_int(item.get("moving_time")),
                    elapsed_time_seconds=_optional_int(item.get("elapsed_time")),
                    total_elevation_gain=_optional_float(item.get("total_elevation_gain")),
                    average_speed_mps=_optional_float(item.get("average_speed")),
                    max_speed_mps=_optional_float(item.get("max_speed")),
                    raw_json=item,
                )
                self.db.add(activity)
                created += 1
                continue

            existing.user_id = user_id
            existing.athlete_id = athlete_id
            existing.name = str(item.get("name") or existing.name)
            existing.sport_type = _optional_str(item.get("sport_type") or item.get("type"))
            existing.start_date = _parse_datetime(item["start_date"])
            existing.timezone = _optional_str(item.get("timezone"))
            existing.distance_meters = _optional_float(item.get("distance"))
            existing.moving_time_seconds = _optional_int(item.get("moving_time"))
            existing.elapsed_time_seconds = _optional_int(item.get("elapsed_time"))
            existing.total_elevation_gain = _optional_float(item.get("total_elevation_gain"))
            existing.average_speed_mps = _optional_float(item.get("average_speed"))
            existing.max_speed_mps = _optional_float(item.get("max_speed"))
            existing.raw_json = item
            updated += 1
            self.db.add(existing)

        self.db.flush()
        return created, updated


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError("Invalid datetime value")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)
