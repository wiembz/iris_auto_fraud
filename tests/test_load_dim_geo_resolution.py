import pandas as pd

from etl.dwh.load_dim_geo import (
    _apply_approved_geo_corrections,
    _linguistic_key_for_localite,
    _resolve_gov_from_postal_reference,
    _resolve_one_geo_row,
    _source_geo_key_from_values,
)


def _postal_ref(gouvernorat, delegation, localite, code_postal):
    return {
        "gouvernorat": gouvernorat,
        "delegation": delegation,
        "localite": localite,
        "code_postal": code_postal,
        "confidence": 1.0,
    }


def test_resolves_governorate_from_unique_postal_reference():
    refs = [_postal_ref("SIDI BOUZID", "REGUEB", "ERRADHAA", "9174")]
    reference_indexes = {"postal": {"9174": refs}}

    assert _resolve_gov_from_postal_reference("9174.0", reference_indexes) == "SIDI BOUZID"


def test_does_not_resolve_governorate_from_ambiguous_postal_reference():
    refs = [
        _postal_ref("TUNIS", "BAB BHAR", "BAB BHAR", "1000"),
        _postal_ref("ARIANA", "ARIANA VILLE", "ARIANA", "1000"),
    ]
    reference_indexes = {"postal": {"1000": refs}}

    assert _resolve_gov_from_postal_reference("1000", reference_indexes) is None


def test_resolve_one_geo_row_uses_unique_postal_place_when_geography_missing():
    ref = _postal_ref("SIDI BOUZID", "REGUEB", "ERRADHAA", "9174")
    reference_indexes = {
        "postal": {"9174": [ref]},
        "postal_localite": {("SIDI BOUZID", "ERRADHAA"): [ref]},
        "postal_alias": {},
        "postal_delegation": {("SIDI BOUZID", "REGUEB"): [ref]},
    }
    row = pd.Series({
        "gouvernorat": None,
        "localite": None,
        "regsini_hint": None,
        "code_postal": "9174.0",
        "rue": None,
    })

    result = _resolve_one_geo_row(row, reference_indexes, corrections_by_key={}, alias_dict={})

    assert result["resolution_status"].startswith("STEP4_POSTAL")
    assert result["gouvernorat"] == "SIDI BOUZID"
    assert result["localite"] == "ERRADHAA"
    assert result["code_postal"] == "9174"
    assert result["geo_quality_level"] == "VALIDATED"


def test_apply_approved_geo_corrections_updates_resolution_row():
    df = pd.DataFrame([
        {
            "pays": "UNKNOWN",
            "region": "UNKNOWN",
            "gouvernorat": "UNKNOWN",
            "localite": "DENDEN",
            "code_postal": "UNKNOWN",
            "geo_key": "UNKNOWN|UNKNOWN|DENDEN|UNKNOWN",
            "_source_geo_key": "UNKNOWN|UNKNOWN|DENDEN|UNKNOWN",
            "geo_quality_level": "AMBIGUOUS",
            "needs_review": "YES",
            "resolution_status": "STEP5_EXCLUDED",
            "postal_code_status": "POSTAL_NOT_APPLICABLE",
            "conflict_detected": "NO",
        }
    ])
    corrections = {
        "UNKNOWN|UNKNOWN|DENDEN|UNKNOWN": {
            "correction_id": 1,
            "region": "GRAND TUNIS",
            "gouvernorat": "MANOUBA",
            "delegation": "MANOUBA",
            "localite": "DENDEN",
            "code_postal": None,
        }
    }

    corrected, metrics = _apply_approved_geo_corrections(df, corrections, reference_indexes={"postal_localite": {}})

    assert metrics["n_rows_corrected"] == 1
    assert corrected.loc[0, "pays"] == "TUNISIE"
    assert corrected.loc[0, "gouvernorat"] == "MANOUBA"
    assert corrected.loc[0, "localite"] == "DENDEN"
    assert corrected.loc[0, "resolution_status"] == "APPROVED_CORRECTION"

