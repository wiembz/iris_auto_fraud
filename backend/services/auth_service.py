"""Email-to-role directory lookup for IRIS login.

This does not authenticate credentials (no password) -- it only resolves
which role an already domain-verified email is allowed to use, so the role
is decided server-side and can no longer be self-selected in the frontend.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent.parent
USER_DIRECTORY_PATH = BASE_DIR / "config" / "auth" / "user_directory.json"

ALLOWED_ROLES = {"analyste", "responsable", "administrateur"}
ALLOWED_EMAIL_DOMAIN = "@bnaassurance.com"


class RoleResolutionError(ValueError):
    """Raised with a user-facing reason when an email cannot be resolved to a role."""


def _load_directory() -> dict[str, str]:
    with open(USER_DIRECTORY_PATH, encoding="utf-8") as handle:
        data = json.load(handle)
    return {
        str(email).strip().lower(): str(role).strip().lower()
        for email, role in data.get("users", {}).items()
    }


def resolve_role(email: str | None) -> dict[str, Any]:
    """Return {"email": ..., "role": ...} for a known, authorized email.

    Raises RoleResolutionError with a message safe to show to the user
    otherwise (unknown domain, email not registered, or misconfigured role).
    """
    normalized = (email or "").strip().lower()
    if not normalized.endswith(ALLOWED_EMAIL_DOMAIN) or normalized == ALLOWED_EMAIL_DOMAIN:
        raise RoleResolutionError("Adresse email non autorisee : domaine BNA Assurance requis.")

    role = _load_directory().get(normalized)
    if role is None:
        raise RoleResolutionError(
            "Cette adresse email n'est pas enregistree dans IRIS. Contactez un administrateur."
        )
    if role not in ALLOWED_ROLES:
        raise RoleResolutionError("Role invalide configure pour cet utilisateur. Contactez un administrateur.")

    return {"email": normalized, "role": role}
