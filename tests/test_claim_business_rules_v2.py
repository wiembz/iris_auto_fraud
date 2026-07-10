import copy

import pandas as pd

from etl.mart.compute_claim_business_rules_v2_candidate import (
    RULE_CATALOG_VERSION,
    SCORE_VERSION,
    compute_claim_business_rules_v2,
    contains_accusatory_wording,
    load_rule_catalog,
    validate_rule_catalog,
)


def _smart_features():
    return pd.DataFrame([
        {
            "claim_sk": 1,
            "claim_business_id": "S1|G1",
            "smart_feature_run_id": "SMART_RUN",
            "source_as_of_date": "2026-07-10",
            "input_hash": "abc",
            "declaration_delay_days": 45,
            "claim_before_contract_start_flag": False,
            "client_claim_count_12m": 3,
            "amount_ratio_to_median": 1.8,
            "comparison_reliability": "DISPLAYABLE",
            "critical_document_missing_count": 1,
            "data_quality_level": "LOW",
        },
        {
            "claim_sk": 2,
            "claim_business_id": "S2|G1",
            "smart_feature_run_id": "SMART_RUN",
            "source_as_of_date": "2026-07-10",
            "input_hash": "def",
            "declaration_delay_days": 4,
            "claim_before_contract_start_flag": False,
            "client_claim_count_12m": 0,
            "amount_ratio_to_median": pd.NA,
            "comparison_reliability": "INSUFFICIENT_SAMPLE",
            "critical_document_missing_count": 0,
            "data_quality_level": "HIGH",
        },
    ])


def test_rule_catalog_loads_and_has_required_shape():
    catalog = load_rule_catalog()
    assert catalog["catalog_version"] == RULE_CATALOG_VERSION
    assert catalog["score_version"] == SCORE_VERSION
    assert len(catalog["rules"]) >= 5
    validate_rule_catalog(catalog)


def test_active_rules_emit_business_signals_with_traceability():
    signals = compute_claim_business_rules_v2(_smart_features())
    by_code = set(signals[signals["claim_sk"].eq(1)]["rule_code"])

    assert {
        "CHR_DECLARATION_DELAY_HIGH",
        "HIST_CLIENT_RECURRENCE_12M",
        "COMP_AMOUNT_ABOVE_SIMILAR_MEDIAN",
        "COMP_CRITICAL_DOCUMENT_MISSING",
        "DATA_QUALITY_LIMITED",
    }.issubset(by_code)
    assert signals["business_explanation"].str.len().gt(0).all()
    assert signals["rule_catalog_hash"].str.len().eq(64).all()
    assert signals["smart_feature_run_id"].eq("SMART_RUN").all()
    assert not signals["business_explanation"].map(contains_accusatory_wording).any()


def test_inactive_rule_and_missing_required_field_do_not_emit_signal():
    catalog = load_rule_catalog()
    modified = copy.deepcopy(catalog)
    modified["rules"][0]["is_active"] = False
    missing_field_features = _smart_features().drop(columns=["critical_document_missing_count"])

    signals = compute_claim_business_rules_v2(missing_field_features, modified)

    assert "CHR_DECLARATION_DELAY_HIGH" not in set(signals["rule_code"])
    assert "COMP_CRITICAL_DOCUMENT_MISSING" not in set(signals["rule_code"])


def test_catalog_validation_rejects_accusatory_wording():
    catalog = load_rule_catalog()
    modified = copy.deepcopy(catalog)
    modified["rules"][0]["business_explanation"] = "preuve de fraude"

    try:
        validate_rule_catalog(modified)
    except ValueError as exc:
        assert "accusatory" in str(exc).lower()
    else:
        raise AssertionError("Expected wording validation to fail")


def test_catalog_validation_rejects_bad_operator_unknown_action_and_bad_active_type():
    catalog = load_rule_catalog()

    bad_operator = copy.deepcopy(catalog)
    bad_operator["rules"][0]["condition"]["operator"] = "between"
    bad_action = copy.deepcopy(catalog)
    bad_action["rules"][0]["suggested_action_code"] = "ACT_UNKNOWN"
    bad_active = copy.deepcopy(catalog)
    bad_active["rules"][0]["is_active"] = "true"

    for modified in [bad_operator, bad_action, bad_active]:
        try:
            validate_rule_catalog(modified)
        except ValueError:
            pass
        else:
            raise AssertionError("Expected strict catalog validation to fail")


def test_catalog_validation_requires_condition_fields_declared():
    catalog = load_rule_catalog()
    modified = copy.deepcopy(catalog)
    modified["rules"][3]["condition"]["requires"]["undeclared_field"] = "X"

    try:
        validate_rule_catalog(modified)
    except ValueError as exc:
        assert "undeclared" in str(exc).lower()
    else:
        raise AssertionError("Expected undeclared requires validation to fail")
