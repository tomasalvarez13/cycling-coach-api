from __future__ import annotations

from app.models.athlete import Athlete
from app.repositories.athlete import AthleteRepository
from app.schemas.athlete import AthleteCreate


class AthleteService:
    def __init__(self, repository: AthleteRepository) -> None:
        self.repository = repository

    def get_or_create_placeholder(self, payload: AthleteCreate) -> Athlete:
        existing = self.repository.get_by_email(payload.email)
        if existing is not None:
            return existing

        athlete = Athlete(
            email=payload.email,
            display_name=payload.display_name,
            timezone=payload.timezone,
        )
        return self.repository.create(athlete)
