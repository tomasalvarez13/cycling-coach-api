from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.athlete import Athlete


class AthleteRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_email(self, email: str) -> Athlete | None:
        return self.session.query(Athlete).filter(Athlete.email == email).one_or_none()

    def create(self, athlete: Athlete) -> Athlete:
        self.session.add(athlete)
        self.session.commit()
        self.session.refresh(athlete)
        return athlete
