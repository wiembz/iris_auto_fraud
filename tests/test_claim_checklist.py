import pandas as pd

from etl.mart.compute_claim_attention_score_v2_candidate import compute_claim_attention_score_v2
from etl.mart.generate_claim_checklist_v1 import generate_claim_checklist


def _details_for_chronology(score_run_id):
    features = pd.DataFrame([{
        "claim_sk": 1,
        "claim_business_id": "S1|G1",
        "smart_feature_run_id": "SMART_RUN",
        "declaration_delay_days": 45,
        "claim_before_contract_start_flag": True,
        "client_claim_count_12m": 0,
        "amount_ratio_to_median": pd.NA,
        "comparison_reliability": "INSUFFICIENT_SAMPLE",
        "critical_document_missing_count": 0,
        "data_quality_level": "HIGH",
        "confidence_level": "HIGH",
    }])
    _, details = compute_claim_attention_score_v2(features, score_run_id=score_run_id)
    return details


def test_checklist_deduplicates_actions_for_same_claim_and_run():
    details = _details_for_chronology("SCORE_RUN")
    checklist = generate_claim_checklist(details)

    assert len(checklist[checklist["action_code"].eq("ACT_VERIFY_CHRONOLOGY")]) == 1
    assert checklist["status"].eq("TO_CHECK").all()
    assert checklist["label"].str.contains("Verifier", regex=False).any()


def test_checklist_does_not_mix_multiple_runs():
    details = pd.concat([_details_for_chronology("RUN_A"), _details_for_chronology("RUN_B")], ignore_index=True)
    checklist = generate_claim_checklist(details)

    assert len(checklist[checklist["action_code"].eq("ACT_VERIFY_CHRONOLOGY")]) == 2
    assert set(checklist["score_run_id"]) == {"RUN_A", "RUN_B"}
    assert set(checklist["checklist_item_id"]) == {
        "RUN_A:1:ACT_VERIFY_CHRONOLOGY",
        "RUN_B:1:ACT_VERIFY_CHRONOLOGY",
    }


def test_checklist_rejects_unknown_action_code():
    details = _details_for_chronology("RUN_A")
    details.loc[0, "suggested_action_code"] = "ACT_UNKNOWN"

    try:
        generate_claim_checklist(details)
    except ValueError as exc:
        assert "unknown" in str(exc).lower()
    else:
        raise AssertionError("Expected unknown action code to fail")
