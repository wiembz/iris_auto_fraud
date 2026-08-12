"""Claim endpoints for the IRIS read-only API."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.engine import Engine

from backend.api.dependencies import get_api_config, get_db_engine
from backend.api.errors import message_error
from backend.config import ApiConfig
from backend.services.claim_review_service import get_claim_review
from backend.services.claims_service import get_claim, get_vehicle_context, list_claims
from backend.services.signals_service import get_claim_signals, get_ml_anomaly, get_post_inspection
from backend.services.timeline_service import get_timeline

router = APIRouter(prefix="/api", tags=["claims"])


@router.get("/claims")
def claims(
    score_version: str | None = None,
    attention_level: str | None = None,
    confidence_level: str | None = None,
    min_score: str | None = None,
    max_score: str | None = None,
    search: str | None = None,
    has_ml: str | None = None,
    has_post_inspection: str | None = None,
    validation_status: str | None = None,
    page: str | None = None,
    page_size: str | None = None,
    sort_by: str | None = None,
    sort_direction: str | None = None,
    include_total: str | None = None,
    engine: Engine = Depends(get_db_engine),
    config: ApiConfig = Depends(get_api_config),
):
    filters = {
        "score_version": score_version,
        "attention_level": attention_level,
        "confidence_level": confidence_level,
        "min_score": min_score,
        "max_score": max_score,
        "search": search,
        "has_ml": has_ml,
        "has_post_inspection": has_post_inspection,
        "validation_status": validation_status,
        "page": page,
        "page_size": page_size,
        "sort_by": sort_by,
        "sort_direction": sort_direction,
        "include_total": include_total,
    }
    return list_claims(engine, config, filters)


@router.get("/claims/{claim_sk}")
def claim_detail(
    claim_sk: int,
    score_version: str | None = None,
    engine: Engine = Depends(get_db_engine),
    config: ApiConfig = Depends(get_api_config),
):
    result = get_claim(engine, config, claim_sk, score_version=score_version)
    if result is None:
        raise message_error(404, "Dossier introuvable pour la version de score demandee.")
    return result


@router.get("/claims/{claim_sk}/review")
def claim_review(
    claim_sk: int,
    score_version: str | None = None,
    score_run_id: str | None = None,
    ml_signal_run_id: str | None = None,
    post_inspection_signal_run_id: str | None = None,
    engine: Engine = Depends(get_db_engine),
    config: ApiConfig = Depends(get_api_config),
):
    result = get_claim_review(
        engine,
        config,
        claim_sk,
        score_version=score_version,
        score_run_id=score_run_id,
        ml_signal_run_id=ml_signal_run_id,
        post_inspection_signal_run_id=post_inspection_signal_run_id,
    )
    if result is None:
        raise message_error(404, "Revue dossier indisponible pour la version de score demandee.")
    return result


@router.get("/claims/{claim_sk}/signals")
def claim_signals(
    claim_sk: int,
    score_version: str | None = None,
    engine: Engine = Depends(get_db_engine),
    config: ApiConfig = Depends(get_api_config),
):
    return get_claim_signals(engine, config, claim_sk, score_version=score_version)


@router.get("/claims/{claim_sk}/ml-anomaly")
def claim_ml_anomaly(
    claim_sk: int,
    engine: Engine = Depends(get_db_engine),
    config: ApiConfig = Depends(get_api_config),
):
    result = get_ml_anomaly(engine, config, claim_sk)
    if result is None:
        raise message_error(
            404,
            "Aucun indicateur d'atypicite statistique disponible pour ce dossier.",
        )
    return result


@router.get("/claims/{claim_sk}/post-inspection")
def claim_post_inspection(
    claim_sk: int,
    engine: Engine = Depends(get_db_engine),
    config: ApiConfig = Depends(get_api_config),
):
    return get_post_inspection(engine, config, claim_sk)


@router.get("/claims/{claim_sk}/vehicle")
def claim_vehicle(
    claim_sk: int,
    engine: Engine = Depends(get_db_engine),
    config: ApiConfig = Depends(get_api_config),
):
    result = get_vehicle_context(engine, config, claim_sk)
    if result is None:
        raise message_error(404, "Contexte vehicule indisponible pour ce dossier.")
    return result


@router.get("/claims/{claim_sk}/timeline")
def claim_timeline(
    claim_sk: int,
    engine: Engine = Depends(get_db_engine),
    config: ApiConfig = Depends(get_api_config),
):
    return get_timeline(engine, config, claim_sk)
