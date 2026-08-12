"""Human validation endpoints -- the only write path in the IRIS API."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.engine import Engine

from backend.api.dependencies import get_api_config, get_db_engine
from backend.api.errors import message_error
from backend.api.schemas import DecisionRequest
from backend.config import ApiConfig
from backend.services.decision_service import (
    DecisionError,
    create_decision,
    get_decision_history,
    list_decisions,
)

router = APIRouter(prefix="/api", tags=["decisions"])


@router.post("/claims/{claim_sk}/decision", status_code=201)
def submit_claim_decision(
    claim_sk: int,
    body: DecisionRequest,
    engine: Engine = Depends(get_db_engine),
    config: ApiConfig = Depends(get_api_config),
):
    try:
        return create_decision(
            engine,
            config,
            claim_sk=claim_sk,
            decision=body.decision,
            comment=body.comment,
            reviewer_email=body.reviewer_email,
            reviewer_role=body.reviewer_role,
            score_version=body.score_version,
        )
    except DecisionError as exc:
        raise message_error(exc.status_code, str(exc))


@router.get("/claims/{claim_sk}/decisions")
def claim_decision_history(claim_sk: int, engine: Engine = Depends(get_db_engine)):
    return {"claim_sk": claim_sk, "items": get_decision_history(engine, claim_sk)}


@router.get("/decisions")
def decisions_feed(
    reviewer_email: str | None = None,
    limit: str | None = None,
    engine: Engine = Depends(get_db_engine),
):
    items = list_decisions(engine, reviewer_email=reviewer_email, limit=int(limit) if limit else 50)
    return {"items": items}
