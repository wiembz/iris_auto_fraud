"""Summary endpoints for the IRIS read-only API."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.engine import Engine

from backend.api.dependencies import get_api_config, get_db_engine
from backend.config import ApiConfig
from backend.services.summary_service import get_summary

router = APIRouter(prefix="/api", tags=["summary"])


@router.get("/health")
def health():
    return {
        "status": "ok",
        "mode": "read-only",
        "message": "IRIS API is available for claim review.",
    }


@router.get("/summary")
def summary(
    score_version: str | None = None,
    engine: Engine = Depends(get_db_engine),
    config: ApiConfig = Depends(get_api_config),
):
    return get_summary(engine, config, score_version=score_version)
