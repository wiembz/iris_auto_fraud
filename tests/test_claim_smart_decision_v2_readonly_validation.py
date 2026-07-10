from pathlib import Path

import pandas as pd

from etl.mart.validate_claim_smart_decision_v2_readonly import (
    build_validation_reports,
)


def _source_features():
    return pd.DataFrame(
        [
            {"claim_sk": 1, "claim_business_id": "S1|G1"},
            {"claim_sk": 2, "claim_business_id": "S2|G1"},
            {"claim_sk": 3, "claim_business_id": "S3|G2"},
        ]
    )


def _smart_features():
    return pd.DataFrame(
        [
            {
                "claim_sk": 1,
                "history_evaluable_flag": True,
                "chronology_evaluable_flag": True,
                "document_completeness_evaluable_flag": True,
                "data_quality_evaluable_flag": True,
                "geo_evaluable_flag": False,
                "comparison_reliability": "DISPLAYABLE",
                "comparison_status_reason": "DISPLAYABLE",
            },
            {
                "claim_sk": 2,
                "history_evaluable_flag": True,
                "chronology_evaluable_flag": False,
                "document_completeness_evaluable_flag": True,
                "data_quality_evaluable_flag": True,
                "geo_evaluable_flag": False,
                "comparison_reliability": "INSUFFICIENT_SAMPLE",
                "comparison_status_reason": "INSUFFICIENT_SAMPLE",
            },
            {
                "claim_sk": 3,
                "history_evaluable_flag": False,
                "chronology_evaluable_flag": False,
                "document_completeness_evaluable_flag": False,
                "data_quality_evaluable_flag": False,
                "geo_evaluable_flag": False,
                "comparison_reliability": "NOT_AVAILABLE",
                "comparison_status_reason": "MISSING_COHORT_ATTRIBUTES",
            },
        ]
    )


def _scores_v2():
    return pd.DataFrame(
        [
            {
                "claim_sk": 1,
                "claim_business_id": "S1|G1",
                "attention_score": 55,
                "attention_level": "Examen renforce suggere",
                "confidence_level": "HIGH",
                "score_version": "IRIS_CLAIM_ATTENTION_V2_CANDIDATE",
                "score_run_id": "V2_RUN",
            },
            {
                "claim_sk": 2,
                "claim_business_id": "S2|G1",
                "attention_score": 25,
                "attention_level": "Points a verifier",
                "confidence_level": "MEDIUM",
                "score_version": "IRIS_CLAIM_ATTENTION_V2_CANDIDATE",
                "score_run_id": "V2_RUN",
            },
            {
                "claim_sk": 3,
                "claim_business_id": "S3|G2",
                "attention_score": 0,
                "attention_level": "Analyse standard",
                "confidence_level": "NOT_EVALUABLE",
                "score_version": "IRIS_CLAIM_ATTENTION_V2_CANDIDATE",
                "score_run_id": "V2_RUN",
            },
        ]
    )


def _details_v2():
    return pd.DataFrame(
        [
            {
                "claim_sk": 1,
                "rule_family": "CHRONOLOGY",
                "rule_code": "RULE_DELAY",
                "raw_points": 30,
                "awarded_points": 25,
                "business_label": "Chronologie a verifier",
                "business_explanation": "Le delai necessite une verification complementaire.",
            },
            {
                "claim_sk": 1,
                "rule_family": "HISTORY",
                "rule_code": "RULE_HISTORY",
                "raw_points": 30,
                "awarded_points": 30,
                "business_label": "Historique recent dense",
                "business_explanation": "Plusieurs dossiers recents sont observes.",
            },
            {
                "claim_sk": 2,
                "rule_family": "DATA_QUALITY",
                "rule_code": "RULE_QUALITY",
                "raw_points": 0,
                "awarded_points": 0,
                "business_label": "Confiance des donnees a completer",
                "business_explanation": "Certaines donnees limitent l'interpretation.",
            },
        ]
    )


