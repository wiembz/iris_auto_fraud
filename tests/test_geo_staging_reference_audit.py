from etl.staging_area.audit_geo_staging_reference import (
    ReferenceRow,
    audit_source_rows,
    build_reference_index,
)


def _reference_index():
    rows = [
        ReferenceRow("ARIANA", "MNIHLA", "MNIHLA", "2094"),
        ReferenceRow("BEN AROUS", "EZZAHRA", "EZZAHRA", "2034"),
        ReferenceRow("SOUSSE", "AKOUDA", "AKOUDA", "4022"),
        ReferenceRow("MONASTIR", "MONASTIR", "MONASTIR", "5000"),
        ReferenceRow("TUNIS", "BAB BHAR", "BAB BHAR", "1000"),
        ReferenceRow("TUNIS", "BAB BHAR", "EL MEDINA", "1000"),
    ]
    return build_reference_index(rows)


def test_detects_postal_governorate_conflict():
    results = audit_source_rows(
        [
            {
                "cpostsini": "2034.0",
                "regsini": "TUNIS",
                "gouvsini": "TUNIS",
                "citesini": "EZZAHRA",
                "rue": "TUNIS",
            }
        ],
        _reference_index(),
    )

    assert results[0]["audit_status"] == "CONFLICT"
    assert "POSTAL_GOUV_CONFLICT" in results[0]["flags"]
    assert results[0]["candidate_gouvernorat"] == "BEN AROUS"


def test_proposes_missing_governorate_from_unique_postal_code():
    results = audit_source_rows(
        [
            {
                "cpostsini": "4022.0",
                "regsini": "",
                "gouvsini": "",
                "citesini": "",
                "rue": "AKOUDA SOUSSE",
            }
        ],
        _reference_index(),
    )

    assert results[0]["audit_status"] == "ENRICHMENT_CANDIDATE"
    assert "MISSING_GOUV_FROM_CP_UNIQUE" in results[0]["flags"]
    assert results[0]["candidate_gouvernorat"] == "SOUSSE"


def test_marks_missing_locality_from_non_unique_postal_code_ambiguous():
    results = audit_source_rows(
        [
            {
                "cpostsini": "1000",
                "regsini": "",
                "gouvsini": "TUNIS",
                "citesini": "",
                "rue": "",
            }
        ],
        _reference_index(),
    )

    assert results[0]["audit_status"] == "AMBIGUOUS_REFERENCE"
    assert "MISSING_LOCALITE_FROM_CP_AMBIGUOUS" in results[0]["flags"]
    assert results[0]["candidate_localite"] == "BAB BHAR|EL MEDINA"


def test_proposes_missing_postal_code_from_unique_governorate_locality():
    results = audit_source_rows(
        [
            {
                "cpostsini": "",
                "regsini": "MONASTIR",
                "gouvsini": "MONASTIR",
                "citesini": "MONASTIR",
                "rue": "AV MED SALAH SAYADI",
            }
        ],
        _reference_index(),
    )

    assert results[0]["audit_status"] == "ENRICHMENT_CANDIDATE"
    assert "MISSING_CP_FROM_GOUV_LOCALITE_UNIQUE" in results[0]["flags"]
    assert results[0]["candidate_code_postal"] == "5000"
