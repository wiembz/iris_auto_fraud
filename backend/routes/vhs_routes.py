"""Vehicle Health Score endpoints for the IRIS read-only API."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from backend.services.vhs_service import (
    get_vhs_inspection_detail,
    get_vhs_inspection_detail_by_key,
    get_vhs_overview,
    list_vhs_vehicles,
)

vhs_bp = Blueprint("vhs", __name__, url_prefix="/api")


def _engine():
    return current_app.config["IRIS_ENGINE"]


@vhs_bp.get("/vhs/overview")
def vhs_overview():
    return jsonify(get_vhs_overview(_engine()))


@vhs_bp.get("/vhs/vehicles")
def vhs_vehicles():
    limit = request.args.get("limit")
    return jsonify(
        list_vhs_vehicles(
            _engine(),
            decision=request.args.get("decision"),
            search=request.args.get("search"),
            limit=int(limit) if limit else 300,
        )
    )


@vhs_bp.get("/vhs/inspections/<int:vhs_score_sk>")
def vhs_inspection_detail(vhs_score_sk: int):
    result = get_vhs_inspection_detail(_engine(), vhs_score_sk)
    if result is None:
        return jsonify({"message": "Inspection introuvable."}), 404
    return jsonify(result)


@vhs_bp.get("/vhs/inspections/by-key")
def vhs_inspection_detail_by_key():
    """Resolve the latest VHS inspection by immatriculation + date_inspection_sk.

    This endpoint avoids the stale SK problem: the inspection_sk stored in
    fact_post_inspection_attention_signal points to a specific run's row, not
    always to the latest run. Use this endpoint when you have the immatriculation
    and date from the post-inspection signal rather than a reliable vhs_score_sk.
    """
    immatriculation = request.args.get("immatriculation", "").strip()
    date_sk = request.args.get("date_sk", "").strip()
    if not immatriculation or not date_sk:
        return jsonify({"message": "Paramètres 'immatriculation' et 'date_sk' requis."}), 400
    try:
        date_sk_int = int(date_sk)
    except ValueError:
        return jsonify({"message": "'date_sk' doit être un entier (format YYYYMMDD)."}), 400

    result = get_vhs_inspection_detail_by_key(_engine(), immatriculation, date_sk_int)
    if result is None:
        return jsonify({"message": "Aucune inspection VHS trouvée pour cette immatriculation et cette date."}), 404
    return jsonify(result)