def test_step4_does_not_resolve_governorate_from_prefix_without_dimregion_match():
    reference_indexes = {
        "postal": {},
        "postal_localite": {},
        "postal_alias": {},
        "postal_delegation": {},
    }
    row = pd.Series({
        "gouvernorat": None,
        "localite": None,
        "regsini_hint": None,
        "code_postal": "3999",
        "rue": None,
    })

    result = _resolve_one_geo_row(row, reference_indexes, corrections_by_key={}, alias_dict={})

    assert result["resolution_status"] == "STEP5_EXCLUDED"
    assert result["geo_quality_level"] == "CONFLICT"
    assert result["postal_code_status"] == "POSTAL_CONFLICT_SOURCE_NOT_IN_DIMREGION"


def test_source_postal_code_conflict_prevents_validated_quality():
    sidi_ref = _postal_ref("SIDI BOUZID", "REGUEB", "ERRADHAA", "9174")
    sfax_ref = _postal_ref("SFAX", "SFAX VILLE", "SFAX", "3000")
    reference_indexes = {
        "postal": {"9174": [sidi_ref], "3000": [sfax_ref]},
        "postal_localite": {("SFAX", "SFAX"): [sfax_ref]},
        "postal_alias": {},
        "postal_delegation": {},
    }
    row = pd.Series({
        "gouvernorat": "SFAX",
        "localite": "SFAX",
        "regsini_hint": None,
        "code_postal": "9174",
        "rue": None,
    })

    result = _resolve_one_geo_row(row, reference_indexes, corrections_by_key={}, alias_dict={})

    assert result["gouvernorat"] == "SFAX"
    assert result["localite"] is None
    assert result["code_postal"] is None
    assert result["geo_quality_level"] == "PARTIAL"
    assert result["conflict_detected"] == "YES"
    assert result["postal_code_status"] == "POSTAL_CONFLICT_GOUVERNORAT_DIMREGION"
    assert result["adresse_fragment"] == "SFAX"

def test_resolves_missing_governorate_from_unique_dimregion_localite():
    ref = _postal_ref("JENDOUBA", "JENDOUBA NORD", "JENDOUBA NORD", "8100")
    reference_indexes = {
        "postal": {},
        "postal_localite": {("JENDOUBA", "JENDOUBA NORD"): [ref]},
        "postal_alias": {},
        "postal_delegation": {("JENDOUBA", "JENDOUBA NORD"): [ref]},
        "postal_localite_global": {"JENDOUBA NORD": [ref]},
        "postal_delegation_global": {"JENDOUBA NORD": [ref]},
    }
    row = pd.Series({
        "gouvernorat": None,
        "localite": "JENDOUBA NORD",
        "regsini_hint": None,
        "code_postal": None,
        "rue": None,
    })

    result = _resolve_one_geo_row(row, reference_indexes, corrections_by_key={}, alias_dict={})

    assert result["resolution_status"].startswith("STEP4_DIMREGION_LOCALITE")
    assert result["gouvernorat"] == "JENDOUBA"
    assert result["localite"] == "JENDOUBA NORD"
    assert result["code_postal"] == "8100"
    assert result["geo_quality_level"] == "VALIDATED"


def test_ambiguous_dimregion_localite_is_not_resolved_without_governorate():
    tunis_ref = _postal_ref("TUNIS", "EL MENZAH", "CITE ENNASR", "2037")
    ariana_ref = _postal_ref("ARIANA", "ARIANA VILLE", "CITE ENNASR", "2080")
    reference_indexes = {
        "postal": {},
        "postal_localite": {
            ("TUNIS", "CITE ENNASR"): [tunis_ref],
            ("ARIANA", "CITE ENNASR"): [ariana_ref],
        },
        "postal_alias": {},
        "postal_delegation": {},
        "postal_localite_global": {"CITE ENNASR": [tunis_ref, ariana_ref]},
        "postal_delegation_global": {},
    }
    row = pd.Series({
        "gouvernorat": None,
        "localite": "CITE ENNASR",
        "regsini_hint": None,
        "code_postal": None,
        "rue": None,
    })

    result = _resolve_one_geo_row(row, reference_indexes, corrections_by_key={}, alias_dict={})

    assert result["resolution_status"] == "STEP5_EXCLUDED"
    assert result["gouvernorat"] is None
    assert result["geo_quality_level"] == "AMBIGUOUS"

