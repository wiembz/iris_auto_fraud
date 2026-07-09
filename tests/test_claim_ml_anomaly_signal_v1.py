from datetime import datetime

import pandas as pd

from etl.mart.compute_claim_ml_anomaly_signal_v1_candidate import (
    CONFIG_PATH,
    SIGNAL_VERSION,
    compute_ml_anomaly_signals,
    load_ml_config,
    percentile_scores,
    prepare_ml_feature_matrix,
    validate_ml_anomaly_signals,
)


def _features():
    return pd.DataFrame([
        {
            "claim_sk": 1,
            "claim_business_id": "S1|G1",
            "feature_run_id": "FEATURE_RUN",
            "claim_date": "2024-01-01",
            "claim_amount": 1000,
            "amount_percentile_by_guarantee": 0.20,
            "amount_vs_guarantee_median_ratio": 1.0,
            "client_claim_count_12m": 0,
            "client_claim_count_24m": 0,
            "days_since_previous_claim": pd.NA,
            "days_claim_to_declaration": 2,
            "days_contract_start_to_claim": 200,
            "client_sk": 10,
            "vehicle_sk": 100,
            "conducteur_sk": 1000,
            "tiers_sk": 2000,
            "code_garantie": "G1",
        },
        {
            "claim_sk": 2,
            "claim_business_id": "S2|G1",
            "feature_run_id": "FEATURE_RUN",
            "claim_date": "2024-02-01",
            "claim_amount": 1100,
            "amount_percentile_by_guarantee": 0.30,
            "amount_vs_guarantee_median_ratio": 1.1,
            "client_claim_count_12m": 1,
            "client_claim_count_24m": 1,
            "days_since_previous_claim": 31,
            "days_claim_to_declaration": 3,
            "days_contract_start_to_claim": 210,
            "client_sk": 10,
            "vehicle_sk": 100,
            "conducteur_sk": 1000,
            "tiers_sk": 2000,
            "code_garantie": "G1",
        },
        {
            "claim_sk": 3,
            "claim_business_id": "S3|G1",
            "feature_run_id": "FEATURE_RUN",
            "claim_date": "2024-03-01",
            "claim_amount": 1200,
            "amount_percentile_by_guarantee": 0.40,
            "amount_vs_guarantee_median_ratio": 1.2,
            "client_claim_count_12m": 2,
            "client_claim_count_24m": 2,
            "days_since_previous_claim": 29,
            "days_claim_to_declaration": 4,
            "days_contract_start_to_claim": 220,
            "client_sk": 10,
            "vehicle_sk": 100,
            "conducteur_sk": 1000,
            "tiers_sk": 2000,
            "code_garantie": "G1",
        },
        {
            "claim_sk": 4,
            "claim_business_id": "S4|G2",
            "feature_run_id": "FEATURE_RUN",
            "claim_date": "2024-04-01",
            "claim_amount": 1300,
            "amount_percentile_by_guarantee": 0.50,
            "amount_vs_guarantee_median_ratio": 1.3,
            "client_claim_count_12m": 0,
            "client_claim_count_24m": 0,
            "days_since_previous_claim": pd.NA,
            "days_claim_to_declaration": 5,
            "days_contract_start_to_claim": 230,
            "client_sk": 20,
            "vehicle_sk": 200,
            "conducteur_sk": 2000,
            "tiers_sk": 3000,
            "code_garantie": "G2",
        },
        {
            "claim_sk": 5,
            "claim_business_id": "S5|G2",
            "feature_run_id": "FEATURE_RUN",
            "claim_date": "2024-05-01",
            "claim_amount": 1400,
            "amount_percentile_by_guarantee": 0.60,
            "amount_vs_guarantee_median_ratio": 1.4,
            "client_claim_count_12m": 0,
            "client_claim_count_24m": 0,
            "days_since_previous_claim": pd.NA,
            "days_claim_to_declaration": 6,
            "days_contract_start_to_claim": 240,
            "client_sk": 30,
            "vehicle_sk": 300,
            "conducteur_sk": 3000,
            "tiers_sk": 4000,
            "code_garantie": "G2",
        },
        {
            "claim_sk": 6,
            "claim_business_id": "S6|G2",
            "feature_run_id": "FEATURE_RUN",
            "claim_date": "2024-06-01",
            "claim_amount": 50000,
            "amount_percentile_by_guarantee": 0.99,
            "amount_vs_guarantee_median_ratio": 8.0,
            "client_claim_count_12m": 5,
            "client_claim_count_24m": 7,
            "days_since_previous_claim": 3,
            "days_claim_to_declaration": 120,
            "days_contract_start_to_claim": 2,
            "client_sk": 40,
            "vehicle_sk": 400,
            "conducteur_sk": 4000,
            "tiers_sk": 5000,
            "code_garantie": "G2",
        },
    ])


def test_committed_ml_config_is_loadable():
    config = load_ml_config(CONFIG_PATH)

    assert config["signal_version"] == SIGNAL_VERSION
    assert config["model"]["type"] == "IsolationForest"
    assert "claim_amount" in config["features"]


def test_percentile_scores_are_interpretable():
    calibrated = percentile_scores(pd.Series([10.0, 20.0, 30.0, 40.0]))

    assert calibrated.iloc[-1] == 1.0
    assert calibrated.between(0, 1).all()


def test_prepare_ml_feature_matrix_adds_recurrence_and_post_inspection_context():
    post = pd.DataFrame([
        {"claim_sk": 6, "scenario_code": "A_INSPECTION_TO_CLAIM"},
        {"claim_sk": 6, "scenario_code": "A_INSPECTION_TO_CLAIM"},
    ])
    config = load_ml_config(CONFIG_PATH)

    enriched, matrix, imputation = prepare_ml_feature_matrix(_features(), post, config)

    assert enriched.loc[enriched["claim_sk"].eq(6), "post_inspection_signal_count"].iloc[0] == 2
    assert "vehicle_claim_count_12m" in matrix.columns
    assert matrix.isna().sum().sum() == 0
    assert set(imputation) == set(config["features"])


def test_compute_ml_anomaly_signals_calibrates_and_stores_explanations():
    config = load_ml_config(CONFIG_PATH)
    signals = compute_ml_anomaly_signals(
        _features(),
        pd.DataFrame([{"claim_sk": 6, "scenario_code": "A_INSPECTION_TO_CLAIM"}]),
        config=config,
        signal_run_id="ML_RUN",
        created_at=datetime(2026, 7, 8, 12, 0, 0),
    )
    validation = validate_ml_anomaly_signals(signals)

    assert len(signals) == 6
    assert signals["score_ml"].between(0, 1).all()
    assert signals["feature_list_json"].str.contains("claim_amount").all()
    assert signals["top_variable_1"].notna().all()
    assert validation["duplicate_grain_rows"] == 0
    assert validation["accusatory_wording_rows"] == 0
