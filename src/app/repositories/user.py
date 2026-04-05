from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_id(self, user_id: str) -> User | None:
        stmt = select(User).where(User.id == user_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def create(self, *, email: str, password_hash: str, full_name: str = "", role: str = "admin") -> User:
        user = User(email=email, password_hash=password_hash, full_name=full_name, role=role)
        self.db.add(user)
        self.db.flush()
        return user
