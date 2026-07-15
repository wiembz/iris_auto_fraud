"""Portfolio-level strategic insights for the manager/responsable dashboard."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from backend.services.portfolio_insights_service import get_portfolio_insights

portfolio_bp = Blueprint("portfolio", __name__, url_prefix="/api")


@portfolio_bp.get("/portfolio/insights")
def portfolio_insights():
    result = get_portfolio_insights(
        current_app.config["IRIS_ENGINE"],
        current_app.config["IRIS_API_CONFIG"],
        score_version=request.args.get("score_version"),
    )
    return jsonify(result)
