from datetime import datetime

import pandas as pd

from etl.mart.compute_claim_business_rule_signals_v1_candidate import (
    SIGNAL_VERSION,
    attention_label,
    compute_claim_business_rule_signals,
    contains_accusatory_wording,
    validate_business_rule_signals,
)


def test_attention_label_boundaries_are_prioritization_wording():
    assert attention_label(3, "HIGH") == "Verification prioritaire suggeree"
    assert attention_label(2, "MEDIUM") == "Signal metier a examiner"
    assert attention_label(1, "LOW") == "Contexte a verifier"
    assert attention_label(0, "LOW", is_data_quality_signal=True) == "Limite de confiance a documenter"


def test_client_amount_and_chronology_rules_are_emitted_without_changing_score_v1():
    features = pd.DataFrame([{
        "claim_sk": 1,
        "claim_business_id": "S1|G1",
        "feature_run_id": "FEATURE_RUN",
        "client_sk": 10,
        "contrat_sk": 20,
        "vehicle_sk": 30,
        "client_claim_count_12m": 3,
        "days_since_previous_claim": 10,
        "amount_vs_guarantee_median_ratio": 4.0,
        "amount_percentile_by_guarantee": 0.99,
        "high_amount_flag": True,
        "days_contract_start_to_claim": 15,
        "claim_before_contract_start_flag": False,
        "days_claim_to_declaration": 45,
        "confidence_level": "HIGH",
        "missing_client_flag": False,
        "missing_contract_flag": False,
        "missing_vehicle_flag": False,
        "missing_guarantee_flag": False,
        "invalid_claim_date_flag": False,
        "invalid_declaration_date_flag": False,
        "future_claim_date_flag": False,
    }])

    signals = compute_claim_business_rule_signals(
        features,
        signal_run_id="RULE_RUN",
        created_at=datetime(2026, 7, 8, 12, 0, 0),
    )
    validation = validate_business_rule_signals(signals)

    assert set(signals["rule_code"]) == {
        "CLIENT_CLAIMS_12M_HIGH",
        "CLIENT_RECENT_PREVIOUS_CLAIM",
        "AMOUNT_HIGH_BY_GUARANTEE",
        "CLAIM_SOON_AFTER_CONTRACT_START",
        "LONG_DECLARATION_DELAY_MEDIUM",
    }
    assert signals["signal_version"].eq(SIGNAL_VERSION).all()
    assert signals["signal_run_id"].eq("RULE_RUN").all()
    assert validation["duplicate_grain_rows"] == 0
    assert validation["accusatory_wording_rows"] == 0


def test_data_quality_signals_have_zero_candidate_points():
    features = pd.DataFrame([{
        "claim_sk": 2,
        "claim_business_id": "S2|G1",
        "feature_run_id": "FEATURE_RUN",
        "client_sk": 0,
        "contrat_sk": 0,
        "vehicle_sk": 0,
        "client_claim_count_12m": 0,
        "days_since_previous_claim": pd.NA,
        "amount_vs_guarantee_median_ratio": 1.0,
        "amount_percentile_by_guarantee": 0.50,
        "high_amount_flag": False,
        "days_contract_start_to_claim": pd.NA,
        "claim_before_contract_start_flag": False,
        "days_claim_to_declaration": 3,
        "confidence_level": "LOW",
        "missing_client_flag": True,
        "missing_contract_flag": True,
        "missing_vehicle_flag": True,
        "missing_guarantee_flag": False,
        "invalid_claim_date_flag": False,
        "invalid_declaration_date_flag": False,
        "future_claim_date_flag": False,
    }])

    signals = compute_claim_business_rule_signals(features, signal_run_id="RULE_RUN")

    assert len(signals) == 1
    assert signals.loc[0, "rule_code"] == "DATA_QUALITY_LIMITATION"
    assert signals.loc[0, "candidate_points"] == 0
    assert signals.loc[0, "is_data_quality_signal"]
    assert "missing_client_flag" in signals.loc[0, "rule_observed_value"]


def test_claim_before_contract_and_negative_declaration_are_coherence_rules():
    features = pd.DataFrame([{
        "claim_sk": 3,
        "claim_business_id": "S3|G1",
        "feature_run_id": "FEATURE_RUN",
        "client_sk": 10,
        "contrat_sk": 20,
        "vehicle_sk": 30,
        "client_claim_count_12m": 0,
        "days_since_previous_claim": pd.NA,
        "amount_vs_guarantee_median_ratio": 1.0,
        "amount_percentile_by_guarantee": 0.50,
        "high_amount_flag": False,
        "days_contract_start_to_claim": -5,
        "claim_before_contract_start_flag": True,
        "days_claim_to_declaration": -2,
        "confidence_level": "MEDIUM",
    }])

    signals = compute_claim_business_rule_signals(features, signal_run_id="RULE_RUN")

    assert set(signals["rule_code"]) == {
        "CLAIM_BEFORE_CONTRACT_START",
        "DECLARATION_BEFORE_CLAIM_DATE",
    }
    assert signals["business_explanation"].str.len().gt(0).all()
    assert validate_business_rule_signals(signals)["negative_candidate_point_rows"] == 0


def test_validation_detects_duplicate_grain_and_accusatory_wording():
    features = pd.DataFrame([{
        "claim_sk": 4,
        "claim_business_id": "S4|G1",
        "feature_run_id": "FEATURE_RUN",
        "client_claim_count_12m": 3,
        "days_since_previous_claim": pd.NA,
        "amount_vs_guarantee_median_ratio": 1.0,
        "amount_percentile_by_guarantee": 0.50,
        "high_amount_flag": False,
        "days_contract_start_to_claim": pd.NA,
        "claim_before_contract_start_flag": False,
        "days_claim_to_declaration": 1,
        "confidence_level": "HIGH",
    }])
    signals = compute_claim_business_rule_signals(features, signal_run_id="RULE_RUN")
    duplicated = pd.concat([signals, signals], ignore_index=True)
    duplicated.loc[0, "business_explanation"] = "fraud detected"

    validation = validate_business_rule_signals(duplicated)

    assert validation["duplicate_grain_rows"] == 1
    assert validation["accusatory_wording_rows"] == 1
    assert contains_accusatory_wording("proof of fraud")
