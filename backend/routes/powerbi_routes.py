"""Governance metadata for the Power BI analytics space (read-only)."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from backend.services.powerbi_governance_service import get_powerbi_governance

powerbi_bp = Blueprint("powerbi", __name__, url_prefix="/api")


@powerbi_bp.get("/powerbi/governance")
def powerbi_governance():
    return jsonify(get_powerbi_governance(current_app.config["IRIS_ENGINE"]))