def test_dimregion_rue_match_overrides_noisy_regsini():
    ref = _postal_ref("JENDOUBA", "JENDOUBA NORD", "JENDOUBA NORD", "8100")
    reference_indexes = {
        "postal": {},
        "postal_localite": {("JENDOUBA", "JENDOUBA NORD"): [ref]},
        "postal_alias": {},
        "postal_delegation": {("JENDOUBA", "JENDOUBA NORD"): [ref]},
        "postal_localite_global": {"JENDOUBA NORD": [ref]},
        "postal_delegation_global": {"JENDOUBA NORD": [ref]},
    }
    row = pd.Series({
        "gouvernorat": None,
        "localite": None,
        "regsini_hint": "ZONE LIBRE",
        "code_postal": None,
        "rue": "JENDOUBA NORD",
    })

    result = _resolve_one_geo_row(row, reference_indexes, corrections_by_key={}, alias_dict={})

    assert result["resolution_status"].startswith("STEP4_DIMREGION_LOCALITE")
    assert result["gouvernorat"] == "JENDOUBA"
    assert result["localite"] == "JENDOUBA NORD"
    assert result["code_postal"] == "8100"

def test_resolves_missing_governorate_from_unique_dimregion_linguistic_localite():
    ref = _postal_ref("SFAX", "SFAX SUD", "TYNA", "3083")
    reference_indexes = {
        "postal": {},
        "postal_localite": {("SFAX", "TYNA"): [ref]},
        "postal_alias": {},
        "postal_delegation": {("SFAX", "SFAX SUD"): [ref]},
        "postal_localite_global": {"TYNA": [ref]},
        "postal_localite_linguistic_global": {"TINA": [ref]},
        "postal_delegation_global": {"SFAX SUD": [ref]},
    }
    row = pd.Series({
        "gouvernorat": None,
        "localite": "THYNA",
        "regsini_hint": None,
        "code_postal": None,
        "rue": None,
    })

    result = _resolve_one_geo_row(row, reference_indexes, corrections_by_key={}, alias_dict={})

    assert result["resolution_status"].startswith("STEP4_DIMREGION_LINGUISTIC_LOCALITE")
    assert result["gouvernorat"] == "SFAX"
    assert result["localite"] == "TYNA"
    assert result["code_postal"] == "3083"
    assert result["geo_quality_level"] == "VALIDATED"


def test_ambiguous_dimregion_linguistic_localite_is_not_resolved_without_governorate():
    bizerte_ref = _postal_ref("BIZERTE", "GHAR EL MELH", "ZOUAOUINE", "7024")
    mahdia_ref = _postal_ref("MAHDIA", "MAHDIA", "ZOUAOUINE", "5131")
    reference_indexes = {
        "postal": {},
        "postal_localite": {
            ("BIZERTE", "ZOUAOUINE"): [bizerte_ref],
            ("MAHDIA", "ZOUAOUINE"): [mahdia_ref],
        },
        "postal_alias": {},
        "postal_delegation": {},
        "postal_localite_global": {"ZOUAOUINE": [bizerte_ref, mahdia_ref]},
        "postal_localite_linguistic_global": {"ZOAINE": [bizerte_ref, mahdia_ref]},
        "postal_delegation_global": {},
    }
    row = pd.Series({
        "gouvernorat": None,
        "localite": "ZOUAOUINE",
        "regsini_hint": None,
        "code_postal": None,
        "rue": None,
    })

    result = _resolve_one_geo_row(row, reference_indexes, corrections_by_key={}, alias_dict={})

    assert result["resolution_status"] == "STEP5_EXCLUDED"
    assert result["gouvernorat"] is None
    assert result["geo_quality_level"] == "AMBIGUOUS"

