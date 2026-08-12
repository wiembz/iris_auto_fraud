from pathlib import Path

import pandas as pd

from etl.mart.compute_claim_attention_dossier_v2_candidate import (
    AGGREGATION_VERSION,
    aggregate_claim_attention_dossier_v2,
    derive_claim_root_id,
)
from etl.mart.validate_claim_attention_dossier_v2_readonly import build_dossier_validation_reports


def _guarantee_scores():
    return pd.DataFrame([
        {
            "claim_sk": 1,
            "claim_business_id": "SIN-1|RCM",
            "attention_score": 40,
            "attention_level": "Points a verifier",
            "confidence_level": "MEDIUM",
            "main_reason_1": "Delai de declaration eleve",
            "main_reason_2": None,
            "main_reason_3": None,
            "score_version": "IRIS_CLAIM_ATTENTION_V2_CANDIDATE",
            "score_run_id": "SCORE_RUN",
        },
        {
            "claim_sk": 2,
            "claim_business_id": "SIN-1|IDA",
            "attention_score": 15,
            "attention_level": "Analyse standard",
            "confidence_level": "HIGH",
            "main_reason_1": "Montant superieur aux dossiers comparables",
            "main_reason_2": None,
            "main_reason_3": None,
            "score_version": "IRIS_CLAIM_ATTENTION_V2_CANDIDATE",
            "score_run_id": "SCORE_RUN",
        },
        {
            "claim_sk": 3,
            "claim_business_id": "SIN-2|BG",
            "attention_score": 52,
            "attention_level": "Examen renforce suggere",
            "confidence_level": "LOW",
            "main_reason_1": "Historique client dense sur 12 mois",
            "main_reason_2": None,
            "main_reason_3": None,
            "score_version": "IRIS_CLAIM_ATTENTION_V2_CANDIDATE",
            "score_run_id": "SCORE_RUN",
        },
    ])


def _guarantee_details():
    return pd.DataFrame([
        {
            "claim_sk": 1,
            "claim_business_id": "SIN-1|RCM",
            "score_run_id": "SCORE_RUN",
            "rule_code": "CHR_DECLARATION_DELAY_HIGH",
            "rule_family": "CHRONOLOGY",
            "awarded_points": 12,
            "business_label": "Delai de declaration eleve",
            "business_explanation": "Le delai peut justifier une verification complementaire.",
        },
        {
            "claim_sk": 2,
            "claim_business_id": "SIN-1|IDA",
            "score_run_id": "SCORE_RUN",
            "rule_code": "COMP_AMOUNT_ABOVE_SIMILAR_MEDIAN",
            "rule_family": "COMPARISON",
            "awarded_points": 15,
            "business_label": "Montant superieur aux dossiers comparables",
            "business_explanation": "Le montant est superieur a une reference comparable.",
        },
        {
            "claim_sk": 2,
            "claim_business_id": "SIN-1|IDA",
            "score_run_id": "SCORE_RUN",
            "rule_code": "CHR_DECLARATION_DELAY_HIGH",
            "rule_family": "CHRONOLOGY",
            "awarded_points": 12,
            "business_label": "Delai de declaration eleve",
            "business_explanation": "Le delai peut justifier une verification complementaire.",
        },
    ])


def _v1_scores():
    return pd.DataFrame([
        {
            "claim_sk": 1,
            "claim_business_id": "SIN-1|RCM",
            "attention_score_v1": 20,
            "attention_level_v1": "Analyse standard",
            "confidence_level_v1": "MEDIUM",
            "score_version_v1": "IRIS_CLAIM_ATTENTION_HYBRID_V1_CANDIDATE",
            "score_run_id_v1": "V1_RUN",
        },
        {
            "claim_sk": 2,
            "claim_business_id": "SIN-1|IDA",
            "attention_score_v1": 30,
            "attention_level_v1": "Points a verifier",
            "confidence_level_v1": "MEDIUM",
            "score_version_v1": "IRIS_CLAIM_ATTENTION_HYBRID_V1_CANDIDATE",
            "score_run_id_v1": "V1_RUN",
        },
    ])


