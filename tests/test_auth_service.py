import pytest

from backend.app import create_app
from backend.services.auth_service import RoleResolutionError, resolve_role


def test_resolve_role_returns_role_for_known_email():
    result = resolve_role("gestionnaire.test@bnaassurance.com")
    assert result == {"email": "gestionnaire.test@bnaassurance.com", "role": "gestionnaire"}


def test_resolve_role_is_case_and_whitespace_insensitive():
    result = resolve_role("  Manager.Test@BnaAssurance.com  ")
    assert result == {"email": "manager.test@bnaassurance.com", "role": "manager"}


def test_resolve_role_rejects_wrong_domain():
    with pytest.raises(RoleResolutionError):
        resolve_role("gestionnaire.test@example.com")


def test_resolve_role_rejects_unknown_email_on_allowed_domain():
    with pytest.raises(RoleResolutionError):
        resolve_role("inconnu@bnaassurance.com")


def test_resolve_role_rejects_missing_email():
    with pytest.raises(RoleResolutionError):
        resolve_role(None)


def test_resolve_role_route_returns_role_for_known_email():
    app = create_app()
    client = app.test_client()

    response = client.post("/api/auth/resolve-role", json={"email": "admin.test@bnaassurance.com"})

    assert response.status_code == 200
    assert response.get_json() == {"email": "admin.test@bnaassurance.com", "role": "administrateur"}


def test_resolve_role_route_rejects_unknown_email():
    app = create_app()
    client = app.test_client()

    response = client.post("/api/auth/resolve-role", json={"email": "inconnu@bnaassurance.com"})

    assert response.status_code == 403
    assert "message" in response.get_json()


def test_resolve_role_route_handles_missing_body():
    app = create_app()
    client = app.test_client()

    response = client.post("/api/auth/resolve-role")

    assert response.status_code == 403
