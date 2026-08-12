"""Governance metadata for the Power BI analytics space (read-only)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.engine import Engine

from backend.api.dependencies import get_db_engine
from backend.services.powerbi_governance_service import get_powerbi_governance

router = APIRouter(prefix="/api", tags=["powerbi"])


@router.get("/powerbi/governance")
def powerbi_governance(engine: Engine = Depends(get_db_engine)):
    return get_powerbi_governance(engine)
