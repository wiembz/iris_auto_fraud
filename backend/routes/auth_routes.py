"""Login role-resolution endpoint for the IRIS frontend."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.services.auth_service import RoleResolutionError, resolve_role


auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_bp.post("/resolve-role")
def resolve_role_route():
    payload = request.get_json(silent=True) or {}
    try:
        result = resolve_role(payload.get("email"))
    except RoleResolutionError as exc:
        return jsonify({"message": str(exc)}), 403
    return jsonify(result)
