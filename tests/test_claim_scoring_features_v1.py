from datetime import date

import pandas as pd

from etl.mart.compute_claim_scoring_features_v1 import (
    compute_amount_features,
    compute_claim_scoring_features,
    compute_client_recurrence,
    compute_recent_avenant_features,
    date_key_to_timestamp,
    is_missing_key,
)


def test_date_key_parser_handles_zero_and_invalid_values():
    assert pd.Timestamp("2024-01-31") == date_key_to_timestamp(20240131)
    assert pd.isna(date_key_to_timestamp(0))
    assert pd.isna(date_key_to_timestamp("0"))
    assert pd.isna(date_key_to_timestamp(20240231))


def test_zero_is_missing_dwh_key():
    assert is_missing_key(0)
    assert is_missing_key("0")
    assert is_missing_key(None)
    assert not is_missing_key(42)


def test_client_recurrence_uses_prior_claim_dates_only():
    df = pd.DataFrame({
        "claim_sk": [1, 2, 3, 4],
        "client_sk": [10, 10, 10, 10],
        "claim_date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-10", "2025-01-05"]),
    })

    result = compute_client_recurrence(df)

    assert result.loc[0, "client_claim_count_total"] == 0
    assert result.loc[1, "client_claim_count_total"] == 0
    assert result.loc[2, "client_claim_count_total"] == 2
    assert result.loc[2, "days_since_previous_claim"] == 9
    assert result.loc[3, "client_claim_count_12m"] == 1


def test_amount_features_flag_high_amount_by_guarantee_distribution():
    df = pd.DataFrame({
        "code_garantie": ["A", "A", "A", "A"],
        "claim_amount": [100.0, 100.0, 100.0, 1000.0],
    })

    result = compute_amount_features(df)

    assert result.loc[3, "amount_vs_guarantee_median_ratio"] == 10.0
    assert result.loc[3, "high_amount_flag"]
    assert not result.loc[0, "high_amount_flag"]


def test_full_feature_build_counts_zero_keys_as_missing_and_confidence_low():
    claims = pd.DataFrame({
        "fact_sinistre_sk": [1],
        "numero_sinistre": ["S1"],
        "code_garantie": ["G1"],
        "sinistre_garantie_key": ["S1|G1"],
        "client_sk": [0],
        "contrat_sk": [0],
        "vehicule_sk": [0],
        "garantie_sk": [0],
        "conducteur_sk": [0],
        "tiers_sk": [0],
        "camtier_sk": [0],
        "geo_sinistre_sk": [0],
        "date_survenance_sk": [20240101],
        "date_declaration_sk": [20240110],
        "montant_evaluation": [500.0],
    })

    result = compute_claim_scoring_features(claims, run_id="TEST", as_of_date=date(2024, 2, 1))

    assert result.loc[0, "missing_client_flag"]
    assert result.loc[0, "missing_contract_flag"]
    assert result.loc[0, "missing_guarantee_flag"]
    assert result.loc[0, "missing_keys_count"] == 3
    assert result.loc[0, "unknown_dimensions_count"] == 7
    assert result.loc[0, "confidence_level"] == "LOW"
    assert result.loc[0, "days_claim_to_declaration"] == 9


def test_contract_start_features_join_on_contract_without_future_leakage():
    claims = pd.DataFrame({
        "fact_sinistre_sk": [1],
        "numero_sinistre": ["S1"],
        "code_garantie": ["G1"],
        "sinistre_garantie_key": ["S1|G1"],
        "client_sk": [1],
        "contrat_sk": [77],
        "vehicule_sk": [0],
        "garantie_sk": [3],
        "conducteur_sk": [0],
        "tiers_sk": [0],
        "camtier_sk": [0],
        "geo_sinistre_sk": [0],
        "date_survenance_sk": [20240115],
        "date_declaration_sk": [20240120],
        "montant_evaluation": [500.0],
    })
    contracts = pd.DataFrame({
        "contrat_sk": [77, 77],
        "date_debut_contrat_sk": [20240101, 20240201],
    })

    result = compute_claim_scoring_features(
        claims,
        contracts,
        run_id="TEST",
        as_of_date=date(2024, 2, 1),
    )

    assert result.loc[0, "contract_start_date_sk"] == 20240101
    assert result.loc[0, "days_contract_start_to_claim"] == 14
    assert not result.loc[0, "claim_before_contract_start_flag"]


def test_recent_avenant_flag_only_counts_genuine_amendments_before_claim():
    df = pd.DataFrame({
        "contrat_sk": [1, 2, 3],
        "claim_date": pd.to_datetime(["2024-06-01", "2024-06-01", "2024-06-01"]),
    })
    contracts = pd.DataFrame({
        "contrat_sk": [1, 1, 2, 3],
        # Contract 1: original subscription (est_avenant=False, ignored) then
        # a genuine avenant 30 days before the claim -> recent.
        # Contract 2: a genuine avenant, but it happened AFTER the claim date
        # (future leakage) -> must not count, no other avenant exists.
        # Contract 3: no avenant rows at all -> stays NA/False.
        "est_avenant": [False, True, True, False],
        "date_derniere_operation_sk": [20230101, 20240502, 20240701, 20230101],
    })

    result = compute_recent_avenant_features(df, contracts, window_days=90)

    assert result.loc[0, "days_since_last_avenant"] == 30
    assert result.loc[0, "recent_contract_change_flag"]

    assert pd.isna(result.loc[1, "days_since_last_avenant"])
    assert not result.loc[1, "recent_contract_change_flag"]

    assert pd.isna(result.loc[2, "days_since_last_avenant"])
    assert not result.loc[2, "recent_contract_change_flag"]