def test_source_geo_key_normalizes_governorate_aliases_for_fact_mapping():
    assert _source_geo_key_from_values("MANNOUBA", "TEBOURBA", "1130.0") == "TUNISIE|MANOUBA|TEBOURBA|1130"
    assert _source_geo_key_from_values("B", "MAHDIA", "5100.0") == "TUNISIE|UNKNOWN|MAHDIA|5100"
    assert _source_geo_key_from_values("TUNISIE -", "NAASSEN", "1135.0") == "TUNISIE|UNKNOWN|NAASSEN|1135"


def test_fuzzy_localite_variants_resolve_jebeniana_inside_sfax():
    ref = _postal_ref("SFAX", "JEBENIANA", "JEBENIANA", "3080")
    reference_indexes = {
        "postal": {},
        "postal_localite": {("SFAX", "JEBENIANA"): [ref]},
        "postal_alias": {},
        "postal_delegation": {("SFAX", "JEBENIANA"): [ref]},
        "postal_localite_global": {"JEBENIANA": [ref]},
        "postal_localite_linguistic_global": {},
        "postal_delegation_global": {"JEBENIANA": [ref]},
    }

    for localite in ["DJEBENIANA SFAX", "DJEBENIENA", "DJEBINIANA", "DJEBINIANA SFAX"]:
        row = pd.Series({
            "gouvernorat": "SFAX",
            "localite": localite,
            "regsini_hint": None,
            "code_postal": None,
            "rue": None,
        })

        result = _resolve_one_geo_row(row, reference_indexes, corrections_by_key={}, alias_dict={})

        assert result["gouvernorat"] == "SFAX"
        assert result["localite"] == "JEBENIANA"
        assert result["code_postal"] == "3080"
        assert result["geo_quality_level"] == "VALIDATED"


def test_fuzzy_localite_variants_resolve_chebba_rejiche_and_bennane():
    chebba = _postal_ref("MAHDIA", "LA CHEBBA", "LA CHEBBA", "5170")
    rejiche = _postal_ref("MAHDIA", "MAHDIA", "REJICHE", "5121")
    bennane = _postal_ref("MONASTIR", "KSIBET EL MEDIOUN", "BENNANE", "5025")
    reference_indexes = {
        "postal": {},
        "postal_localite": {
            ("MAHDIA", "LA CHEBBA"): [chebba],
            ("MAHDIA", "REJICHE"): [rejiche],
            ("MONASTIR", "BENNANE"): [bennane],
        },
        "postal_alias": {},
        "postal_delegation": {},
        "postal_localite_global": {},
        "postal_localite_linguistic_global": {},
        "postal_delegation_global": {},
    }

    cases = [
        ("MAHDIA", "ECHABBA", "LA CHEBBA", "5170"),
        ("MAHDIA", "ECHEBBA", "LA CHEBBA", "5170"),
        ("MAHDIA", "CHIBA MAHDIA", "LA CHEBBA", "5170"),
        ("MAHDIA", "RAJICH", "REJICHE", "5121"),
        ("MAHDIA", "RJICH", "REJICHE", "5121"),
        ("MAHDIA", "REJICHE MAHDIA", "REJICHE", "5121"),
        ("MONASTIR", "BANANE", "BENNANE", "5025"),
        ("MONASTIR", "BANNANE MONASTIR", "BENNANE", "5025"),
        ("MONASTIR", "BENNENE", "BENNANE", "5025"),
    ]
    for gouvernorat, localite, expected_localite, expected_cp in cases:
        row = pd.Series({
            "gouvernorat": gouvernorat,
            "localite": localite,
            "regsini_hint": None,
            "code_postal": None,
            "rue": None,
        })

        result = _resolve_one_geo_row(row, reference_indexes, corrections_by_key={}, alias_dict={})

        assert result["gouvernorat"] == gouvernorat
        assert result["localite"] == expected_localite
        assert result["code_postal"] == expected_cp
        assert result["geo_quality_level"] == "VALIDATED"


