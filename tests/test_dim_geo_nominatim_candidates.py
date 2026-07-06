from etl.dwh.audit_dim_geo_nominatim_candidates import (
    build_nominatim_query,
    evaluate_nominatim_response,
    verify_candidates,
)


def _candidate(**overrides):
    row = {
        "geo_audit_status": "CORRECTION_CANDIDATE",
        "matched_reference_terms": "SFAX SUD",
        "approved_gouvernorat": "SFAX",
        "approved_delegation": "SFAX SUD",
        "approved_localite": "SFAX SUD",
        "source_rue": "CITE ENNASR SFAX SUD",
    }
    row.update(overrides)
    return row


def _nominatim_ok_response():
    return [
        {
            "place_id": 123,
            "osm_type": "relation",
            "osm_id": 456,
            "lat": "34.7406",
            "lon": "10.7603",
            "class": "boundary",
            "type": "administrative",
            "importance": 0.42,
            "display_name": "Sfax Sud, Gouvernorat de Sfax, Tunisie",
            "address": {
                "city": "Sfax Sud",
                "state": "Gouvernorat de Sfax",
                "country": "Tunisie",
                "country_code": "tn",
            },
        }
    ]


def test_nominatim_confirmed_unique_candidate_is_auto_approvable():
    row = _candidate()

    result = evaluate_nominatim_response(row, _nominatim_ok_response(), build_nominatim_query(row))

    assert result["nominatim_decision"] == "AUTO_APPROVABLE"
    assert result["nominatim_status"] == "NOMINATIM_CONFIRMED"
    assert result["nominatim_governorate_match"] == "YES"
    assert result["nominatim_place_match"] == "YES"


def test_nominatim_explicit_non_tunisia_country_is_conflict_review():
    row = _candidate()
    response = _nominatim_ok_response()
    response[0]["address"]["country"] = "France"
    response[0]["address"]["country_code"] = "fr"

    result = evaluate_nominatim_response(row, response, build_nominatim_query(row))

    assert result["nominatim_decision"] == "REVIEW"
    assert result["nominatim_status"] == "NOMINATIM_CONFLICT"


def test_build_nominatim_query_does_not_send_raw_rue():
    row = _candidate(source_rue="12 RUE PERSONNELLE CITE ENNASR SFAX SUD")

    query = build_nominatim_query(row)

    assert query == "SFAX SUD, SFAX, Tunisie"
    assert "12 RUE" not in query
    assert "PERSONNELLE" not in query


def test_verify_candidates_without_online_does_not_call_nominatim():
    rows = [_candidate()]

    result = verify_candidates(
        rows=rows,
        cache={},
        language="fr",
        limit=None,
        result_limit=5,
        include_ambiguous=False,
        sleep_seconds=0,
        timeout_seconds=1,
        online=False,
        base_url="https://nominatim.openstreetmap.org/search",
        user_agent="IRIS-AUTO-FRAUD-GEO-AUDIT/1.0",
        email=None,
    )

    assert result[0]["nominatim_decision"] == "REVIEW"
    assert result[0]["nominatim_status"] == "NOMINATIM_NOT_RUN"
    assert result[0]["nominatim_query"] == "SFAX SUD, SFAX, Tunisie"
