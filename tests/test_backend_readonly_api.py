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
from backend.services.claims_service import _safe_int
from backend.services.serialization import row_to_dict, to_json_value
from etl.utils.business_language import contains_forbidden_business_wording
from backend.services.summary_service import clear_summary_cache, get_summary


BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"


class DummyEngine:
    def __init__(self):
        self.connect_calls = 0

    def connect(self):
        self.connect_calls += 1
        raise AssertionError("summary cache should avoid database access")


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
    assert config.summary_cache_ttl_seconds >= 0


def test_safe_int_bounds_page_size_values():
    assert _safe_int("5000", default=50, min_value=1, max_value=200) == 200
    assert _safe_int("0", default=50, min_value=1, max_value=200) == 1
    assert _safe_int("bad", default=50, min_value=1, max_value=200) == 50


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


def test_claim_list_query_uses_exists_instead_of_signal_joins():
    claims_text = (BACKEND_DIR / "services" / "claims_service.py").read_text(encoding="utf-8").lower()
    list_claims_text = claims_text.split("def get_claim", maxsplit=1)[0]

    assert "exists (" in list_claims_text
    assert "left join mart.fact_claim_ml_anomaly_signal" not in list_claims_text
    assert "left join mart.fact_post_inspection_attention_signal" not in list_claims_text
    assert "group by\n                s.claim_sk" not in list_claims_text


def test_summary_cache_can_serve_without_database_access():
    from backend import config as config_module
    from backend.services import summary_service

    clear_summary_cache()
    cfg = config_module.ApiConfig(summary_cache_ttl_seconds=60)
    payload = {
        "score_version": cfg.default_score_version,
        "score_run_id": "RUN_1",
        "total_claims": 10,
        "attention_distribution": [],
        "confidence_distribution": [],
        "top_claims": [],
        "cache": {"hit": False, "ttl_seconds": 60},
    }
    summary_service._set_cached_summary(cfg.default_score_version, 60, payload)

    result = get_summary(DummyEngine(), cfg)

    assert result["score_run_id"] == "RUN_1"
    assert result["cache"]["hit"] is True


def test_backend_wording_stays_non_accusatory():
    assert not contains_forbidden_business_wording(_backend_text())

def test_declared_mvp_routes_are_present_in_routes_source():
    routes_text = (BACKEND_DIR / "routes" / "claims_routes.py").read_text(encoding="utf-8")
    summary_text = (BACKEND_DIR / "routes" / "summary_routes.py").read_text(encoding="utf-8")

    assert '@claims_bp.get("/claims")' in routes_text
    assert '@claims_bp.get("/claims/<int:claim_sk>")' in routes_text
    assert '@claims_bp.get("/claims/<int:claim_sk>/review")' in routes_text
    assert '@claims_bp.get("/claims/<int:claim_sk>/signals")' in routes_text
    assert '@claims_bp.get("/claims/<int:claim_sk>/ml-anomaly")' in routes_text
    assert '@claims_bp.get("/claims/<int:claim_sk>/post-inspection")' in routes_text
    assert '@claims_bp.get("/claims/<int:claim_sk>/timeline")' in routes_text
    assert '@summary_bp.get("/summary")' in summary_text

def test_backend_claim_review_service_is_available_for_future_frontend():
    routes_text = (BACKEND_DIR / "routes" / "claims_routes.py").read_text(encoding="utf-8")
    service_text = (BACKEND_DIR / "services" / "claim_review_service.py").read_text(encoding="utf-8")

    assert '@claims_bp.get("/claims/<int:claim_sk>/review")' in routes_text
    assert "def get_claim_review(" in service_text


