from __future__ import annotations

from fastapi import APIRouter

from app.schemas.athlete import AthleteSummary

router = APIRouter(prefix="/athletes", tags=["athletes"])


@router.get("/me", response_model=AthleteSummary)
def get_current_athlete() -> AthleteSummary:
    return AthleteSummary(
        id="00000000-0000-0000-0000-000000000000",
        display_name="placeholder-athlete",
    )
