from datetime import datetime

import pandas as pd

from etl.mart.compute_claim_smart_features_v2_candidate import (
    SMART_FEATURE_VERSION,
    compute_claim_smart_features_v2,
)


def _source_features():
    return pd.DataFrame([
        {
            "claim_sk": 1,
            "claim_business_id": "S1|G1",
            "feature_run_id": "FEATURE_RUN",
            "claim_date": "2024-01-01",
            "code_garantie": "G1",
            "claim_amount": 100,
            "expected_document_count": 4,
            "available_document_count": 4,
            "critical_document_missing_count": 0,
            "days_claim_to_declaration": 5,
            "claim_before_contract_start_flag": False,
            "client_claim_count_12m": 1,
            "client_claim_count_24m": 2,
            "missing_client_flag": False,
            "missing_contract_flag": False,
            "missing_vehicle_flag": False,
            "missing_guarantee_flag": False,
            "missing_geo_flag": False,
            "unmapped_code_count": 0,
            "invalid_claim_date_flag": False,
            "invalid_declaration_date_flag": False,
        },
        {
            "claim_sk": 2,
            "claim_business_id": "S2|G1",
            "feature_run_id": "FEATURE_RUN",
            "claim_date": "2024-02-01",
            "code_garantie": "G1",
            "claim_amount": 120,
            "expected_document_count": 4,
            "available_document_count": 2,
            "critical_document_missing_count": 1,
            "days_claim_to_declaration": 45,
            "claim_before_contract_start_flag": False,
            "client_claim_count_12m": 3,
            "client_claim_count_24m": 4,
            "missing_client_flag": False,
            "missing_contract_flag": False,
            "missing_vehicle_flag": True,
            "missing_guarantee_flag": False,
            "missing_geo_flag": True,
            "unmapped_code_count": 2,
            "invalid_claim_date_flag": False,
            "invalid_declaration_date_flag": False,
        },
        {
            "claim_sk": 3,
            "claim_business_id": "S3|G1",
            "feature_run_id": "FEATURE_RUN",
            "claim_date": "2024-03-01",
            "code_garantie": "G1",
            "claim_amount": 300,
            "expected_document_count": 4,
            "available_document_count": 4,
            "critical_document_missing_count": 0,
            "days_claim_to_declaration": -1,
            "claim_before_contract_start_flag": True,
            "client_claim_count_12m": 0,
            "client_claim_count_24m": 0,
            "missing_client_flag": False,
            "missing_contract_flag": False,
            "missing_vehicle_flag": False,
            "missing_guarantee_flag": False,
            "missing_geo_flag": False,
            "unmapped_code_count": 0,
            "invalid_claim_date_flag": False,
            "invalid_declaration_date_flag": False,
        },
    ])


def test_smart_features_compute_completeness_chronology_and_quality():
    features = compute_claim_smart_features_v2(
        _source_features(),
        smart_feature_run_id="SMART_RUN",
        calculated_at=datetime(2026, 7, 10, 10, 0, 0),
        min_cohort_size=2,
    )
    by_claim = features.set_index("claim_sk")

    assert by_claim.loc[1, "smart_feature_version"] == SMART_FEATURE_VERSION
    assert by_claim.loc[1, "completeness_rate"] == 1.0
    assert by_claim.loc[2, "missing_document_count"] == 2
    assert by_claim.loc[2, "critical_document_missing_count"] == 1
    assert by_claim.loc[3, "declaration_before_claim_flag"]
    assert by_claim.loc[2, "data_quality_level"] == "LOW"
    assert by_claim.loc[2, "unmapped_code_count"] == 2


def test_input_hash_is_deterministic_for_identical_inputs():
    first = compute_claim_smart_features_v2(_source_features(), calculated_at=datetime(2026, 7, 10, 10, 0, 0))
    second = compute_claim_smart_features_v2(_source_features(), calculated_at=datetime(2026, 7, 10, 11, 0, 0))

    assert first.set_index("claim_sk").loc[1, "input_hash"] == second.set_index("claim_sk").loc[1, "input_hash"]
    assert len(first.set_index("claim_sk").loc[1, "input_hash"]) == 64


def test_zero_history_is_known_but_missing_history_is_not_evaluable():
    known_zero = compute_claim_smart_features_v2(_source_features()).set_index("claim_sk")
    absent_history = _source_features().drop(columns=["client_claim_count_12m", "client_claim_count_24m"])
    absent = compute_claim_smart_features_v2(absent_history).set_index("claim_sk")

    assert known_zero.loc[3, "history_evaluable_flag"]
    assert known_zero.loc[3, "client_claim_count_12m"] == 0
    assert not absent.loc[3, "history_evaluable_flag"]
    assert pd.isna(absent.loc[3, "client_claim_count_12m"])


