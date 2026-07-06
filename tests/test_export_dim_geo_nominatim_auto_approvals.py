from etl.dwh.export_dim_geo_nominatim_auto_approvals import (
    build_auto_approval_export,
    build_auto_approval_rows,
    is_auto_approvable,
)


def _row(**overrides):
    row = {
        "source_geo_key": "UNKNOWN|UNKNOWN|YASMINET|UNKNOWN",
        "current_region": "UNKNOWN",
        "current_gouvernorat": "UNKNOWN",
        "current_localite": "YASMINET",
        "current_code_postal": "UNKNOWN",
        "approved_region": "GRAND TUNIS",
        "approved_gouvernorat": "BEN AROUS",
        "approved_delegation": "EL MOUROUJ",
        "approved_localite": "EL MOUROUJ",
        "approved_code_postal": "UNKNOWN",
        "geo_audit_status": "CORRECTION_CANDIDATE",
        "confidence_score": "0.70",
        "matched_source_field": "source_rue",
        "matched_reference_key": "GRAND TUNIS|BEN AROUS|EL MOUROUJ|EL MOUROUJ|UNKNOWN",
        "nominatim_decision": "AUTO_APPROVABLE",
        "nominatim_status": "NOMINATIM_CONFIRMED",
        "nominatim_governorate_match": "YES",
        "nominatim_place_match": "YES",
        "nominatim_query": "EL MOUROUJ, BEN AROUS, Tunisie",
        "nominatim_place_id": "53166285",
        "nominatim_display_name": "El Mourouj, Gouvernorat Ben Arous, Tunisie",
    }
    row.update(overrides)
    return row


def test_is_auto_approvable_requires_confirmed_matches():
    assert is_auto_approvable(_row(), min_confidence=0.70)
    assert not is_auto_approvable(_row(nominatim_place_match="NO"), min_confidence=0.70)
    assert not is_auto_approvable(_row(nominatim_status="NOMINATIM_PARTIAL"), min_confidence=0.70)
    assert not is_auto_approvable(_row(confidence_score="0.60"), min_confidence=0.70)


def test_build_auto_approval_rows_outputs_pending_correction_shape():
    rows = [_row()]

    result = build_auto_approval_rows(rows, existing_keys=set(), approval_status="PENDING", min_confidence=0.70)

    assert len(result) == 1
    assert result[0]["geo_key"] == "UNKNOWN|UNKNOWN|YASMINET|UNKNOWN"
    assert result[0]["approval_status"] == "PENDING"
    assert result[0]["review_decision_rule"] == "NOMINATIM_AUTO_APPROVABLE_DIMREGION_RUE_TERM_UNIQUE_SOURCE_KEY"
    assert result[0]["approved_gouvernorat"] == "BEN AROUS"


def test_build_auto_approval_rows_skips_existing_keys():
    rows = [_row()]

    result = build_auto_approval_rows(
        rows,
        existing_keys={"UNKNOWN|UNKNOWN|YASMINET|UNKNOWN"},
        approval_status="APPROVED",
        min_confidence=0.70,
    )

    assert result == []


def test_build_auto_approval_export_skips_same_source_key_with_multiple_targets():
    rows = [
        _row(source_geo_key="UNKNOWN|UNKNOWN|LES BERGES DU LAC|UNKNOWN", approved_gouvernorat="ARIANA", approved_localite="EL MENZAH 7"),
        _row(source_geo_key="UNKNOWN|UNKNOWN|LES BERGES DU LAC|UNKNOWN", approved_gouvernorat="TUNIS", approved_localite="EL KRAM"),
    ]

    output, skipped = build_auto_approval_export(rows, existing_keys=set(), approval_status="PENDING", min_confidence=0.70)

    assert output == []
    assert len(skipped) == 1
    assert skipped[0]["source_geo_key"] == "UNKNOWN|UNKNOWN|LES BERGES DU LAC|UNKNOWN"
    assert skipped[0]["distinct_approved_targets"] == "2"
