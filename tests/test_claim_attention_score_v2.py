import pandas as pd

from etl.mart.compute_claim_attention_score_v2_candidate import (
    SCORE_VERSION,
    compute_claim_attention_score_v2,
)


def _features(confidence="LOW"):
    return pd.DataFrame([
        {
            "claim_sk": 1,
            "claim_business_id": "S1|G1",
            "smart_feature_run_id": "SMART_RUN",
            "source_as_of_date": "2026-07-10",
            "input_hash": "abc",
            "declaration_delay_days": 45,
            "claim_before_contract_start_flag": True,
            "client_claim_count_12m": 3,
            "amount_ratio_to_median": 2.0,
            "comparison_reliability": "DISPLAYABLE",
            "critical_document_missing_count": 1,
            "data_quality_level": "LOW",
            "confidence_level": confidence,
        },
        {
            "claim_sk": 2,
            "claim_business_id": "S2|G1",
            "smart_feature_run_id": "SMART_RUN",
            "source_as_of_date": "2026-07-10",
            "input_hash": "def",
            "declaration_delay_days": 1,
            "claim_before_contract_start_flag": False,
            "client_claim_count_12m": 0,
            "amount_ratio_to_median": pd.NA,
            "comparison_reliability": "INSUFFICIENT_SAMPLE",
            "critical_document_missing_count": 0,
            "data_quality_level": "HIGH",
            "confidence_level": "HIGH",
        },
    ])


def test_score_v2_outputs_scores_and_explanatory_details():
    scores, details = compute_claim_attention_score_v2(_features(), score_run_id="SCORE_RUN")
    by_claim = scores.set_index("claim_sk")

    assert by_claim.loc[1, "score_version"] == SCORE_VERSION
    assert by_claim.loc[1, "attention_score"] > by_claim.loc[2, "attention_score"]
    assert by_claim.loc[1, "priority_rank"] == 1
    assert by_claim.loc[2, "attention_level"] == "Analyse standard"
    assert details["business_explanation"].str.len().gt(0).all()
    assert details["score_run_id"].eq("SCORE_RUN").all()
    assert {"raw_points", "awarded_points", "family_cap", "rule_version", "rule_catalog_hash", "input_hash"}.issubset(details.columns)


def test_family_caps_and_global_cap_are_applied():
    scores, details = compute_claim_attention_score_v2(_features())
    # CHR_CLAIM_BEFORE_CONTRACT_START was reclassified as a DATA_QUALITY signal
    # (0 points, never accuses the dossier — a claim before contract start is
    # almost always a contractual-data-entry inconsistency, not a fraud clue).
    # CHRONOLOGY now only carries CHR_DECLARATION_DELAY_HIGH (12 pts), so the
    # 25-point family cap is no longer exercised by this fixture.
    chronology_points = details[(details["claim_sk"].eq(1)) & (details["rule_family"].eq("CHRONOLOGY"))]["awarded_points"].sum()

    assert chronology_points == 12
    assert scores["attention_score"].between(0, 100).all()
    assert scores.set_index("claim_sk").loc[1, "main_reason_1"] in set(details[details["awarded_points"].gt(0)]["business_label"])


def test_golden_dossier_exact_score_level_and_top_reasons():
    """Golden dataset: any silent change of thresholds, points or caps must break this test."""
    scores, details = compute_claim_attention_score_v2(_features(), score_run_id="GOLDEN_RUN")
    by_claim = scores.set_index("claim_sk")

    # Claim 1: CHRONOLOGY 12 (CLAIM_BEFORE_CONTRACT_START moved to DATA_QUALITY,
    # 0 pts), HISTORY 12, COMPARISON 15, COMPLETENESS 15 = 54.
    assert by_claim.loc[1, "attention_score"] == 54
    assert by_claim.loc[1, "attention_level"] == "Examen renforce suggere"
    assert by_claim.loc[1, "main_reason_1"] == "Montant superieur aux dossiers comparables"
    assert by_claim.loc[1, "main_reason_2"] == "Piece critique manquante"
    assert by_claim.loc[1, "main_reason_3"] == "Delai de declaration eleve"

    # Claim 2: no rule fires, clean data.
    assert by_claim.loc[2, "attention_score"] == 0
    assert by_claim.loc[2, "attention_level"] == "Analyse standard"
    assert pd.isna(by_claim.loc[2, "main_reason_1"])

    # CLAIM_BEFORE_CONTRACT_START fires (claim 1) but never awards points or
    # ranks as a reason: it only documents a contractual-data-quality limit.
    contract_start_detail = details[details["claim_sk"].eq(1) & details["rule_code"].eq("CHR_CLAIM_BEFORE_CONTRACT_START")]
    assert contract_start_detail["rule_family"].eq("DATA_QUALITY").all()
    assert contract_start_detail["raw_points"].eq(0).all()
    assert contract_start_detail["awarded_points"].eq(0).all()

    # CHR_DECLARATION_DELAY_HIGH is alone in CHRONOLOGY now, so it is awarded
    # in full (no capping needed since 12 < the 25-point family cap).
    delay_detail = details[details["claim_sk"].eq(1) & details["rule_code"].eq("CHR_DECLARATION_DELAY_HIGH")]
    assert delay_detail["raw_points"].eq(12).all()
    assert delay_detail["awarded_points"].eq(12).all()


def test_pd_na_confidence_level_does_not_fail():
    scores, _ = compute_claim_attention_score_v2(_features(confidence=pd.NA))
    assert scores.set_index("claim_sk").loc[1, "confidence_level"] == "LOW"


def test_ml_is_not_required_for_v2_score():
    scores, details = compute_claim_attention_score_v2(_features())
    assert "ml" not in " ".join(details["rule_code"].str.lower().tolist())
    assert not scores.empty