def test_missing_control_columns_are_not_high_quality_by_default():
    partial = _source_features().drop(columns=[
        "missing_client_flag",
        "missing_contract_flag",
        "missing_vehicle_flag",
        "missing_guarantee_flag",
        "missing_geo_flag",
        "unmapped_code_count",
        "invalid_claim_date_flag",
        "invalid_declaration_date_flag",
    ])
    result = compute_claim_smart_features_v2(partial).set_index("claim_sk")

    assert not result.loc[1, "data_quality_evaluable_flag"]
    assert result.loc[1, "data_quality_level"] == "NOT_EVALUABLE"
    assert result.loc[1, "confidence_level"] == "NOT_EVALUABLE"


def test_missing_dates_make_chronology_not_evaluable():
    partial = _source_features().drop(columns=["days_claim_to_declaration", "claim_before_contract_start_flag"])
    result = compute_claim_smart_features_v2(partial).set_index("claim_sk")

    assert not result.loc[1, "chronology_evaluable_flag"]
    assert pd.isna(result.loc[1, "chronology_signal_count"])


def test_similar_claim_statistics_require_sufficient_point_in_time_cohort():
    displayable = compute_claim_smart_features_v2(_source_features(), min_cohort_size=2).set_index("claim_sk")
    blocked = compute_claim_smart_features_v2(_source_features(), min_cohort_size=20).set_index("claim_sk")

    assert displayable.loc[3, "similar_claim_count"] == 2
    assert displayable.loc[3, "comparison_reliability"] == "DISPLAYABLE"
    assert displayable.loc[3, "amount_ratio_to_median"] > 2
    assert blocked.loc[3, "comparison_reliability"] == "INSUFFICIENT_SAMPLE"
    assert pd.isna(blocked.loc[3, "amount_ratio_to_median"])


def test_comparison_rejects_missing_cohort_attributes_and_reference_date():
    missing_cohort = _source_features().drop(columns=["code_garantie"])
    missing_date = _source_features().drop(columns=["claim_date"])

    assert compute_claim_smart_features_v2(missing_cohort).loc[0, "comparison_status_reason"] == "MISSING_COHORT_ATTRIBUTES"
    assert compute_claim_smart_features_v2(missing_date).loc[0, "comparison_status_reason"] == "MISSING_REFERENCE_DATE"


def test_comparison_excludes_future_rows_and_duplicate_claim_sk():
    frame = pd.DataFrame([
        {"claim_sk": 1, "claim_date": "2024-01-01", "code_garantie": "G1", "claim_amount": 100},
        {"claim_sk": 1, "claim_date": "2024-01-02", "code_garantie": "G1", "claim_amount": 110},
        {"claim_sk": 2, "claim_date": "2024-02-01", "code_garantie": "G1", "claim_amount": 200},
        {"claim_sk": 3, "claim_date": "2024-03-01", "code_garantie": "G1", "claim_amount": 400},
        {"claim_sk": 4, "claim_date": "2024-04-01", "code_garantie": "G1", "claim_amount": 9999},
    ])
    result = compute_claim_smart_features_v2(frame, min_cohort_size=2).set_index("claim_sk")

    assert result.loc[3, "similar_claim_count"] == 2
    assert result.loc[3, "amount_median_similar"] == 155


def test_comparison_handles_zero_median_and_missing_amount():
    zero_frame = pd.DataFrame([
        {"claim_sk": 1, "claim_date": "2024-01-01", "code_garantie": "G1", "claim_amount": 0},
        {"claim_sk": 2, "claim_date": "2024-02-01", "code_garantie": "G1", "claim_amount": 0},
        {"claim_sk": 3, "claim_date": "2024-03-01", "code_garantie": "G1", "claim_amount": 10},
    ])
    missing_amount = zero_frame.copy()
    missing_amount.loc[2, "claim_amount"] = pd.NA

    zero_result = compute_claim_smart_features_v2(zero_frame, min_cohort_size=2).set_index("claim_sk")
    missing_result = compute_claim_smart_features_v2(missing_amount, min_cohort_size=2).set_index("claim_sk")

    assert zero_result.loc[3, "comparison_status_reason"] == "ZERO_MEDIAN"
    assert pd.isna(zero_result.loc[3, "amount_ratio_to_median"])
    assert missing_result.loc[3, "comparison_status_reason"] == "NOT_AVAILABLE"


def test_geo_is_partial_until_explicitly_enabled():
    features = compute_claim_smart_features_v2(_source_features(), geo_ready=False)
    assert features["geo_evaluable_flag"].eq(False).all()
    assert features["geo_mapping_quality"].eq("PARTIAL").all()
