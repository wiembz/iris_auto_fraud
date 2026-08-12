"""Contract tests for the FastAPI migration: same endpoints, same JSON shapes,
same status codes, same `{"message": "..."}` business-error format as the
Flask API it replaces. See docs/architecture/MIGRATION_FASTAPI_PLAN.md.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_health_returns_200():
    response = _client().get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_resolve_role_returns_same_json_shape_as_before():
    response = _client().post("/api/auth/resolve-role", json={"email": "admin.test@bnaassurance.com"})
    assert response.status_code == 200
    assert response.json() == {"email": "admin.test@bnaassurance.com", "role": "administrateur"}


def test_auth_error_uses_message_format_not_fastapi_default_detail():
    response = _client().post("/api/auth/resolve-role", json={"email": "inconnu@bnaassurance.com"})
    body = response.json()
    assert response.status_code == 403
    assert "message" in body
    assert "detail" not in body


def test_all_declared_endpoints_exist():
    paths = set(create_app().openapi()["paths"].keys())
    expected = {
        "/api/health",
        "/api/summary",
        "/api/auth/resolve-role",
        "/api/claims",
        "/api/claims/{claim_sk}",
        "/api/claims/{claim_sk}/review",
        "/api/claims/{claim_sk}/signals",
        "/api/claims/{claim_sk}/ml-anomaly",
        "/api/claims/{claim_sk}/post-inspection",
        "/api/claims/{claim_sk}/vehicle",
        "/api/claims/{claim_sk}/timeline",
        "/api/claims/{claim_sk}/decision",
        "/api/claims/{claim_sk}/decisions",
        "/api/decisions",
        "/api/portfolio/insights",
        "/api/powerbi/governance",
        "/api/vhs/overview",
        "/api/vhs/vehicles",
        "/api/vhs/inspection-images/{asset_id}/content",
        "/api/vhs/inspections/by-key",
        "/api/vhs/inspections/{vhs_score_sk}",
        "/api/claims/{claim_sk}/workflow",
        "/api/claims/{claim_sk}/workflow/history",
        "/api/claims/{claim_sk}/workflow/status",
        "/api/claims/{claim_sk}/workflow/assignment",
        "/api/claims/{claim_sk}/workflow/tasks",
        "/api/claims/{claim_sk}/workflow/tasks/{task_ref_id}/complete",
        "/api/workflow/tasks",
    }
    assert expected.issubset(paths)


def test_unknown_endpoint_returns_404():
    response = _client().get("/api/does-not-exist")
    assert response.status_code == 404


def test_openapi_docs_available():
    client = _client()
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_decision_empty_json_body_returns_business_error_not_422():
    # Every field is optional (permissive, like the old Flask `body.get(...)`) --
    # decision_service itself raises the business error on invalid content.
    response = _client().post("/api/claims/1/decision", json={})
    assert response.status_code != 422
    assert "message" in response.json()


def test_workflow_status_empty_json_body_returns_business_error_not_422():
    response = _client().post("/api/claims/1/workflow/status", json={})
    assert response.status_code != 422
    assert "message" in response.json()


def test_post_with_no_body_at_all_does_not_return_422():
    # Distinct from the two tests above: no Content-Type, zero bytes, not
    # even `{}` -- matches Flask's request.get_json(silent=True) or {},
    # which never 422'd on a missing body. Every write endpoint's Pydantic
    # body model must carry a default instance for this to hold.
    client = _client()
    for path in (
        "/api/claims/1/decision",
        "/api/claims/1/workflow/status",
        "/api/claims/1/workflow/assignment",
        "/api/claims/1/workflow/tasks",
    ):
        response = client.post(path)
        assert response.status_code != 422, path
        assert "message" in response.json(), path