def test_untrusted_cross_governorate_localite_is_not_kept_as_final_localite():
    hammamet = _postal_ref("NABEUL", "HAMMAMET", "HAMMAMET", "8050")
    reference_indexes = {
        "postal": {},
        "postal_localite": {("NABEUL", "HAMMAMET"): [hammamet]},
        "postal_alias": {},
        "postal_delegation": {("NABEUL", "HAMMAMET"): [hammamet]},
        "postal_localite_global": {"HAMMAMET": [hammamet]},
        "postal_localite_linguistic_global": {},
        "postal_delegation_global": {"HAMMAMET": [hammamet]},
    }
    row = pd.Series({
        "gouvernorat": "SFAX",
        "localite": "HAMMAMET",
        "regsini_hint": None,
        "code_postal": None,
        "rue": None,
    })

    result = _resolve_one_geo_row(row, reference_indexes, corrections_by_key={}, alias_dict={})

    assert result["gouvernorat"] == "SFAX"
    assert result["localite"] is None
    assert result["code_postal"] is None
    assert result["geo_quality_level"] == "PARTIAL"
    assert result["resolution_method"] == "UNTRUSTED_SOURCE_LOCALITE"


def test_point_of_interest_is_kept_as_address_fragment_not_localite():
    sfax = _postal_ref("SFAX", "SFAX VILLE", "SFAX", "3000")
    reference_indexes = {
        "postal": {},
        "postal_localite": {("SFAX", "SFAX"): [sfax]},
        "postal_alias": {},
        "postal_delegation": {},
    }
    row = pd.Series({
        "gouvernorat": "SFAX",
        "localite": "HOPITAL HABIB BOURGUIBA SFAX",
        "regsini_hint": None,
        "code_postal": None,
        "rue": None,
    })

    result = _resolve_one_geo_row(row, reference_indexes, corrections_by_key={}, alias_dict={})

    assert result["gouvernorat"] == "SFAX"
    assert result["localite"] is None
    assert result["adresse_fragment"] == "HOPITAL HABIB BOURGUIBA SFAX"
    assert result["geo_quality_level"] == "PARTIAL"


# ---------------------------------------------------------------------------
# _linguistic_key_for_localite: Tunisian typo/transliteration families
# ---------------------------------------------------------------------------

def test_linguistic_key_converges_jebeniana_family():
    variants = ["DJEBENIANA SFAX", "DJEBENIENA", "DJEBINIANA", "DJEBINIANA SFAX", "JEBENIANA"]
    keys = {_linguistic_key_for_localite(v) for v in variants}
    assert len(keys) == 1


def test_linguistic_key_converges_chebba_family():
    variants = ["CHEBBA MAHDIA", "CHIBA MAHDIA", "ECHABBA", "ECHEBBA", "LA CHEBBA"]
    keys = {_linguistic_key_for_localite(v) for v in variants}
    assert len(keys) == 1


def test_linguistic_key_converges_rejiche_family():
    variants = ["RAJICH", "RJICH", "REJICH MAHDIA", "REJICHE MAHDIA", "REJICHE"]
    keys = {_linguistic_key_for_localite(v) for v in variants}
    assert len(keys) == 1


def test_linguistic_key_converges_bennane_family():
    variants = [
        "BANANE", "BANEN", "BANENE", "BANNAN", "BANNAN MONASTIR", "BANNANE",
        "BANNANE MONASTIR", "BANNEN", "BANNENE", "BENANA", "BENANE MONASTIR",
        "BENNAME", "BENNEN", "BENNENE", "BENNANE",
    ]
    keys = {_linguistic_key_for_localite(v) for v in variants}
    assert len(keys) == 1


