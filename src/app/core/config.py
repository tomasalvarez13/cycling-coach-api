from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["local", "staging", "production", "test"] = "local"
    app_name: str = "cycling-coach-api"
    app_debug: bool = False
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/cycling_coach"
    )
    cors_origins: list[str] = Field(default_factory=list)
    jwt_secret: str = Field(default="change-me-in-dev", validation_alias=AliasChoices("JWT_SECRET"))
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 30
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None
    strava_client_id: str | None = None
    strava_client_secret: str | None = None
    strava_redirect_uri: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
