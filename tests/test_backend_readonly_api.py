from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import re

from backend.config import (
    DEFAULT_ML_SIGNAL_VERSION,
    DEFAULT_POST_INSPECTION_SIGNAL_VERSION,
    DEFAULT_SCORE_VERSION,
    load_config,
)
from backend.services.serialization import row_to_dict, to_json_value


BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"


def _backend_text() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in BACKEND_DIR.rglob("*.py")
    ).lower()



def _service_text() -> str:
    services_dir = BACKEND_DIR / "services"
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in services_dir.rglob("*.py")
    ).lower()
def test_api_config_defaults_target_candidate_read_only_outputs():
    config = load_config()

    assert config.default_score_version == DEFAULT_SCORE_VERSION
    assert config.ml_signal_version == DEFAULT_ML_SIGNAL_VERSION
    assert config.post_inspection_signal_version == DEFAULT_POST_INSPECTION_SIGNAL_VERSION
    assert config.max_page_size >= 50


def test_serialization_converts_common_database_values():
    assert to_json_value(date(2026, 7, 9)) == "2026-07-09"
    assert to_json_value(datetime(2026, 7, 9, 8, 30, 0)) == "2026-07-09T08:30:00"
    assert to_json_value(Decimal("12.50")) == 12.5

    row = {"claim_sk": 1, "claim_date": date(2026, 7, 9), "amount": Decimal("99.90")}
    assert row_to_dict(row) == {"claim_sk": 1, "claim_date": "2026-07-09", "amount": 99.9}


def test_backend_service_sql_stays_read_only():
    text = _service_text()

    forbidden_patterns = [
        r"(?<!path\.)\binsert\b",
        r"\bupdate\b",
        r"\bdelete\b",
        r"\bdrop\b",
        r"\btruncate\b",
        r"\balter\b",
        r"\bcreate\s+table\b",
        r"\bto_sql\b",
    ]
    for pattern in forbidden_patterns:
        assert re.search(pattern, text) is None


def test_backend_wording_stays_non_accusatory():
    text = _backend_text()

    forbidden_terms = [
        "fraude detectee",
        "fraude détectée",
        "preuve de fraude",
        "client fraudeur",
        "suspect confirme",
        "suspect confirmé",
        "probabilite de fraude",
        "probabilité de fraude",
    ]
    for term in forbidden_terms:
        assert term not in text


def test_declared_mvp_routes_are_present_in_routes_source():
    routes_text = (BACKEND_DIR / "routes" / "claims_routes.py").read_text(encoding="utf-8")
    summary_text = (BACKEND_DIR / "routes" / "summary_routes.py").read_text(encoding="utf-8")

    assert '@claims_bp.get("/claims")' in routes_text
    assert '@claims_bp.get("/claims/<int:claim_sk>")' in routes_text
    assert '@claims_bp.get("/claims/<int:claim_sk>/signals")' in routes_text
    assert '@claims_bp.get("/claims/<int:claim_sk>/ml-anomaly")' in routes_text
    assert '@claims_bp.get("/claims/<int:claim_sk>/post-inspection")' in routes_text
    assert '@claims_bp.get("/claims/<int:claim_sk>/timeline")' in routes_text
    assert '@summary_bp.get("/summary")' in summary_text




