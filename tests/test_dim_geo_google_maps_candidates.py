from etl.dwh.audit_dim_geo_google_maps_candidates import (
    build_google_query,
    evaluate_google_response,
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


def _google_ok_response():
    return {
        "status": "OK",
        "results": [
            {
                "formatted_address": "Sfax Sud, Sfax, Tunisia",
                "place_id": "place-1",
                "types": ["locality", "political"],
                "geometry": {
                    "location_type": "APPROXIMATE",
                    "location": {"lat": 34.7, "lng": 10.7},
                },
                "address_components": [
                    {"long_name": "Sfax Sud", "short_name": "Sfax Sud", "types": ["locality", "political"]},
                    {"long_name": "Sfax Governorate", "short_name": "Sfax", "types": ["administrative_area_level_1", "political"]},
                    {"long_name": "Tunisia", "short_name": "TN", "types": ["country", "political"]},
                ],
            }
        ],
    }


def test_google_confirmed_unique_candidate_is_auto_approvable():
    row = _candidate()

    result = evaluate_google_response(row, _google_ok_response(), build_google_query(row))

    assert result["google_decision"] == "AUTO_APPROVABLE"
    assert result["google_status"] == "GOOGLE_CONFIRMED"
    assert result["google_governorate_match"] == "YES"
    assert result["google_place_match"] == "YES"


def test_google_non_tunisia_result_is_conflict_review():
    row = _candidate()
    response = _google_ok_response()
    response["results"][0]["address_components"][-1] = {
        "long_name": "France",
        "short_name": "FR",
        "types": ["country", "political"],
    }

    result = evaluate_google_response(row, response, build_google_query(row))

    assert result["google_decision"] == "REVIEW"
    assert result["google_status"] == "GOOGLE_CONFLICT"


def test_verify_candidates_offline_does_not_call_google():
    rows = [_candidate()]

    result = verify_candidates(
        rows=rows,
        api_key=None,
        cache={},
        language="fr",
        limit=None,
        include_ambiguous=False,
        sleep_seconds=0,
        timeout_seconds=1,
        offline=True,
    )

    assert result[0]["google_decision"] == "REVIEW"
    assert result[0]["google_status"] == "GOOGLE_NOT_RUN"
    assert result[0]["google_query"] == "SFAX SUD, SFAX, Tunisie"
