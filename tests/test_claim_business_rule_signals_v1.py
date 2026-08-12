from datetime import datetime

import pandas as pd

from etl.mart.compute_claim_business_rule_signals_v1_candidate import (
    SIGNAL_VERSION,
    attention_label,
    compute_claim_business_rule_signals,
    contains_accusatory_wording,
    enrich_features_for_business_rules,
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


def test_claim_before_contract_start_is_a_data_quality_signal_not_suspicion():
    # Un sinistre anterieur au debut de contrat est presque toujours une
    # incoherence de saisie contractuelle (contrat retroactif, date mal
    # saisie), pas un indice de fraude : ce signal ne doit jamais ajouter de
    # points d'attention, seulement documenter une limite de confiance.
    features = pd.DataFrame([{
        "claim_sk": 99,
        "claim_business_id": "S99|G1",
        "feature_run_id": "FEATURE_RUN",
        "client_sk": 10,
        "contrat_sk": 20,
        "vehicle_sk": 30,
        "client_claim_count_12m": 0,
        "days_since_previous_claim": pd.NA,
        "amount_vs_guarantee_median_ratio": 1.0,
        "amount_percentile_by_guarantee": 0.50,
        "high_amount_flag": False,
        "days_contract_start_to_claim": -30,
        "claim_before_contract_start_flag": True,
        "days_claim_to_declaration": 1,
        "confidence_level": "MEDIUM",
    }])

    signals = compute_claim_business_rule_signals(features, signal_run_id="RULE_RUN")
    row = signals[signals["rule_code"] == "CLAIM_BEFORE_CONTRACT_START"].iloc[0]

    assert row["rule_family"] == "Qualite donnees"
    assert row["candidate_points"] == 0
    assert row["rule_severity_rank"] == 0
    assert bool(row["is_data_quality_signal"]) is True
    assert row["attention_level"] == "Limite de confiance a documenter"
    assert not contains_accusatory_wording(row["business_explanation"])


def test_recent_contract_amendment_is_a_chronology_suspicion_rule():
    features = pd.DataFrame([{
        "claim_sk": 100,
        "claim_business_id": "S100|G1",
        "feature_run_id": "FEATURE_RUN",
        "client_sk": 10,
        "contrat_sk": 20,
        "vehicle_sk": 30,
        "client_claim_count_12m": 0,
        "days_since_previous_claim": pd.NA,
        "amount_vs_guarantee_median_ratio": 1.0,
        "amount_percentile_by_guarantee": 0.50,
        "high_amount_flag": False,
        "days_contract_start_to_claim": 400,
        "claim_before_contract_start_flag": False,
        "days_claim_to_declaration": 1,
        "days_since_last_avenant": 30,
        "recent_contract_change_flag": True,
        "confidence_level": "HIGH",
    }])

    signals = compute_claim_business_rule_signals(features, signal_run_id="RULE_RUN")
    row = signals[signals["rule_code"] == "RECENT_CONTRACT_AMENDMENT"].iloc[0]

    assert row["rule_family"] == "Chronologie"
    assert row["candidate_points"] == 10
    assert bool(row["is_data_quality_signal"]) is False
    assert row["rule_observed_value"] == "30"


def test_recent_contract_amendment_does_not_fire_when_flag_is_false():
    features = pd.DataFrame([{
        "claim_sk": 101,
        "claim_business_id": "S101|G1",
        "feature_run_id": "FEATURE_RUN",
        "client_sk": 10,
        "contrat_sk": 20,
        "vehicle_sk": 30,
        "client_claim_count_12m": 0,
        "days_since_previous_claim": pd.NA,
        "amount_vs_guarantee_median_ratio": 1.0,
        "amount_percentile_by_guarantee": 0.50,
        "high_amount_flag": False,
        "days_contract_start_to_claim": 400,
        "claim_before_contract_start_flag": False,
        "days_claim_to_declaration": 1,
        "days_since_last_avenant": 200,
        "recent_contract_change_flag": False,
        "confidence_level": "HIGH",
    }])

    signals = compute_claim_business_rule_signals(features, signal_run_id="RULE_RUN")

    assert "RECENT_CONTRACT_AMENDMENT" not in set(signals["rule_code"])


def test_rapid_declaration_after_subscription_is_a_chronology_suspicion_rule():
    features = pd.DataFrame([{
        "claim_sk": 102,
        "claim_business_id": "S102|G1",
        "feature_run_id": "FEATURE_RUN",
        "client_sk": 10,
        "contrat_sk": 20,
        "vehicle_sk": 30,
        "client_claim_count_12m": 0,
        "days_since_previous_claim": pd.NA,
        "amount_vs_guarantee_median_ratio": 1.0,
        "amount_percentile_by_guarantee": 0.50,
        "high_amount_flag": False,
        "days_contract_start_to_claim": 400,
        "claim_before_contract_start_flag": False,
        "days_claim_to_declaration": 1,
        "days_contract_start_to_declaration": 15,
        "rapid_declaration_after_subscription_flag": True,
        "confidence_level": "HIGH",
    }])

    signals = compute_claim_business_rule_signals(features, signal_run_id="RULE_RUN")
    row = signals[signals["rule_code"] == "RAPID_DECLARATION_AFTER_SUBSCRIPTION"].iloc[0]

    assert row["rule_family"] == "Chronologie"
    assert row["candidate_points"] == 10
    assert bool(row["is_data_quality_signal"]) is False
    assert row["rule_observed_value"] == "15"


def test_tiers_identity_incomplete_is_a_tiers_family_rule():
    features = pd.DataFrame([{
        "claim_sk": 103,
        "claim_business_id": "S103|G1",
        "feature_run_id": "FEATURE_RUN",
        "client_sk": 10,
        "contrat_sk": 20,
        "vehicle_sk": 30,
        "tiers_sk": 501,
        "client_claim_count_12m": 0,
        "days_since_previous_claim": pd.NA,
        "amount_vs_guarantee_median_ratio": 1.0,
        "amount_percentile_by_guarantee": 0.50,
        "high_amount_flag": False,
        "days_contract_start_to_claim": 400,
        "claim_before_contract_start_flag": False,
        "days_claim_to_declaration": 1,
        "tiers_identity_incomplete_flag": True,
        "confidence_level": "HIGH",
    }])

    signals = compute_claim_business_rule_signals(features, signal_run_id="RULE_RUN")
    row = signals[signals["rule_code"] == "TIERS_IDENTITY_INCOMPLETE"].iloc[0]

    assert row["rule_family"] == "Tiers"
    assert row["candidate_points"] == 6
    assert bool(row["is_data_quality_signal"]) is False


def test_tiers_identity_incomplete_does_not_fire_when_flag_is_false():
    features = pd.DataFrame([{
        "claim_sk": 104,
        "claim_business_id": "S104|G1",
        "feature_run_id": "FEATURE_RUN",
        "client_sk": 10,
        "contrat_sk": 20,
        "vehicle_sk": 30,
        "tiers_sk": 502,
        "client_claim_count_12m": 0,
        "days_since_previous_claim": pd.NA,
        "amount_vs_guarantee_median_ratio": 1.0,
        "amount_percentile_by_guarantee": 0.50,
        "high_amount_flag": False,
        "days_contract_start_to_claim": 400,
        "claim_before_contract_start_flag": False,
        "days_claim_to_declaration": 1,
        "tiers_identity_incomplete_flag": False,
        "confidence_level": "HIGH",
    }])

    signals = compute_claim_business_rule_signals(features, signal_run_id="RULE_RUN")

    assert "TIERS_IDENTITY_INCOMPLETE" not in set(signals["rule_code"])


def test_tiers_repeated_across_clients_is_not_wired_to_any_rule():
    # Verified on real data: nom_tiers is massively polluted with claim-cause
    # words ("DERAPAGE", "BRIS DE GLACE", "INCENDIE", "VOL") and placeholder
    # codes, not just legitimate shared institutions (STEG, insurers,
    # leasing companies) -- ~19% of claims fired this rule for reasons
    # unrelated to fraud. It stays disabled; tiers_repeat_client_count is
    # still computed (raw data) but must never produce a signal.
    features = pd.DataFrame([{
        "claim_sk": 105,
        "claim_business_id": "S105|G1",
        "feature_run_id": "FEATURE_RUN",
        "client_sk": 10,
        "contrat_sk": 20,
        "vehicle_sk": 30,
        "tiers_sk": 501,
        "client_claim_count_12m": 0,
        "days_since_previous_claim": pd.NA,
        "amount_vs_guarantee_median_ratio": 1.0,
        "amount_percentile_by_guarantee": 0.50,
        "high_amount_flag": False,
        "days_contract_start_to_claim": 400,
        "claim_before_contract_start_flag": False,
        "days_claim_to_declaration": 1,
        "tiers_repeat_client_count": 3,
        "client_tiers_pair_repeat_count": 1,
        "confidence_level": "HIGH",
    }])

    signals = compute_claim_business_rule_signals(features, signal_run_id="RULE_RUN")

    assert "TIERS_REPEATED_ACROSS_CLIENTS" not in set(signals["rule_code"])


def test_client_tiers_pair_repeated_fires_above_threshold():
    features = pd.DataFrame([{
        "claim_sk": 106,
        "claim_business_id": "S106|G1",
        "feature_run_id": "FEATURE_RUN",
        "client_sk": 10,
        "contrat_sk": 20,
        "vehicle_sk": 30,
        "tiers_sk": 501,
        "client_claim_count_12m": 0,
        "days_since_previous_claim": pd.NA,
        "amount_vs_guarantee_median_ratio": 1.0,
        "amount_percentile_by_guarantee": 0.50,
        "high_amount_flag": False,
        "days_contract_start_to_claim": 400,
        "claim_before_contract_start_flag": False,
        "days_claim_to_declaration": 1,
        "tiers_repeat_client_count": 1,
        "client_tiers_pair_repeat_count": 3,
        "confidence_level": "HIGH",
    }])

    signals = compute_claim_business_rule_signals(features, signal_run_id="RULE_RUN")
    row = signals[signals["rule_code"] == "CLIENT_TIERS_PAIR_REPEATED"].iloc[0]

    assert row["rule_family"] == "Tiers"
    assert row["candidate_points"] == 18
    assert "TIERS_REPEATED_ACROSS_CLIENTS" not in set(signals["rule_code"])


def test_tiers_repeat_rules_do_not_fire_below_threshold():
    features = pd.DataFrame([{
        "claim_sk": 107,
        "claim_business_id": "S107|G1",
        "feature_run_id": "FEATURE_RUN",
        "client_sk": 10,
        "contrat_sk": 20,
        "vehicle_sk": 30,
        "tiers_sk": 501,
        "client_claim_count_12m": 0,
        "days_since_previous_claim": pd.NA,
        "amount_vs_guarantee_median_ratio": 1.0,
        "amount_percentile_by_guarantee": 0.50,
        "high_amount_flag": False,
        "days_contract_start_to_claim": 400,
        "claim_before_contract_start_flag": False,
        "days_claim_to_declaration": 1,
        "tiers_repeat_client_count": 1,
        "client_tiers_pair_repeat_count": 1,
        "confidence_level": "HIGH",
    }])

    signals = compute_claim_business_rule_signals(features, signal_run_id="RULE_RUN")

    assert "TIERS_REPEATED_ACROSS_CLIENTS" not in set(signals["rule_code"])
    assert "CLIENT_TIERS_PAIR_REPEATED" not in set(signals["rule_code"])


def test_geo_recurrence_uses_prior_claims_only_in_same_zone():
    features = pd.DataFrame([
        {
            "claim_sk": 1, "claim_business_id": "S1|G1", "feature_run_id": "FEATURE_RUN",
            "claim_date": pd.Timestamp("2024-01-01"), "claim_geo_sk": 500,
            "client_claim_count_12m": 0, "days_since_previous_claim": pd.NA,
            "amount_vs_guarantee_median_ratio": 1.0, "amount_percentile_by_guarantee": 0.5,
            "high_amount_flag": False, "days_contract_start_to_claim": 400,
            "claim_before_contract_start_flag": False, "days_claim_to_declaration": 1,
            "confidence_level": "HIGH",
        },
        {
            "claim_sk": 2, "claim_business_id": "S2|G1", "feature_run_id": "FEATURE_RUN",
            "claim_date": pd.Timestamp("2024-02-01"), "claim_geo_sk": 500,
            "client_claim_count_12m": 0, "days_since_previous_claim": pd.NA,
            "amount_vs_guarantee_median_ratio": 1.0, "amount_percentile_by_guarantee": 0.5,
            "high_amount_flag": False, "days_contract_start_to_claim": 400,
            "claim_before_contract_start_flag": False, "days_claim_to_declaration": 1,
            "confidence_level": "HIGH",
        },
        {
            "claim_sk": 3, "claim_business_id": "S3|G1", "feature_run_id": "FEATURE_RUN",
            "claim_date": pd.Timestamp("2024-03-01"), "claim_geo_sk": 500,
            "client_claim_count_12m": 0, "days_since_previous_claim": pd.NA,
            "amount_vs_guarantee_median_ratio": 1.0, "amount_percentile_by_guarantee": 0.5,
            "high_amount_flag": False, "days_contract_start_to_claim": 400,
            "claim_before_contract_start_flag": False, "days_claim_to_declaration": 1,
            "confidence_level": "HIGH",
        },
        {
            "claim_sk": 4, "claim_business_id": "S4|G1", "feature_run_id": "FEATURE_RUN",
            "claim_date": pd.Timestamp("2024-04-01"), "claim_geo_sk": 500,
            "client_claim_count_12m": 0, "days_since_previous_claim": pd.NA,
            "amount_vs_guarantee_median_ratio": 1.0, "amount_percentile_by_guarantee": 0.5,
            "high_amount_flag": False, "days_contract_start_to_claim": 400,
            "claim_before_contract_start_flag": False, "days_claim_to_declaration": 1,
            "confidence_level": "HIGH",
        },
    ])

    signals = compute_claim_business_rule_signals(features, signal_run_id="RULE_RUN")

    # _geo_recurrence_rules is not wired into claim_business_rules_for_row:
    # on real data its fixed threshold of 3 fired on 98% of dossiers (median
    # 6 claims/zone over the full history, one dense zone alone >37000) --
    # not a concentration signal, just normal urban density. It stays
    # disabled pending a percentile-based recalibration (see its docstring).
    assert signals[signals["rule_family"] == "Geographie"].empty


def test_geo_recurrence_rules_function_still_works_if_called_directly():
    # The function itself is preserved (unused) for a future percentile-based
    # recalibration; this locks in that its internal logic still behaves,
    # even though nothing in the active pipeline calls it today.
    from etl.mart.compute_claim_business_rule_signals_v1_candidate import _geo_recurrence_rules

    row = pd.Series({
        "claim_sk": 4, "geo_claim_count_12m": 3, "geo_days_since_previous_claim": pd.NA,
        "confidence_level": "HIGH",
    })
    rules = _geo_recurrence_rules(row)
    assert {r["rule_code"] for r in rules} == {"GEO_CLAIMS_12M_HIGH"}
    assert rules[0]["candidate_points"] == 10


def test_client_rapid_accumulation_fires_on_third_claim_within_30_days():
    features = pd.DataFrame([
        {
            "claim_sk": 10, "claim_business_id": "S10|G1", "feature_run_id": "FEATURE_RUN",
            "claim_date": pd.Timestamp("2024-01-01"), "client_sk": 900,
            "client_claim_count_12m": 0, "days_since_previous_claim": pd.NA,
            "amount_vs_guarantee_median_ratio": 1.0, "amount_percentile_by_guarantee": 0.5,
            "high_amount_flag": False, "days_contract_start_to_claim": 400,
            "claim_before_contract_start_flag": False, "days_claim_to_declaration": 1,
            "confidence_level": "HIGH",
        },
        {
            "claim_sk": 11, "claim_business_id": "S11|G1", "feature_run_id": "FEATURE_RUN",
            "claim_date": pd.Timestamp("2024-01-10"), "client_sk": 900,
            "client_claim_count_12m": 0, "days_since_previous_claim": pd.NA,
            "amount_vs_guarantee_median_ratio": 1.0, "amount_percentile_by_guarantee": 0.5,
            "high_amount_flag": False, "days_contract_start_to_claim": 400,
            "claim_before_contract_start_flag": False, "days_claim_to_declaration": 1,
            "confidence_level": "HIGH",
        },
        {
            # Third claim for the same client within 30 days -> 2 priors in window.
            "claim_sk": 12, "claim_business_id": "S12|G1", "feature_run_id": "FEATURE_RUN",
            "claim_date": pd.Timestamp("2024-01-20"), "client_sk": 900,
            "client_claim_count_12m": 0, "days_since_previous_claim": pd.NA,
            "amount_vs_guarantee_median_ratio": 1.0, "amount_percentile_by_guarantee": 0.5,
            "high_amount_flag": False, "days_contract_start_to_claim": 400,
            "claim_before_contract_start_flag": False, "days_claim_to_declaration": 1,
            "confidence_level": "HIGH",
        },
    ])

    signals = compute_claim_business_rule_signals(features, signal_run_id="RULE_RUN")
    rows = signals[signals["rule_code"] == "CLIENT_CLAIMS_RAPID_ACCUMULATION"]

    assert set(rows["claim_sk"]) == {12}
    assert (rows["candidate_points"] == 15).all()
    assert (rows["rule_family"] == "Historique").all()


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


def test_enriched_recurrence_uses_prior_claims_only_and_ignores_zero_keys():
    features = pd.DataFrame([
        {
            "claim_sk": 10,
            "claim_business_id": "S10|G1",
            "feature_run_id": "FEATURE_RUN",
            "claim_date": "2024-01-01",
            "vehicle_sk": 100,
            "conducteur_sk": 500,
            "tiers_sk": 700,
            "client_sk": 900,
            "code_garantie": "G1",
            "confidence_level": "HIGH",
        },
        {
            "claim_sk": 11,
            "claim_business_id": "S11|G1",
            "feature_run_id": "FEATURE_RUN",
            "claim_date": "2024-01-01",
            "vehicle_sk": 100,
            "conducteur_sk": 500,
            "tiers_sk": 700,
            "client_sk": 900,
            "code_garantie": "G1",
            "confidence_level": "HIGH",
        },
        {
            "claim_sk": 12,
            "claim_business_id": "S12|G1",
            "feature_run_id": "FEATURE_RUN",
            "claim_date": "2024-01-20",
            "vehicle_sk": 100,
            "conducteur_sk": 500,
            "tiers_sk": 700,
            "client_sk": 900,
            "code_garantie": "G1",
            "confidence_level": "HIGH",
        },
        {
            "claim_sk": 13,
            "claim_business_id": "S13|G1",
            "feature_run_id": "FEATURE_RUN",
            "claim_date": "2024-02-01",
            "vehicle_sk": 0,
            "conducteur_sk": 0,
            "tiers_sk": 0,
            "client_sk": 0,
            "code_garantie": "G1",
            "confidence_level": "LOW",
        },
    ])

    enriched = enrich_features_for_business_rules(features)
    by_claim = enriched.set_index("claim_sk")

    assert by_claim.loc[10, "vehicle_claim_count_12m"] == 0
    assert by_claim.loc[11, "vehicle_claim_count_12m"] == 0
    assert by_claim.loc[12, "vehicle_claim_count_12m"] == 2
    assert by_claim.loc[12, "vehicle_days_since_previous_claim"] == 19
    assert by_claim.loc[13, "vehicle_claim_count_12m"] == 0
    assert by_claim.loc[13, "driver_claim_count_12m"] == 0
    assert pd.isna(by_claim.loc[13, "driver_days_since_previous_claim"])


def test_unknown_driver_key_never_produces_a_driver_recurrence_signal():
    # Trois sinistres non lies (vehicule/client/tiers/garantie tous distincts),
    # rapproches dans le temps, mais sans conducteur identifie (conducteur_sk=0).
    # Regression du bug ou un conducteur_sk fantome (numero_permis de repli
    # partage par des milliers de lignes) agregeait ces sinistres comme s'ils
    # provenaient du meme conducteur : ce cas ne doit jamais generer de signal
    # "Recurrence conducteur" ni "Sinistre conducteur precedent recent".
    base_fields = {
        "feature_run_id": "FEATURE_RUN",
        "confidence_level": "LOW",
        "client_claim_count_12m": 0,
        "days_since_previous_claim": pd.NA,
        "amount_vs_guarantee_median_ratio": 1.0,
        "amount_percentile_by_guarantee": 0.5,
        "high_amount_flag": False,
        "days_contract_start_to_claim": pd.NA,
        "claim_before_contract_start_flag": False,
        "days_claim_to_declaration": 1,
    }
    features = pd.DataFrame([
        {
            **base_fields,
            "claim_sk": 40,
            "claim_business_id": "S40|G1",
            "claim_date": "2024-01-01",
            "client_sk": 940,
            "vehicle_sk": 240,
            "conducteur_sk": 0,
            "tiers_sk": 840,
            "code_garantie": "G40",
        },
        {
            **base_fields,
            "claim_sk": 41,
            "claim_business_id": "S41|G1",
            "claim_date": "2024-01-10",
            "client_sk": 941,
            "vehicle_sk": 241,
            "conducteur_sk": 0,
            "tiers_sk": 841,
            "code_garantie": "G41",
        },
        {
            **base_fields,
            "claim_sk": 42,
            "claim_business_id": "S42|G1",
            "claim_date": "2024-01-20",
            "client_sk": 942,
            "vehicle_sk": 242,
            "conducteur_sk": 0,
            "tiers_sk": 842,
            "code_garantie": "G42",
        },
    ])

    signals = compute_claim_business_rule_signals(features, signal_run_id="RULE_RUN")

    assert "DRIVER_CLAIMS_12M_HIGH" not in set(signals["rule_code"])
    assert "DRIVER_RECENT_PREVIOUS_CLAIM" not in set(signals["rule_code"])


def test_degenerate_conducteur_sk_never_produces_a_driver_recurrence_signal():
    # Regression: dwh.dim_conducteur can assign a real, non-zero conducteur_sk
    # to a record with neither a name nor a permit number (e.g. sk=18 with
    # 19 892 unrelated claims attached on real data). Without excluding these
    # keys, unrelated claims missing driver identity look like "the same
    # recidivist driver". degenerate_conducteur_keys is how the caller (loaded
    # from dwh.dim_conducteur) flags such keys.
    base_fields = {
        "feature_run_id": "FEATURE_RUN",
        "confidence_level": "LOW",
        "client_claim_count_12m": 0,
        "days_since_previous_claim": pd.NA,
        "amount_vs_guarantee_median_ratio": 1.0,
        "amount_percentile_by_guarantee": 0.5,
        "high_amount_flag": False,
        "days_contract_start_to_claim": pd.NA,
        "claim_before_contract_start_flag": False,
        "days_claim_to_declaration": 1,
    }
    features = pd.DataFrame([
        {
            **base_fields,
            "claim_sk": 50,
            "claim_business_id": "S50|G1",
            "claim_date": "2024-01-01",
            "client_sk": 950,
            "vehicle_sk": 250,
            "conducteur_sk": 18,
            "tiers_sk": 850,
            "code_garantie": "G50",
        },
        {
            **base_fields,
            "claim_sk": 51,
            "claim_business_id": "S51|G1",
            "claim_date": "2024-01-10",
            "client_sk": 951,
            "vehicle_sk": 251,
            "conducteur_sk": 18,
            "tiers_sk": 851,
            "code_garantie": "G51",
        },
        {
            **base_fields,
            "claim_sk": 52,
            "claim_business_id": "S52|G1",
            "claim_date": "2024-01-20",
            "client_sk": 952,
            "vehicle_sk": 252,
            "conducteur_sk": 18,
            "tiers_sk": 852,
            "code_garantie": "G52",
        },
    ])

    signals = compute_claim_business_rule_signals(
        features, signal_run_id="RULE_RUN", degenerate_conducteur_keys={18},
    )

    assert "DRIVER_CLAIMS_12M_HIGH" not in set(signals["rule_code"])
    assert "DRIVER_RECENT_PREVIOUS_CLAIM" not in set(signals["rule_code"])


def test_real_repeated_conducteur_sk_still_fires_when_not_degenerate():
    # A genuinely identified repeat driver (not in degenerate_conducteur_keys)
    # must keep firing -- the fix must not blunt the legitimate 86% of cases.
    base_fields = {
        "feature_run_id": "FEATURE_RUN",
        "confidence_level": "LOW",
        "client_claim_count_12m": 0,
        "days_since_previous_claim": pd.NA,
        "amount_vs_guarantee_median_ratio": 1.0,
        "amount_percentile_by_guarantee": 0.5,
        "high_amount_flag": False,
        "days_contract_start_to_claim": pd.NA,
        "claim_before_contract_start_flag": False,
        "days_claim_to_declaration": 1,
    }
    features = pd.DataFrame([
        {
            **base_fields,
            "claim_sk": 60,
            "claim_business_id": "S60|G1",
            "claim_date": "2024-01-01",
            "client_sk": 960,
            "vehicle_sk": 260,
            "conducteur_sk": 700,
            "tiers_sk": 860,
            "code_garantie": "G60",
        },
        {
            **base_fields,
            "claim_sk": 61,
            "claim_business_id": "S61|G1",
            "claim_date": "2024-01-10",
            "client_sk": 961,
            "vehicle_sk": 261,
            "conducteur_sk": 700,
            "tiers_sk": 861,
            "code_garantie": "G61",
        },
    ])

    signals = compute_claim_business_rule_signals(
        features, signal_run_id="RULE_RUN", degenerate_conducteur_keys={18},
    )

    assert "DRIVER_RECENT_PREVIOUS_CLAIM" in set(signals["rule_code"])


def test_overloaded_conducteur_sk_excluded_by_claim_volume_even_with_a_real_looking_name():
    # Regression: some conducteur_sk carry a non-null nom_conducteur/numero_permis
    # that is itself contamination ("EN STATIONNEMENT", "SANS CONDUCTEUR", and at
    # least 6 misspelled variants) rather than a real identity. Those can't be
    # caught by the null/null check, so DRIVER_KEY_MAX_PLAUSIBLE_CLAIMS excludes
    # any conducteur_sk linked to more claims than a real individual plausibly
    # generates in one run -- without needing to know the exact garbage text.
    base_fields = {
        "feature_run_id": "FEATURE_RUN",
        "confidence_level": "LOW",
        "client_claim_count_12m": 0,
        "days_since_previous_claim": pd.NA,
        "amount_vs_guarantee_median_ratio": 1.0,
        "amount_percentile_by_guarantee": 0.5,
        "high_amount_flag": False,
        "days_contract_start_to_claim": pd.NA,
        "claim_before_contract_start_flag": False,
        "days_claim_to_declaration": 1,
    }
    overloaded_rows = [
        {
            **base_fields,
            "claim_sk": 1000 + i,
            "claim_business_id": f"S{1000 + i}|G1",
            "claim_date": f"2024-01-{(i % 28) + 1:02d}",
            "client_sk": 2000 + i,
            "vehicle_sk": 3000 + i,
            "conducteur_sk": 999,
            "tiers_sk": 4000 + i,
            "code_garantie": f"G{1000 + i}",
        }
        for i in range(25)
    ]
    real_driver_rows = [
        {
            **base_fields,
            "claim_sk": 70,
            "claim_business_id": "S70|G1",
            "claim_date": "2024-01-01",
            "client_sk": 970,
            "vehicle_sk": 270,
            "conducteur_sk": 700,
            "tiers_sk": 870,
            "code_garantie": "G70",
        },
        {
            **base_fields,
            "claim_sk": 71,
            "claim_business_id": "S71|G1",
            "claim_date": "2024-01-10",
            "client_sk": 971,
            "vehicle_sk": 271,
            "conducteur_sk": 700,
            "tiers_sk": 871,
            "code_garantie": "G71",
        },
    ]
    features = pd.DataFrame(overloaded_rows + real_driver_rows)

    signals = compute_claim_business_rule_signals(features, signal_run_id="RULE_RUN")

    overloaded_claim_sks = {row["claim_sk"] for row in overloaded_rows}
    driver_signals = signals[signals["rule_code"].isin(["DRIVER_CLAIMS_12M_HIGH", "DRIVER_RECENT_PREVIOUS_CLAIM"])]
    assert set(driver_signals["claim_sk"]).isdisjoint(overloaded_claim_sks)
    assert 71 in set(driver_signals["claim_sk"])


def test_vehicle_driver_third_party_and_guarantee_rules_are_candidate_signals():
    features = pd.DataFrame([
        {
            "claim_sk": 20,
            "claim_business_id": "S20|G1",
            "feature_run_id": "FEATURE_RUN",
            "claim_date": "2024-01-01",
            "client_sk": 910,
            "contrat_sk": 1,
            "vehicle_sk": 200,
            "conducteur_sk": 600,
            "tiers_sk": 800,
            "code_garantie": "G2",
            "confidence_level": "HIGH",
            "client_claim_count_12m": 0,
            "days_since_previous_claim": pd.NA,
            "amount_vs_guarantee_median_ratio": 1.0,
            "amount_percentile_by_guarantee": 0.5,
            "high_amount_flag": False,
            "days_contract_start_to_claim": pd.NA,
            "claim_before_contract_start_flag": False,
            "days_claim_to_declaration": 1,
        },
        {
            "claim_sk": 21,
            "claim_business_id": "S21|G1",
            "feature_run_id": "FEATURE_RUN",
            "claim_date": "2024-02-01",
            "client_sk": 910,
            "contrat_sk": 1,
            "vehicle_sk": 200,
            "conducteur_sk": 600,
            "tiers_sk": 800,
            "code_garantie": "G2",
            "confidence_level": "HIGH",
            "client_claim_count_12m": 0,
            "days_since_previous_claim": pd.NA,
            "amount_vs_guarantee_median_ratio": 1.0,
            "amount_percentile_by_guarantee": 0.5,
            "high_amount_flag": False,
            "days_contract_start_to_claim": pd.NA,
            "claim_before_contract_start_flag": False,
            "days_claim_to_declaration": 1,
        },
        {
            "claim_sk": 22,
            "claim_business_id": "S22|G1",
            "feature_run_id": "FEATURE_RUN",
            "claim_date": "2024-02-20",
            "client_sk": 910,
            "contrat_sk": 1,
            "vehicle_sk": 200,
            "conducteur_sk": 600,
            "tiers_sk": 800,
            "code_garantie": "G2",
            "confidence_level": "HIGH",
            "client_claim_count_12m": 0,
            "days_since_previous_claim": pd.NA,
            "amount_vs_guarantee_median_ratio": 1.0,
            "amount_percentile_by_guarantee": 0.5,
            "high_amount_flag": False,
            "days_contract_start_to_claim": pd.NA,
            "claim_before_contract_start_flag": False,
            "days_claim_to_declaration": 1,
        },
    ])

    signals = compute_claim_business_rule_signals(features, signal_run_id="RULE_RUN")
    claim_22_codes = set(signals.loc[signals["claim_sk"].eq(22), "rule_code"])

    assert {
        "VEHICLE_CLAIMS_12M_MEDIUM",
        "VEHICLE_RECENT_PREVIOUS_CLAIM",
        "DRIVER_CLAIMS_12M_HIGH",
        "DRIVER_RECENT_PREVIOUS_CLAIM",
        "THIRD_PARTY_CLAIMS_12M_HIGH",
        "THIRD_PARTY_RECENT_PREVIOUS_CLAIM",
        "CLIENT_GUARANTEE_REPEAT_12M_MEDIUM",
        "CLIENT_GUARANTEE_RECENT_PREVIOUS_CLAIM",
    }.issubset(claim_22_codes)
    assert validate_business_rule_signals(signals)["accusatory_wording_rows"] == 0
