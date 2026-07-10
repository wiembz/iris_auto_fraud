import pandas as pd

from etl.mart.compute_claim_attention_score_v2_candidate import compute_claim_attention_score_v2
from etl.mart.generate_claim_explanations_v2 import (
    contains_forbidden_language,
    generate_claim_explanations,
)
from etl.utils.business_language import normalize_business_text


def test_business_language_guardrails_block_accusatory_terms_with_accents_case_and_spaces():
    assert contains_forbidden_language("  PREUVE   DE   FRAUDE  ")
    assert contains_forbidden_language("probabilité de fraude")
    assert normalize_business_text("Suspect confirmé") == "suspect confirme"
    assert not contains_forbidden_language("verification complementaire suggeree")


def test_generated_explanations_are_deterministic_and_non_accusatory():
    features = pd.DataFrame([{
        "claim_sk": 1,
        "claim_business_id": "S1|G1",
        "smart_feature_run_id": "SMART_RUN",
        "declaration_delay_days": 45,
        "claim_before_contract_start_flag": False,
        "client_claim_count_12m": 3,
        "amount_ratio_to_median": 2.0,
        "comparison_reliability": "DISPLAYABLE",
        "critical_document_missing_count": 1,
        "data_quality_level": "LOW",
        "confidence_level": "LOW",
    }])
    scores, details = compute_claim_attention_score_v2(features)
    explanations = generate_claim_explanations(scores, details)
    text = explanations.loc[0, "business_summary"]

    assert "aide a l'analyse" in text
    assert "decision du gestionnaire" in text
    assert not contains_forbidden_language(text)
