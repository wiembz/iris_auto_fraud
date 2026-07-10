"""Claim endpoints for the IRIS read-only API."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from backend.services.claim_review_service import get_claim_review
from backend.services.claims_service import get_claim, get_vehicle_context, list_claims
from backend.services.signals_service import get_claim_signals, get_ml_anomaly, get_post_inspection
from backend.services.timeline_service import get_timeline


claims_bp = Blueprint("claims", __name__, url_prefix="/api")


def _engine():
    return current_app.config["IRIS_ENGINE"]


def _config():
    return current_app.config["IRIS_API_CONFIG"]


@claims_bp.get("/claims")
def claims():
    filters = {
        "score_version": request.args.get("score_version"),
        "attention_level": request.args.get("attention_level"),
        "confidence_level": request.args.get("confidence_level"),
        "min_score": request.args.get("min_score"),
        "max_score": request.args.get("max_score"),
        "search": request.args.get("search"),
        "has_ml": request.args.get("has_ml"),
        "has_post_inspection": request.args.get("has_post_inspection"),
        "page": request.args.get("page"),
        "page_size": request.args.get("page_size"),
    }
    return jsonify(list_claims(_engine(), _config(), filters))


@claims_bp.get("/claims/<int:claim_sk>")
def claim_detail(claim_sk: int):
    result = get_claim(
        _engine(),
        _config(),
        claim_sk,
        score_version=request.args.get("score_version"),
    )
    if result is None:
        return jsonify({"message": "Dossier introuvable pour la version de score demandee."}), 404
    return jsonify(result)


@claims_bp.get("/claims/<int:claim_sk>/review")
def claim_review(claim_sk: int):
    result = get_claim_review(
        _engine(),
        _config(),
        claim_sk,
        score_version=request.args.get("score_version"),
        score_run_id=request.args.get("score_run_id"),
        ml_signal_run_id=request.args.get("ml_signal_run_id"),
        post_inspection_signal_run_id=request.args.get("post_inspection_signal_run_id"),
    )
    if result is None:
        return jsonify({"message": "Revue dossier indisponible pour la version de score demandee."}), 404
    return jsonify(result)


@claims_bp.get("/claims/<int:claim_sk>/signals")
def claim_signals(claim_sk: int):
    return jsonify(
        get_claim_signals(
            _engine(),
            _config(),
            claim_sk,
            score_version=request.args.get("score_version"),
        )
    )


@claims_bp.get("/claims/<int:claim_sk>/ml-anomaly")
def claim_ml_anomaly(claim_sk: int):
    result = get_ml_anomaly(_engine(), _config(), claim_sk)
    if result is None:
        return jsonify({
            "claim_sk": claim_sk,
            "message": "Aucun indicateur d'atypicite statistique disponible pour ce dossier.",
        }), 404
    return jsonify(result)


@claims_bp.get("/claims/<int:claim_sk>/post-inspection")
def claim_post_inspection(claim_sk: int):
    return jsonify(get_post_inspection(_engine(), _config(), claim_sk))


@claims_bp.get("/claims/<int:claim_sk>/vehicle")
def claim_vehicle(claim_sk: int):
    result = get_vehicle_context(_engine(), _config(), claim_sk)
    if result is None:
        return jsonify({"message": "Contexte vehicule indisponible pour ce dossier."}), 404
    return jsonify(result)


@claims_bp.get("/claims/<int:claim_sk>/timeline")
def claim_timeline(claim_sk: int):
    return jsonify(get_timeline(_engine(), _config(), claim_sk))
