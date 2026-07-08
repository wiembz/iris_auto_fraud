import pandas as pd

from etl.mart.compute_claim_attention_score_v1_candidate import (
    SCORE_VERSION,
    attention_level,
    compute_claim_attention_scores,
    validate_score_outputs,
)


def test_attention_level_boundaries():
    assert attention_level(0) == "Analyse standard"
    assert attention_level(24) == "Analyse standard"
    assert attention_level(25) == "Points a verifier"
    assert attention_level(50) == "Examen renforce suggere"
    assert attention_level(75) == "Examen prioritaire suggere"


def test_score_uses_only_v1_active_families_and_keeps_quality_at_zero_points():
    features = pd.DataFrame([{
        "claim_sk": 1,
        "claim_business_id": "S1|G1",
        "feature_run_id": "FEATURE_RUN",
        "client_claim_count_12m": 3,
        "days_since_previous_claim": 10,
        "amount_vs_guarantee_median_ratio": 4.0,
        "amount_percentile_by_guarantee": 0.99,
        "high_amount_flag": True,
        "days_claim_to_declaration": 120,
        "days_contract_start_to_claim": 20,
        "claim_before_contract_start_flag": False,
        "confidence_level": "LOW",
        "geo_signal_ready_flag": False,
        "vhs_signal_ready_flag": False,
        "third_party_signal_ready_flag": False,
        "vehicle_recurrence_ready_flag": False,
    }])

    scores, details = compute_claim_attention_scores(features, score_run_id="SCORE_RUN")
    validation = validate_score_outputs(scores, details)

    assert scores.loc[0, "score_version"] == SCORE_VERSION
    assert scores.loc[0, "attention_score"] == 63
    assert scores.loc[0, "attention_level"] == "Examen renforce suggere"
    assert validation["detail_point_mismatch_rows"] == 0
    assert "Qualite donnees" in set(details["signal_family"])
    assert details.loc[details["signal_family"].eq("Qualite donnees"), "points"].iloc[0] == 0
    assert "Cohérence géographique" not in set(details["signal_family"])
    assert "VHS / état technique" not in set(details["signal_family"])


def test_score_has_standard_reason_when_no_positive_signal():
    features = pd.DataFrame([{
        "claim_sk": 2,
        "claim_business_id": "S2|G1",
        "feature_run_id": "FEATURE_RUN",
        "client_claim_count_12m": 0,
        "days_since_previous_claim": pd.NA,
        "amount_vs_guarantee_median_ratio": 1.0,
        "amount_percentile_by_guarantee": 0.5,
        "high_amount_flag": False,
        "days_claim_to_declaration": 2,
        "days_contract_start_to_claim": 400,
        "claim_before_contract_start_flag": False,
        "confidence_level": "HIGH",
    }])

    scores, details = compute_claim_attention_scores(features, score_run_id="SCORE_RUN")

    assert scores.loc[0, "attention_score"] == 0
    assert scores.loc[0, "attention_level"] == "Analyse standard"
    assert scores.loc[0, "main_reason_1"] == "Aucun signal prioritaire V1"
    assert details.empty
