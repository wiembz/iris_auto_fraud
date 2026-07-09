from datetime import datetime

import pandas as pd

from etl.mart.compute_claim_attention_hybrid_ml_score_v1_candidate import (
    CONFIG_PATH,
    SCORE_VERSION,
    build_ml_detail_rows,
    compute_claim_attention_hybrid_ml_scores,
    load_hybrid_ml_config,
)
from etl.mart.compute_claim_attention_hybrid_score_v1_candidate import validate_hybrid_outputs


def _config():
    return load_hybrid_ml_config(CONFIG_PATH)


def _base_scores():
    return pd.DataFrame([
        {
            "claim_sk": 1,
            "claim_business_id": "S1|G1",
            "score_version": "IRIS_CLAIM_ATTENTION_HYBRID_V1_CANDIDATE",
            "score_run_id": "BASE_RUN",
            "feature_run_id": "FEATURE_RUN",
            "attention_score": 45,
            "attention_level": "Points a verifier",
            "confidence_level": "HIGH",
            "main_reason_1": "Base reason",
            "main_reason_2": None,
            "main_reason_3": None,
            "profile_name": "BASE",
            "source_system": "BASE",
            "created_at": datetime(2026, 7, 8, 12, 0, 0),
        },
        {
            "claim_sk": 2,
            "claim_business_id": "S2|G1",
            "score_version": "IRIS_CLAIM_ATTENTION_HYBRID_V1_CANDIDATE",
            "score_run_id": "BASE_RUN",
            "feature_run_id": "FEATURE_RUN",
            "attention_score": 96,
            "attention_level": "Examen prioritaire suggere",
            "confidence_level": "MEDIUM",
            "main_reason_1": "Base high reason",
            "main_reason_2": None,
            "main_reason_3": None,
            "profile_name": "BASE",
            "source_system": "BASE",
            "created_at": datetime(2026, 7, 8, 12, 0, 0),
        },
    ])


def _base_details():
    return pd.DataFrame([
        {
            "claim_sk": 1,
            "claim_business_id": "S1|G1",
            "score_run_id": "BASE_RUN",
            "score_version": "IRIS_CLAIM_ATTENTION_HYBRID_V1_CANDIDATE",
            "signal_family": "Regles metier - Montant atypique",
            "signal_code": "AMOUNT_HIGH_BY_GUARANTEE",
            "signal_label": "Montant eleve",
            "signal_value": "ratio=4",
            "points": 45,
            "severity": "HIGH",
            "business_explanation": "Le montant est au-dessus du profil de garantie.",
            "profile_name": "BASE",
            "created_at": datetime(2026, 7, 8, 12, 0, 0),
        },
        {
            "claim_sk": 2,
            "claim_business_id": "S2|G1",
            "score_run_id": "BASE_RUN",
            "score_version": "IRIS_CLAIM_ATTENTION_HYBRID_V1_CANDIDATE",
            "signal_family": "Regles metier - Recurrence client",
            "signal_code": "CLIENT_CLAIMS_12M_HIGH",
            "signal_label": "Recurrence client elevee",
            "signal_value": "5",
            "points": 96,
            "severity": "HIGH",
            "business_explanation": "Plusieurs sinistres precedents sont observes.",
            "profile_name": "BASE",
            "created_at": datetime(2026, 7, 8, 12, 0, 0),
        },
    ])


def _ml_signals():
    return pd.DataFrame([
        {
            "claim_sk": 1,
            "claim_business_id": "S1|G1",
            "raw_anomaly_score": 0.8,
            "score_ml": 0.99,
            "ml_attention_points": 10,
            "top_variable_1": "claim_amount: value=10000, percentile=0.99",
            "top_variable_2": "days_claim_to_declaration: value=90, percentile=0.95",
            "top_variable_3": "client_claim_count_12m: value=4, percentile=0.90",
        },
        {
            "claim_sk": 2,
            "claim_business_id": "S2|G1",
            "raw_anomaly_score": 0.7,
            "score_ml": 0.96,
            "ml_attention_points": 10,
            "top_variable_1": "claim_amount: value=9000, percentile=0.96",
            "top_variable_2": None,
            "top_variable_3": None,
        },
    ])


def test_committed_hybrid_ml_config_is_loadable():
    config = _config()

    assert config["score_version"] == SCORE_VERSION
    assert config["base_hybrid_score_version"] == "IRIS_CLAIM_ATTENTION_HYBRID_V1_CANDIDATE"
    assert config["ml"]["max_points"] == 10


def test_ml_details_are_capped_by_remaining_score_room():
    details = build_ml_detail_rows(
        _ml_signals(),
        _base_scores(),
        "HYBRID_ML_RUN",
        _config(),
        datetime(2026, 7, 8, 12, 0, 0),
    )

    assert details.set_index("claim_sk").loc[1, "points"] == 10
    assert details.set_index("claim_sk").loc[2, "points"] == 4
    assert details["signal_family"].eq("ML atypicite calibree").all()


def test_hybrid_ml_score_combines_base_and_ml_without_overflow():
    scores, details = compute_claim_attention_hybrid_ml_scores(
        _base_scores(),
        _base_details(),
        _ml_signals(),
        config=_config(),
        score_run_id="HYBRID_ML_RUN",
        created_at=datetime(2026, 7, 8, 12, 0, 0),
    )

    by_claim = scores.set_index("claim_sk")
    assert by_claim.loc[1, "attention_score"] == 55
    assert by_claim.loc[2, "attention_score"] == 100
    assert by_claim.loc[1, "score_version"] == SCORE_VERSION
    assert validate_hybrid_outputs(scores, details)["detail_point_mismatch_rows"] == 0
    assert validate_hybrid_outputs(scores, details)["score_out_of_range_rows"] == 0
