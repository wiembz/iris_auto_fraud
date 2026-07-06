from etl.dwh.audit_dim_geo_excluded_rue_candidates import (
    ReferenceRow,
    build_candidate,
    build_reference_index,
)


def test_rue_unique_delegation_candidate_from_quartier_zone_label():
    ref_index = build_reference_index([
        ReferenceRow("SFAX", "SFAX SUD", "CITE ENNASR", "3083"),
        ReferenceRow("ARIANA", "RAOUED", "CITE ENNASR", "2083"),
    ])
    row = {
        "source_gouvernorat": "",
        "source_localite": "CITE ENNASR",
        "source_code_postal": "",
        "source_region": "",
        "source_rue": "CITE ENNASR SFAX SUD",
        "_source_geo_key": "UNKNOWN|UNKNOWN|CITE ENNASR|UNKNOWN",
    }

    candidate = build_candidate(row, ref_index)

    assert candidate is not None
    assert candidate["approval_status"] == "PENDING"
    assert candidate["geo_audit_status"] == "CORRECTION_CANDIDATE"
    assert candidate["review_decision_rule"] == "RUE_UNIQUE_DIMREGION_TERM_REVIEW"
    assert candidate["matched_reference_terms"] == "SFAX SUD"
    assert candidate["approved_gouvernorat"] == "SFAX"
    assert candidate["approved_delegation"] == "SFAX SUD"
    assert candidate["approved_localite"] == "SFAX SUD"


def test_rue_ambiguous_term_stays_pending_without_approved_target():
    ref_index = build_reference_index([
        ReferenceRow("BIZERTE", "GHAR EL MELH", "ZOUAOUINE", "7024"),
        ReferenceRow("MAHDIA", "MAHDIA", "ZOUAOUINE", "5131"),
    ])
    row = {
        "source_gouvernorat": "",
        "source_localite": "ZONE LIBRE",
        "source_code_postal": "",
        "source_region": "",
        "source_rue": "ZOUAOUINE",
        "_source_geo_key": "UNKNOWN|UNKNOWN|ZONE LIBRE|UNKNOWN",
    }

    candidate = build_candidate(row, ref_index)

    assert candidate is not None
    assert candidate["approval_status"] == "PENDING"
    assert candidate["geo_audit_status"] == "AMBIGUOUS_CANDIDATE"
    assert candidate["review_decision_rule"] == "RUE_AMBIGUOUS_DIMREGION_TERMS_REVIEW"
    assert candidate["approved_gouvernorat"] == ""
    assert "ZOUAOUINE" in candidate["matched_reference_terms"]
    assert "BIZERTE" in candidate["matched_reference_key"]
    assert "MAHDIA" in candidate["matched_reference_key"]
