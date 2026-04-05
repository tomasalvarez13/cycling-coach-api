from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.services.auth import AuthService

settings = get_settings()
configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.bootstrap_admin_email and settings.bootstrap_admin_password:
        db: Session = SessionLocal()
        try:
            AuthService(db).register_initial_admin_if_missing(
                email=settings.bootstrap_admin_email,
                password=settings.bootstrap_admin_password,
            )
        finally:
            db.close()
    yield


app = FastAPI(
    title=settings.app_name,
    debug=settings.app_debug,
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

@app.get("/health", tags=["health"])
def root_healthcheck() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
    }


app.include_router(api_router, prefix=settings.api_v1_prefix)
