"""Portfolio-level strategic insights for the manager/responsable dashboard."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.engine import Engine

from backend.api.dependencies import get_api_config, get_db_engine
from backend.config import ApiConfig
from backend.services.portfolio_insights_service import get_portfolio_insights

router = APIRouter(prefix="/api", tags=["portfolio"])


@router.get("/portfolio/insights")
def portfolio_insights(
    score_version: str | None = None,
    engine: Engine = Depends(get_db_engine),
    config: ApiConfig = Depends(get_api_config),
):
    return get_portfolio_insights(engine, config, score_version=score_version)
