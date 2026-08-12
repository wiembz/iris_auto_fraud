"""Login role-resolution endpoint for the IRIS frontend."""
from __future__ import annotations

from fastapi import APIRouter, Request

from backend.api.errors import message_error
from backend.services.auth_service import RoleResolutionError, resolve_role

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/resolve-role")
async def resolve_role_route(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    try:
        return resolve_role(payload.get("email"))
    except RoleResolutionError as exc:
        raise message_error(403, str(exc))