def test_linguistic_key_does_not_merge_benbla_into_bennane():
    # BENBLA is close to BENNANE by edit distance, but Monastir has a real,
    # distinct locality "Bembla" (postal 5021/5022/5032/5036/5076) separate
    # from "Bennane" (postal 5025). Merging them would conflate two different
    # real places, so BENBLA must stay out of the BENNANE family.
    assert _linguistic_key_for_localite("BENBLA") != _linguistic_key_for_localite("BENNANE")


def test_linguistic_key_does_not_merge_unrelated_governorate_names():
    # Cross-governorate false pairs (e.g. SFAX vs HAMMAMET/NABEUL) must never
    # collapse to the same linguistic key regardless of fuzzy closeness.
    assert _linguistic_key_for_localite("HAMMAMET") != _linguistic_key_for_localite("BENNANE")


def test_linguistic_key_still_resolves_existing_documented_variants():
    # Non-regression: families already documented in the function's docstring
    # before this change must keep converging.
    assert (
        _linguistic_key_for_localite("ARIANA ESOGHRA")
        == _linguistic_key_for_localite("ARIANA ESSOGHRA")
        == _linguistic_key_for_localite("ARIANA SOGHRA")
        == _linguistic_key_for_localite("ARIANA SOUGHRA")
    )
    assert _linguistic_key_for_localite("EL MENZAH") == _linguistic_key_for_localite("MANZEH")


def test_resolves_jebeniana_typo_family_when_governorate_already_known():
    # DJEBENIANA/DJEBENIENA/DJEBINIANA are canonicalized to JEBENIANA upstream
    # by _apply_tunisian_localite_variant_rules (via _localite_match_terms),
    # so this resolves as an exact DimRegion match, not a fuzzy/linguistic one.
    ref = _postal_ref("SFAX", "JEBENIANA", "JEBENIANA", "3080")
    reference_indexes = {
        "postal": {},
        "postal_localite": {("SFAX", "JEBENIANA"): [ref]},
        "postal_alias": {},
        "postal_delegation": {},
    }
    row = pd.Series({
        "gouvernorat": "SFAX",
        "localite": "DJEBENIANA SFAX",
        "regsini_hint": None,
        "code_postal": None,
        "rue": None,
    })

    result = _resolve_one_geo_row(row, reference_indexes, corrections_by_key={}, alias_dict={})

    assert result["resolution_status"].startswith("STEP1_GOUVSINI_DIMREGION_EXACT_LOCALITE")
    assert result["gouvernorat"] == "SFAX"
    assert result["localite"] == "JEBENIANA"
    assert result["code_postal"] == "3080"
    assert result["geo_quality_level"] == "VALIDATED"


def test_resolves_localite_via_linguistic_key_when_governorate_already_known():
    # ARIANA ESOGHRA-style variants are only covered by the generic letter
    # collapsing inside _linguistic_key_for_localite (not by the exact-text
    # variant rules), so this genuinely exercises the DIMREGION_LINGUISTIC_LOCALITE
    # fallback path inside _canonicalize_localite_with_dimregion.
    ref = _postal_ref("ARIANA", "ARIANA VILLE", "ARIANA SOGRA", "2080")
    reference_indexes = {
        "postal": {},
        "postal_localite": {("ARIANA", "ARIANA SOGRA"): [ref]},
        "postal_alias": {},
        "postal_delegation": {},
    }
    row = pd.Series({
        "gouvernorat": "ARIANA",
        "localite": "ARIANA ESOGHRA",
        "regsini_hint": None,
        "code_postal": None,
        "rue": None,
    })

    result = _resolve_one_geo_row(row, reference_indexes, corrections_by_key={}, alias_dict={})

    assert result["resolution_status"].startswith("STEP1_GOUVSINI_DIMREGION_LINGUISTIC_LOCALITE")
    assert result["gouvernorat"] == "ARIANA"
    assert result["localite"] == "ARIANA SOGRA"
    assert result["code_postal"] == "2080"
    assert result["geo_quality_level"] == "VALIDATED"
