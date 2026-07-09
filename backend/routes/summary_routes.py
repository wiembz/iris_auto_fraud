"""Summary endpoints for the IRIS read-only API."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from backend.services.summary_service import get_summary


summary_bp = Blueprint("summary", __name__, url_prefix="/api")


@summary_bp.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "mode": "read-only",
        "message": "IRIS API is available for claim review.",
    })


@summary_bp.get("/summary")
def summary():
    result = get_summary(
        current_app.config["IRIS_ENGINE"],
        current_app.config["IRIS_API_CONFIG"],
        score_version=request.args.get("score_version"),
    )
    return jsonify(result)
