from datetime import datetime

import pandas as pd

from etl.mart.compute_claim_attention_hybrid_score_v1_candidate import (
    SCORE_VERSION,
    attention_level,
    compute_claim_attention_hybrid_scores,
    validate_hybrid_outputs,
)


def _config():
    return {
        "score_version": SCORE_VERSION,
        "profile_name": "CLAIM_ATTENTION_HYBRID_V1_CANDIDATE",
        "max_score": 100,
        "business_rules": {
            "enabled": True,
            "max_points": 70,
            "exclude_data_quality_signals": True,
            "default_rule_weight": 1.0,
            "family_weights": {
                "Recurrence client": 1.0,
                "Montant atypique": 1.0,
                "Chronologie": 1.0,
            },
            "family_caps": {
                "Recurrence client": 25,
                "Montant atypique": 25,
                "Chronologie": 20,
            },
            "rule_weights": {
                "CLIENT_CLAIMS_12M_HIGH": 1.0,
                "CLIENT_RECENT_PREVIOUS_CLAIM": 1.0,
                "AMOUNT_HIGH_BY_GUARANTEE": 1.0,
            },
        },
        "post_inspection": {
            "enabled": True,
            "max_points": 25,
            "scenario_code": "A_INSPECTION_TO_CLAIM",
            "confidence_points": {"HIGH": 25, "MEDIUM": 15, "LOW": 0},
            "include_zero_point_context": True,
        },
    }


def test_attention_level_boundaries():
    assert attention_level(0) == "Analyse standard"
    assert attention_level(24) == "Analyse standard"
    assert attention_level(25) == "Points a verifier"
    assert attention_level(50) == "Examen renforce suggere"
    assert attention_level(75) == "Examen prioritaire suggere"


def test_hybrid_score_weights_business_rules_and_caps_family():
    features = pd.DataFrame([{
        "claim_sk": 1,
        "claim_business_id": "S1|G1",
        "feature_run_id": "FEATURE_RUN",
        "confidence_level": "HIGH",
    }])
    business_rules = pd.DataFrame([
        {
            "claim_sk": 1,
            "claim_business_id": "S1|G1",
            "rule_family": "Recurrence client",
            "rule_code": "CLIENT_CLAIMS_12M_HIGH",
            "rule_label": "Recurrence client elevee",
            "rule_severity_rank": 3,
            "rule_observed_value": "3",
            "candidate_points": 20,
            "business_explanation": "Plusieurs sinistres precedents sont observes.",
            "is_data_quality_signal": False,
        },
        {
            "claim_sk": 1,
            "claim_business_id": "S1|G1",
            "rule_family": "Recurrence client",
            "rule_code": "CLIENT_RECENT_PREVIOUS_CLAIM",
            "rule_label": "Sinistre precedent recent",
            "rule_severity_rank": 1,
            "rule_observed_value": "10",
            "candidate_points": 10,
            "business_explanation": "Le dossier suit un precedent sinistre du meme client.",
            "is_data_quality_signal": False,
        },
        {
            "claim_sk": 1,
            "claim_business_id": "S1|G1",
            "rule_family": "Montant atypique",
            "rule_code": "AMOUNT_HIGH_BY_GUARANTEE",
            "rule_label": "Montant eleve",
            "rule_severity_rank": 3,
            "rule_observed_value": "ratio=4",
            "candidate_points": 20,
            "business_explanation": "Le montant est au-dessus du profil de garantie.",
            "is_data_quality_signal": False,
        },
    ])

    scores, details = compute_claim_attention_hybrid_scores(
        features,
        business_rules,
        pd.DataFrame(),
        config=_config(),
        score_run_id="HYBRID_RUN",
        created_at=datetime(2026, 7, 8, 12, 0, 0),
    )

    assert scores.loc[0, "score_version"] == SCORE_VERSION
    assert scores.loc[0, "attention_score"] == 45
    assert details.groupby("signal_family")["points"].sum().to_dict() == {
        "Regles metier - Montant atypique": 20,
        "Regles metier - Recurrence client": 25,
    }
    assert validate_hybrid_outputs(scores, details)["detail_point_mismatch_rows"] == 0


def test_hybrid_score_uses_configurable_rule_weight():
    config = _config()
    config["business_rules"]["rule_weights"]["AMOUNT_HIGH_BY_GUARANTEE"] = 0.5
    features = pd.DataFrame([{
        "claim_sk": 1,
        "claim_business_id": "S1|G1",
        "feature_run_id": "FEATURE_RUN",
        "confidence_level": "HIGH",
    }])
    business_rules = pd.DataFrame([{
        "claim_sk": 1,
        "claim_business_id": "S1|G1",
        "rule_family": "Montant atypique",
        "rule_code": "AMOUNT_HIGH_BY_GUARANTEE",
        "rule_label": "Montant eleve",
        "rule_severity_rank": 3,
        "rule_observed_value": "ratio=4",
        "candidate_points": 20,
        "business_explanation": "Le montant est au-dessus du profil de garantie.",
        "is_data_quality_signal": False,
    }])

    scores, details = compute_claim_attention_hybrid_scores(
        features,
        business_rules,
        pd.DataFrame(),
        config=config,
        score_run_id="HYBRID_RUN",
    )

    assert details.loc[0, "points"] == 10
    assert scores.loc[0, "attention_score"] == 10


def test_post_inspection_uses_strongest_claim_signal_once():
    features = pd.DataFrame([{
        "claim_sk": 2,
        "claim_business_id": "S2|G1",
        "feature_run_id": "FEATURE_RUN",
        "confidence_level": "MEDIUM",
    }])
    post = pd.DataFrame([
        {
            "claim_sk": 2,
            "scenario_code": "A_INSPECTION_TO_CLAIM",
            "confidence_level": "MEDIUM",
            "days_inspection_to_claim": 20,
            "defective_zone": "SOUS_CAPOT",
        },
        {
            "claim_sk": 2,
            "scenario_code": "A_INSPECTION_TO_CLAIM",
            "confidence_level": "HIGH",
            "days_inspection_to_claim": 5,
            "defective_zone": "INTERIEUR",
        },
    ])

    scores, details = compute_claim_attention_hybrid_scores(
        features,
        pd.DataFrame(),
        post,
        config=_config(),
        score_run_id="HYBRID_RUN",
    )

    assert scores.loc[0, "attention_score"] == 25
    assert len(details) == 1
    assert details.loc[0, "signal_code"] == "POST_INSPECTION_HIGH"


def test_data_quality_rule_does_not_add_points():
    features = pd.DataFrame([{
        "claim_sk": 3,
        "claim_business_id": "S3|G1",
        "feature_run_id": "FEATURE_RUN",
        "confidence_level": "LOW",
    }])
    business_rules = pd.DataFrame([{
        "claim_sk": 3,
        "claim_business_id": "S3|G1",
        "rule_family": "Qualite donnees",
        "rule_code": "DATA_QUALITY_LIMITATION",
        "rule_label": "Donnees a completer",
        "rule_severity_rank": 0,
        "rule_observed_value": "missing_vehicle_flag",
        "candidate_points": 99,
        "business_explanation": "Des donnees structurantes sont manquantes.",
        "is_data_quality_signal": True,
    }])

    scores, details = compute_claim_attention_hybrid_scores(
        features,
        business_rules,
        pd.DataFrame(),
        config=_config(),
        score_run_id="HYBRID_RUN",
    )

    assert scores.loc[0, "attention_score"] == 0
    assert details.empty
    assert scores.loc[0, "confidence_level"] == "LOW"