def test_derive_claim_root_id_keeps_quality_flags():
    assert derive_claim_root_id("SIN-1|RCM") == ("SIN-1", "PIPE_SEPARATED_ROOT")
    assert derive_claim_root_id("SIN-2") == ("SIN-2", "NO_SEPARATOR_USED_AS_ROOT")
    assert derive_claim_root_id(None) == ("", "MISSING_BUSINESS_ID")


def test_dossier_aggregation_uses_max_score_not_sum_and_keeps_guarantees():
    dossier, details = aggregate_claim_attention_dossier_v2(_guarantee_scores(), _guarantee_details(), aggregation_run_id="DOSSIER_RUN")
    by_root = dossier.set_index("claim_root_id")

    assert by_root.loc["SIN-1", "dossier_attention_score"] == 40
    assert by_root.loc["SIN-1", "dossier_attention_score"] != 55
    assert by_root.loc["SIN-1", "guarantee_row_count"] == 2
    assert by_root.loc["SIN-1", "guarantee_codes"] == "IDA,RCM"
    assert by_root.loc["SIN-1", "distinct_rule_count"] == 2
    assert by_root.loc["SIN-1", "aggregation_version"] == AGGREGATION_VERSION
    assert details["claim_root_id"].eq("SIN-1").sum() == 3


def test_dossier_reasons_are_deduplicated_and_ordered_by_points():
    dossier, _ = aggregate_claim_attention_dossier_v2(_guarantee_scores(), _guarantee_details(), aggregation_run_id="DOSSIER_RUN")
    row = dossier.set_index("claim_root_id").loc["SIN-1"]

    assert row["main_reason_1"] == "Montant superieur aux dossiers comparables"
    assert row["main_reason_2"] == "Delai de declaration eleve"
    assert row[["main_reason_1", "main_reason_2", "main_reason_3"]].dropna().tolist().count("Delai de declaration eleve") == 1


def test_dossier_validation_reports_cover_expected_outputs():
    reports = build_dossier_validation_reports(
        _guarantee_scores(),
        _guarantee_details(),
        _v1_scores(),
        aggregation_run_id="DOSSIER_RUN",
        sample_size=10,
    )

    expected = {
        "claim_dossier_v2_load_summary.csv",
        "claim_dossier_v2_validation_summary.csv",
        "claim_dossier_v2_score_distribution.csv",
        "claim_dossier_v2_attention_level_distribution.csv",
        "claim_dossier_v2_confidence_distribution.csv",
        "claim_dossier_v2_guarantee_count_distribution.csv",
        "claim_dossier_v2_aggregation_change_summary.csv",
        "claim_dossier_v2_v1_v2_comparison.csv",
        "claim_dossier_v2_v1_v2_level_transition.csv",
        "claim_dossier_v2_contradictory_motifs.csv",
        "claim_dossier_v2_business_validation_sample.csv",
    }
    assert expected.issubset(reports)
    assert reports["claim_dossier_v2_load_summary.csv"].iloc[0]["claim_root_rows"] == 2
    assert reports["claim_dossier_v2_validation_summary.csv"].iloc[0]["duplicate_claim_root_rows"] == 0
    assert not reports["claim_dossier_v2_business_validation_sample.csv"].empty


def test_dossier_scripts_do_not_contain_postgresql_write_operations():
    for path in [
        Path("etl/mart/compute_claim_attention_dossier_v2_candidate.py"),
        Path("etl/mart/validate_claim_attention_dossier_v2_readonly.py"),
    ]:
        script = path.read_text(encoding="utf-8").lower()
        forbidden = [".to_sql(", " insert ", " update ", " delete ", " alter ", " drop ", " create table", " truncate "]
        assert not any(fragment in script for fragment in forbidden)
