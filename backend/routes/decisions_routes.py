"""Human validation endpoints — the only write path in the IRIS API."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from backend.services.decision_service import (
    DecisionError,
    create_decision,
    get_decision_history,
    list_decisions,
)

decisions_bp = Blueprint("decisions", __name__, url_prefix="/api")


def _engine():
    return current_app.config["IRIS_ENGINE"]


def _config():
    return current_app.config["IRIS_API_CONFIG"]


@decisions_bp.post("/claims/<int:claim_sk>/decision")
def submit_claim_decision(claim_sk: int):
    body = request.get_json(silent=True) or {}
    try:
        result = create_decision(
            _engine(),
            _config(),
            claim_sk=claim_sk,
            decision=body.get("decision"),
            comment=body.get("comment"),
            reviewer_email=body.get("reviewer_email"),
            reviewer_role=body.get("reviewer_role"),
            score_version=body.get("score_version"),
        )
    except DecisionError as exc:
        return jsonify({"message": str(exc)}), exc.status_code
    return jsonify(result), 201


@decisions_bp.get("/claims/<int:claim_sk>/decisions")
def claim_decision_history(claim_sk: int):
    return jsonify({"claim_sk": claim_sk, "items": get_decision_history(_engine(), claim_sk)})


@decisions_bp.get("/decisions")
def decisions_feed():
    reviewer_email = request.args.get("reviewer_email")
    limit = request.args.get("limit")
    items = list_decisions(_engine(), reviewer_email=reviewer_email, limit=int(limit) if limit else 50)
    return jsonify({"items": items})
