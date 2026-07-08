from datetime import datetime

import pandas as pd

from etl.mart.compute_post_inspection_attention_signal_v1_candidate import (
    SIGNAL_VERSION,
    aggregate_checkpoint_anomalies,
    business_explanation,
    compute_post_inspection_signals,
    confidence_level,
    contains_accusatory_wording,
    date_key_to_timestamp,
    delay_bucket,
)


def test_date_key_parser_handles_valid_zero_and_invalid_values():
    assert pd.Timestamp("2024-01-31") == date_key_to_timestamp(20240131)
    assert pd.isna(date_key_to_timestamp(0))
    assert pd.isna(date_key_to_timestamp("0"))
    assert pd.isna(date_key_to_timestamp(20240231))


def test_delay_bucket_mapping_uses_calendar_day_counts():
    assert delay_bucket(0) == "DAYS_0_7"
    assert delay_bucket(7) == "DAYS_0_7"
    assert delay_bucket(8) == "DAYS_8_30"
    assert delay_bucket(30) == "DAYS_8_30"
    assert delay_bucket(31) == "DAYS_31_90"
    assert delay_bucket(90) == "DAYS_31_90"
    assert delay_bucket(-1) is None
    assert delay_bucket(91) is None


def test_anomaly_aggregation_groups_by_inspection_and_zone():
    checkpoints = pd.DataFrame({
        "inspection_key": ["I1", "I1", "I1", "I2"],
        "zone_controle": ["SOUS_CAPOT", "SOUS_CAPOT", "INTERIEUR", "SOUS_CAPOT"],
        "checkpoint_code": ["oil", "battery", "seat", "oil"],
        "checkpoint_libelle": ["Huile", "Batterie", "Siege", "Huile"],
        "est_anomalie": [True, False, True, True],
        "est_anomalie_critique": [True, False, False, False],
    })

    result = aggregate_checkpoint_anomalies(checkpoints)

    row = result[
        result["inspection_key"].eq("I1")
        & result["defective_zone"].eq("SOUS_CAPOT")
    ].iloc[0]
    assert row["defective_checkpoint_count"] == 1
    assert row["critical_checkpoint_count"] == 1
    assert row["defective_checkpoint_codes"] == "oil"


def test_confidence_assignment():
    assert confidence_level(5, 2, "SOUS_CAPOT") == "HIGH"
    assert confidence_level(30, 1, "SOUS_CAPOT") == "HIGH"
    assert confidence_level(31, 1, "SOUS_CAPOT") == "MEDIUM"
    assert confidence_level(90, 1, "SOUS_CAPOT") == "MEDIUM"
    assert confidence_level(5, 0, "NO_DOCUMENTED_ANOMALY") == "LOW"


def test_business_explanation_is_present_and_non_accusatory():
    explanation = business_explanation("HIGH", has_documented_anomaly=True)

    assert explanation
    assert not contains_accusatory_wording(explanation)


def test_compute_signals_excludes_missing_vehicle_key_and_claim_before_inspection():
    inspections = pd.DataFrame({
        "fact_inspection_vehicule_sk": [1, 2],
        "inspection_key": ["I1", "I2"],
        "vehicule_sk": [10, 0],
        "date_inspection_sk": [20240110, 20240110],
        "immatriculation_norm": ["123TU456", "999TU999"],
    })
    claims = pd.DataFrame({
        "fact_sinistre_sk": [100, 101, 102],
        "sinistre_garantie_key": ["S100|G", "S101|G", "S102|G"],
        "contrat_sk": [500, 501, 502],
        "client_sk": [700, 701, 702],
        "vehicule_sk": [10, 10, 0],
        "date_survenance_sk": [20240115, 20240105, 20240115],
        "code_garantie": ["G", "G", "G"],
    })
    checkpoints = pd.DataFrame({
        "inspection_key": ["I1"],
        "zone_controle": ["SOUS_CAPOT"],
        "checkpoint_code": ["oil"],
        "checkpoint_libelle": ["Huile"],
        "est_anomalie": [True],
        "est_anomalie_critique": [False],
    })

    signals, validation = compute_post_inspection_signals(
        inspections,
        checkpoints,
        claims,
        signal_run_id="RUN",
        created_at=datetime(2024, 1, 1),
    )

    assert len(signals) == 1
    assert signals.loc[0, "claim_sk"] == 100
    assert signals.loc[0, "days_inspection_to_claim"] == 5
    assert validation["negative_delay_rows"] == 0
    excluded = validation["excluded_candidates"].set_index("exclusion_reason")["rows"].to_dict()
    assert excluded["INSPECTION_MISSING_VEHICULE_SK"] == 1
    assert excluded["CLAIM_MISSING_VEHICULE_SK"] == 1
    assert excluded["CLAIM_BEFORE_INSPECTION"] == 1


def test_compute_signals_creates_low_context_row_without_documented_anomaly():
    inspections = pd.DataFrame({
        "fact_inspection_vehicule_sk": [1],
        "inspection_key": ["I1"],
        "vehicule_sk": [10],
        "date_inspection_sk": [20240110],
        "immatriculation_norm": ["123TU456"],
    })
    claims = pd.DataFrame({
        "fact_sinistre_sk": [100],
        "sinistre_garantie_key": ["S100|G"],
        "contrat_sk": [500],
        "client_sk": [700],
        "vehicule_sk": [10],
        "date_survenance_sk": [20240112],
        "code_garantie": ["G"],
    })

    signals, _ = compute_post_inspection_signals(
        inspections,
        pd.DataFrame(),
        claims,
        signal_run_id="RUN",
        created_at=datetime(2024, 1, 1),
    )

    assert len(signals) == 1
    assert signals.loc[0, "defective_zone"] == "NO_DOCUMENTED_ANOMALY"
    assert signals.loc[0, "confidence_level"] == "LOW"
    assert signals.loc[0, "attention_level"] == "Contexte technique documente"


def test_no_duplicate_grain_for_zone_aggregation():
    inspections = pd.DataFrame({
        "fact_inspection_vehicule_sk": [1],
        "inspection_key": ["I1"],
        "vehicule_sk": [10],
        "date_inspection_sk": [20240110],
        "immatriculation_norm": ["123TU456"],
    })
    claims = pd.DataFrame({
        "fact_sinistre_sk": [100],
        "sinistre_garantie_key": ["S100|G"],
        "contrat_sk": [500],
        "client_sk": [700],
        "vehicule_sk": [10],
        "date_survenance_sk": [20240112],
        "code_garantie": ["G"],
    })
    checkpoints = pd.DataFrame({
        "inspection_key": ["I1", "I1"],
        "zone_controle": ["SOUS_CAPOT", "SOUS_CAPOT"],
        "checkpoint_code": ["oil", "battery"],
        "checkpoint_libelle": ["Huile", "Batterie"],
        "est_anomalie": [True, True],
        "est_anomalie_critique": [False, False],
    })

    signals, validation = compute_post_inspection_signals(
        inspections,
        checkpoints,
        claims,
        signal_run_id="RUN",
        created_at=datetime(2024, 1, 1),
    )

    assert len(signals) == 1
    assert signals.loc[0, "signal_version"] == SIGNAL_VERSION
    assert signals.loc[0, "defective_checkpoint_count"] == 2
    assert validation["duplicate_grain_rows"] == 0