def _v1_scores():
    return pd.DataFrame(
        [
            {
                "claim_sk": 1,
                "claim_business_id": "S1|G1",
                "attention_score_v1": 45,
                "attention_level_v1": "Points a verifier",
                "confidence_level_v1": "HIGH",
            },
            {
                "claim_sk": 2,
                "claim_business_id": "S2|G1",
                "attention_score_v1": 25,
                "attention_level_v1": "Points a verifier",
                "confidence_level_v1": "MEDIUM",
            },
        ]
    )


def test_readonly_validation_reports_cover_requested_outputs():
    reports = build_validation_reports(
        _source_features(),
        _smart_features(),
        _scores_v2(),
        _details_v2(),
        _v1_scores(),
        feature_run_id="FEATURE_RUN",
        v1_score_run_id="V1_RUN",
        v1_score_version="IRIS_CLAIM_ATTENTION_HYBRID_V1_CANDIDATE",
        score_run_id_v2="V2_RUN",
        sample_size=2,
    )

    expected_reports = {
        "smart_v2_load_summary.csv",
        "smart_v2_evaluation_status_summary.csv",
        "smart_v2_score_distribution.csv",
        "smart_v2_attention_level_distribution.csv",
        "smart_v2_confidence_distribution.csv",
        "smart_v2_rule_activation_frequency.csv",
        "smart_v2_points_raw_awarded_by_rule.csv",
        "smart_v2_points_raw_awarded_by_family.csv",
        "smart_v2_comparable_cohort_summary.csv",
        "smart_v2_cohort_size_distribution.csv",
        "smart_v2_cohort_status_by_year_guarantee.csv",
        "smart_v2_amount_rule_activation_by_guarantee_year.csv",
        "smart_v2_chronology_rule_audit_by_period.csv",
        "smart_v2_non_evaluation_causes.csv",
        "smart_v2_grain_audit_summary.csv",
        "smart_v2_grain_multi_guarantee_summary.csv",
        "smart_v2_v1_v2_score_comparison.csv",
        "smart_v2_v1_v2_level_transition.csv",
        "smart_v2_business_validation_sample.csv",
        "smart_v2_stratified_business_validation_sample.csv",
        "smart_v2_validation_summary.csv",
    }
    assert expected_reports.issubset(reports)

    load_summary = reports["smart_v2_load_summary.csv"].iloc[0]
    assert load_summary["loaded_claim_rows"] == 3
    assert load_summary["fully_evaluable_claims"] == 1
    assert load_summary["displayable_comparison_claims"] == 1
    assert load_summary["evaluation_status"] == "PARTIALLY_EVALUABLE"
    assert "CHRONOLOGY" in load_summary["evaluable_rule_families"]
    assert "GEOGRAPHY" in load_summary["non_evaluable_rule_families"]

    rule_points = reports["smart_v2_points_raw_awarded_by_rule.csv"]
    chronology = rule_points.set_index("rule_code").loc["RULE_DELAY"]
    assert chronology["raw_points_total"] == 30
    assert chronology["awarded_points_total"] == 25

    comparison = reports["smart_v2_v1_v2_score_comparison.csv"].set_index("claim_sk")
    assert comparison.loc[1, "score_delta_v2_minus_v1"] == 10
    assert pd.isna(comparison.loc[3, "attention_score_v1"])

    assert not reports["smart_v2_grain_audit_summary.csv"].empty
    assert "business_review_comment" in reports["smart_v2_stratified_business_validation_sample.csv"].columns
    validation = reports["smart_v2_validation_summary.csv"].iloc[0]
    assert validation["score_out_of_range_rows"] == 0
    assert validation["accusatory_wording_rows"] == 0


def test_readonly_validation_script_has_no_postgresql_write_operations():
    script = Path("etl/mart/validate_claim_smart_decision_v2_readonly.py").read_text(encoding="utf-8").lower()
    forbidden_fragments = [
        ".to_sql(",
        " insert ",
        " update ",
        " delete ",
        " alter ",
        " drop ",
        " create table",
        " truncate ",
    ]
    assert not any(fragment in script for fragment in forbidden_fragments)
