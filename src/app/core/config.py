from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, computed_field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["local", "development", "staging", "production", "test"] = "local"
    app_name: str = "cycling-coach-api"
    app_debug: bool = False
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/cycling_coach"
    )
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    jwt_secret: str = Field(default="change-me-in-dev", validation_alias=AliasChoices("JWT_SECRET"))
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 30
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None
    strava_client_id: str | None = None
    strava_client_secret: str | None = None
    strava_redirect_uri: str | None = None
    strava_frontend_redirect_uri: str | None = None
    strava_oauth_state_ttl_minutes: int = 15
    strava_default_activity_limit: int = 30
    strava_full_sync_max_pages: int = 10
    strava_token_refresh_skew_seconds: int = 300
    strava_webhook_verify_token: str | None = None
    strava_webhook_callback_url: str | None = None
    strava_webhook_subscription_id: str | None = None
    token_encryption_secret: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            if raw.startswith("["):
                try:
                    decoded = json.loads(raw)
                except json.JSONDecodeError:
                    pass
                else:
                    if isinstance(decoded, list):
                        return [str(item).strip() for item in decoded if str(item).strip()]
            return [item.strip() for item in raw.split(",") if item.strip()]
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: object) -> object:
        if isinstance(value, str) and value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