def test_recent_avenant_flag_respects_window_and_wires_through_full_pipeline():
    claims = pd.DataFrame({
        "fact_sinistre_sk": [1],
        "numero_sinistre": ["S1"],
        "code_garantie": ["G1"],
        "sinistre_garantie_key": ["S1|G1"],
        "client_sk": [1],
        "contrat_sk": [77],
        "vehicule_sk": [0],
        "garantie_sk": [3],
        "conducteur_sk": [0],
        "tiers_sk": [0],
        "camtier_sk": [0],
        "geo_sinistre_sk": [0],
        "date_survenance_sk": [20240601],
        "date_declaration_sk": [20240605],
        "montant_evaluation": [500.0],
    })
    contracts = pd.DataFrame({
        "contrat_sk": [77, 77],
        "date_debut_contrat_sk": [20200101, 20200101],
        "est_avenant": [False, True],
        "date_derniere_operation_sk": [20200101, 20240201],
    })

    result = compute_claim_scoring_features(claims, contracts, run_id="TEST", as_of_date=date(2024, 6, 10))

    # 121 days between the avenant (2024-02-01) and the claim (2024-06-01):
    # outside the 90-day "recent" window, so the flag must not fire even
    # though days_since_last_avenant is populated.
    assert result.loc[0, "days_since_last_avenant"] == 121
    assert not result.loc[0, "recent_contract_change_flag"]


def test_rapid_declaration_after_subscription_uses_declaration_not_claim_date():
    claims = pd.DataFrame({
        "fact_sinistre_sk": [1, 2],
        "numero_sinistre": ["S1", "S2"],
        "code_garantie": ["G1", "G1"],
        "sinistre_garantie_key": ["S1|G1", "S2|G1"],
        "client_sk": [1, 1],
        "contrat_sk": [77, 78],
        "vehicule_sk": [0, 0],
        "garantie_sk": [3, 3],
        "conducteur_sk": [0, 0],
        "tiers_sk": [0, 0],
        "camtier_sk": [0, 0],
        "geo_sinistre_sk": [0, 0],
        # Claim 1: declaration lands 20 days after subscription -> rapid.
        # Claim 2: declaration lands 121 days after subscription -> not rapid.
        "date_survenance_sk": [20240115, 20240301],
        "date_declaration_sk": [20240121, 20240501],
        "montant_evaluation": [500.0, 500.0],
    })
    contracts = pd.DataFrame({
        "contrat_sk": [77, 78],
        "date_debut_contrat_sk": [20240101, 20240101],
    })

    result = compute_claim_scoring_features(claims, contracts, run_id="TEST", as_of_date=date(2024, 6, 1))
    by_claim = result.set_index("claim_sk")

    assert by_claim.loc[1, "days_contract_start_to_declaration"] == 20
    assert by_claim.loc[1, "rapid_declaration_after_subscription_flag"]

    assert by_claim.loc[2, "days_contract_start_to_declaration"] == 121
    assert not by_claim.loc[2, "rapid_declaration_after_subscription_flag"]


def test_tiers_identity_incomplete_flag_only_fires_when_a_tiers_is_linked():
    claims = pd.DataFrame({
        "fact_sinistre_sk": [1, 2, 3],
        "numero_sinistre": ["S1", "S2", "S3"],
        "code_garantie": ["G1", "G1", "G1"],
        "sinistre_garantie_key": ["S1|G1", "S2|G1", "S3|G1"],
        "client_sk": [1, 1, 1],
        "contrat_sk": [77, 77, 77],
        "vehicule_sk": [0, 0, 0],
        "garantie_sk": [3, 3, 3],
        "conducteur_sk": [0, 0, 0],
        # Claim 1: tiers linked, but its nom_tiers is blank -> incomplete.
        # Claim 2: tiers linked with a real name -> complete, no flag.
        # Claim 3: no tiers linked at all (tiers_sk=0) -> not applicable.
        "tiers_sk": [501, 502, 0],
        "camtier_sk": [0, 0, 0],
        "geo_sinistre_sk": [0, 0, 0],
        "date_survenance_sk": [20240115, 20240115, 20240115],
        "date_declaration_sk": [20240116, 20240116, 20240116],
        "montant_evaluation": [500.0, 500.0, 500.0],
    })
    tiers = pd.DataFrame({
        "tiers_sk": [501, 502],
        "nom_tiers": ["", "Dupont"],
    })

    result = compute_claim_scoring_features(claims, df_tiers=tiers, run_id="TEST", as_of_date=date(2024, 2, 1))
    by_claim = result.set_index("claim_sk")

    assert by_claim.loc[1, "tiers_identity_incomplete_flag"]
    assert not by_claim.loc[2, "tiers_identity_incomplete_flag"]
    assert not by_claim.loc[3, "tiers_identity_incomplete_flag"]
