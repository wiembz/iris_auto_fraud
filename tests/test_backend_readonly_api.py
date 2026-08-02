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


def _strip_comment_lines(source: str) -> str:
    """Drop whole-line '#' comments before scanning for forbidden SQL keywords --
    a comment explaining *why* some other layer once ran ALTER/DROP is documentation,
    not executable code, and shouldn't trip a read-only guard on this service."""
    return "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )


def _service_text(exclude: tuple[str, ...] = ()) -> str:
    services_dir = BACKEND_DIR / "services"
    return "\n".join(
        _strip_comment_lines(path.read_text(encoding="utf-8"))
        for path in services_dir.rglob("*.py")
        if path.name not in exclude
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
    # decision_service.py and workflow_service.py are the deliberate write
    # paths (schema `app`, append-only, DB triggers block UPDATE/DELETE).
    # inspection_image_service.py is a third: it owns app.inspection_image_asset
    # (idempotent CREATE TABLE IF NOT EXISTS, same pattern every ETL mart
    # script already uses for its own tables). All three are excluded here
    # and, where warranted, checked precisely instead of weakening this
    # guarantee for every other service.
    text = _service_text(exclude=("decision_service.py", "workflow_service.py", "inspection_image_service.py"))

    forbidden_patterns = [
        r"(?<!path\.)\binsert\b",
        r"(?<!\.)\bupdate\b",  # allow dict.update(...); SQL UPDATE is never preceded by a dot
        r"\bdelete\b",
        r"\bdrop\b",
        r"\btruncate\b",
        r"\balter\b",
        r"\bcreate\s+table\b",
        r"\bto_sql\b",
    ]
    for pattern in forbidden_patterns:
        assert re.search(pattern, text) is None


def test_decision_service_only_writes_to_app_schema():
    decision_text = (BACKEND_DIR / "services" / "decision_service.py").read_text(encoding="utf-8").lower()

    assert "insert into app.claim_review_decision" in decision_text
    assert "update " not in decision_text
    assert "delete " not in decision_text
    assert "drop " not in decision_text
    assert "truncate" not in decision_text
    assert "alter " not in decision_text
    # Le seul write autorise reste confine au schema applicatif `app` :
    # jamais d'ecriture dans dwh/mart/staging depuis les services backend.
    assert "insert into dwh." not in decision_text
    assert "insert into mart." not in decision_text
    assert "insert into staging." not in decision_text


def test_workflow_service_only_writes_to_app_schema():
    workflow_text = (BACKEND_DIR / "services" / "workflow_service.py").read_text(encoding="utf-8").lower()

    assert "insert into app.claim_workflow_event" in workflow_text
    assert "update " not in workflow_text
    assert "delete " not in workflow_text
    assert "drop " not in workflow_text
    assert "truncate" not in workflow_text
    assert "alter " not in workflow_text
    # Meme garantie que decision_service : jamais d'ecriture dans dwh/mart/staging.
    assert "insert into dwh." not in workflow_text
    assert "insert into mart." not in workflow_text
    assert "insert into staging." not in workflow_text


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


def test_confidence_explanation_flags_unknown_driver_even_when_confidence_high():
    from backend.services.claim_review_service import _confidence_explanation

    explanation = _confidence_explanation(
        conf_level="HIGH",
        missing_keys=0,
        unknown_dims=1,
        weak_join=False,
        missing_driver=True,
        missing_client=False,
    )
    assert explanation == "Qualité partielle — conducteur non identifié."


def test_confidence_explanation_lists_both_identity_gaps():
    from backend.services.claim_review_service import _confidence_explanation

    explanation = _confidence_explanation(
        conf_level="HIGH",
        missing_keys=0,
        unknown_dims=2,
        weak_join=False,
        missing_driver=True,
        missing_client=True,
    )
    assert explanation == "Qualité partielle — conducteur non identifié, client non identifié."


def test_confidence_explanation_still_reports_optimal_when_no_identity_gap():
    from backend.services.claim_review_service import _confidence_explanation

    explanation = _confidence_explanation(
        conf_level="HIGH",
        missing_keys=0,
        unknown_dims=0,
        weak_join=False,
        missing_driver=False,
        missing_client=False,
    )
    assert explanation == "Qualité de données optimale : aucune clé manquante, jointures complètes, géolocalisation cohérente."


def test_confidence_explanation_medium_and_low_unchanged_without_identity_gap():
    from backend.services.claim_review_service import _confidence_explanation

    medium = _confidence_explanation("MEDIUM", 1, 0, False, False, False)
    assert medium == "Confiance modérée : 1 clé(s) manquante(s)."

    low = _confidence_explanation("LOW", 0, 0, True, False, False)
    assert low == "Confiance limitée : jointures défaillantes."


class _FakeRow:
    """Minimal stand-in for a SQLAlchemy Row exposing ._mapping like the real rows."""

    def __init__(self, mapping: dict):
        self._mapping = mapping


def test_timeline_groups_same_stafim_inspection_into_one_event():
    from backend.services.claim_review_service import _timeline_from_feature_and_inspections

    inspection_rows = [
        _FakeRow({
            "inspection_sk": 500,
            "vehicule_sk": 12776,
            "inspection_date": "2025-10-23",
            "days_inspection_to_claim": 42,
            "defective_zone": "ENTRETIEN",
            "business_explanation": "Un sinistre est survenu peu apres une inspection STAFFIM du meme vehicule.",
        }),
        _FakeRow({
            "inspection_sk": 500,
            "vehicule_sk": 12776,
            "inspection_date": "2025-10-23",
            "days_inspection_to_claim": 42,
            "defective_zone": "INTERIEUR",
            "business_explanation": "Un sinistre est survenu peu apres une inspection STAFFIM du meme vehicule.",
        }),
        _FakeRow({
            "inspection_sk": 500,
            "vehicule_sk": 12776,
            "inspection_date": "2025-10-23",
            "days_inspection_to_claim": 42,
            "defective_zone": "SOUS_VEHICULE",
            "business_explanation": "Un sinistre est survenu peu apres une inspection STAFFIM du meme vehicule.",
        }),
    ]

    timeline = _timeline_from_feature_and_inspections(None, inspection_rows)

    stafim_events = [e for e in timeline if e["event_type"] == "Inspection STAFFIM"]
    assert len(stafim_events) == 1
    assert "ENTRETIEN" in stafim_events[0]["description"]
    assert "INTERIEUR" in stafim_events[0]["description"]
    assert "SOUS_VEHICULE" in stafim_events[0]["description"]


def test_contract_validity_uses_effet_dates_when_present():
    from datetime import date
    from backend.services.claim_review_service import _contract_validity_at_claim_date

    contract = _FakeRow({
        "date_debut_effet": date(2024, 1, 1),
        "date_fin_effet": date(2025, 1, 1),
        "date_debut_contrat": date(2020, 1, 1),
        "date_fin_contrat": date(2030, 1, 1),
        "statut_contrat": "EN COURS",
    })

    result = _contract_validity_at_claim_date(contract, date(2024, 6, 1))
    assert result == {"is_valid_at_claim_date": True, "reference": "effet", "statut_contrat": "EN COURS"}


def test_contract_validity_false_when_claim_before_or_after_coverage():
    from datetime import date
    from backend.services.claim_review_service import _contract_validity_at_claim_date

    contract = _FakeRow({
        "date_debut_effet": date(2024, 1, 1),
        "date_fin_effet": date(2025, 1, 1),
        "date_debut_contrat": None,
        "date_fin_contrat": None,
        "statut_contrat": "EXPIRE",
    })

    before = _contract_validity_at_claim_date(contract, date(2023, 12, 31))
    after = _contract_validity_at_claim_date(contract, date(2025, 1, 2))
    assert before["is_valid_at_claim_date"] is False
    assert after["is_valid_at_claim_date"] is False


def test_contract_validity_falls_back_to_contract_dates_without_effet():
    from datetime import date
    from backend.services.claim_review_service import _contract_validity_at_claim_date

    contract = _FakeRow({
        "date_debut_effet": None,
        "date_fin_effet": None,
        "date_debut_contrat": date(2020, 1, 1),
        "date_fin_contrat": date(2030, 1, 1),
        "statut_contrat": "EN COURS",
    })

    result = _contract_validity_at_claim_date(contract, date(2024, 6, 1))
    assert result["is_valid_at_claim_date"] is True
    assert result["reference"] == "contrat"


def test_contract_validity_true_when_no_end_date_yet():
    from datetime import date
    from backend.services.claim_review_service import _contract_validity_at_claim_date

    contract = _FakeRow({
        "date_debut_effet": date(2024, 1, 1),
        "date_fin_effet": None,
        "date_debut_contrat": None,
        "date_fin_contrat": None,
        "statut_contrat": "EN COURS",
    })

    result = _contract_validity_at_claim_date(contract, date(2030, 6, 1))
    assert result["is_valid_at_claim_date"] is True


def test_contract_validity_none_without_contract_or_claim_date():
    from datetime import date
    from backend.services.claim_review_service import _contract_validity_at_claim_date

    contract = _FakeRow({
        "date_debut_effet": date(2024, 1, 1),
        "date_fin_effet": None,
        "date_debut_contrat": None,
        "date_fin_contrat": None,
        "statut_contrat": "EN COURS",
    })

    assert _contract_validity_at_claim_date(None, date(2024, 6, 1)) is None
    assert _contract_validity_at_claim_date(contract, None) is None


def test_contract_validity_handles_mixed_date_and_datetime_types():
    # dwh.fact_sinistre.claim_date is DATE but dwh.dim_contrat's dates are
    # TIMESTAMP: this mirrors the real column types (regression test for a
    # TypeError: can't compare datetime.datetime to datetime.date).
    from datetime import date, datetime
    from backend.services.claim_review_service import _contract_validity_at_claim_date

    contract = _FakeRow({
        "date_debut_effet": datetime(2024, 1, 1, 0, 0, 0),
        "date_fin_effet": datetime(2025, 1, 1, 0, 0, 0),
        "date_debut_contrat": None,
        "date_fin_contrat": None,
        "statut_contrat": "EN COURS",
    })

    result = _contract_validity_at_claim_date(contract, date(2024, 6, 1))
    assert result["is_valid_at_claim_date"] is True


def test_contract_validity_unknown_when_no_start_date_at_all():
    from datetime import date
    from backend.services.claim_review_service import _contract_validity_at_claim_date

    contract = _FakeRow({
        "date_debut_effet": None,
        "date_fin_effet": None,
        "date_debut_contrat": None,
        "date_fin_contrat": None,
        "statut_contrat": "INCONNU",
    })

    result = _contract_validity_at_claim_date(contract, date(2024, 6, 1))
    assert result == {"is_valid_at_claim_date": None, "reference": None, "statut_contrat": "INCONNU"}


def test_timeline_keeps_distinct_inspections_separate():
    from backend.services.claim_review_service import _timeline_from_feature_and_inspections

    inspection_rows = [
        _FakeRow({
            "inspection_sk": 500,
            "vehicule_sk": 12776,
            "inspection_date": "2025-10-23",
            "days_inspection_to_claim": 42,
            "defective_zone": "ENTRETIEN",
            "business_explanation": "x",
        }),
        _FakeRow({
            "inspection_sk": 501,
            "vehicule_sk": 12776,
            "inspection_date": "2025-06-01",
            "days_inspection_to_claim": 186,
            "defective_zone": "SOUS_CAPOT",
            "business_explanation": "y",
        }),
    ]

    timeline = _timeline_from_feature_and_inspections(None, inspection_rows)
    stafim_events = [e for e in timeline if e["event_type"] == "Inspection STAFFIM"]
    assert len(stafim_events) == 2


