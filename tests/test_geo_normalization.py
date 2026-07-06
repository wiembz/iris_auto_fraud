from etl.utils.geo_normalization import (
    normalize_geo_text,
    normalize_numeric_code,
    normalize_postal_code,
)


class TestNormalizeGeoText:
    def test_none_returns_none(self):
        assert normalize_geo_text(None) is None

    def test_empty_and_spaces_return_none(self):
        assert normalize_geo_text("") is None
        assert normalize_geo_text("   ") is None

    def test_mixed_case_and_outer_spaces(self):
        assert normalize_geo_text(" Tunis ") == "TUNIS"

    def test_double_spaces_are_collapsed(self):
        assert normalize_geo_text("Ben  Arous") == "BEN AROUS"

    def test_non_informative_values_return_none(self):
        for value in ["N/A", "NA", "-", "--", ".", "NULL", "NONE"]:
            assert normalize_geo_text(value) is None

    def test_unknown_values_return_unknown(self):
        for value in ["UNKNOWN", "INCONNU", "INCONNUE", "NON RENSEIGNE", "non renseigné"]:
            assert normalize_geo_text(value) == "UNKNOWN"

    def test_accents_are_preserved(self):
        assert normalize_geo_text(" béja ") == "BÉJA"


class TestNormalizePostalCode:
    def test_integer(self):
        assert normalize_postal_code(1000) == "1000"

    def test_excel_float(self):
        assert normalize_postal_code(1000.0) == "1000"

    def test_excel_float_string(self):
        assert normalize_postal_code("1000.0") == "1000"

    def test_text_with_spaces(self):
        assert normalize_postal_code(" 1000 ") == "1000"
        assert normalize_postal_code("10 00") == "1000"

    def test_leading_zero_is_preserved_for_text(self):
        assert normalize_postal_code("0100") == "0100"

    def test_empty_and_non_informative(self):
        assert normalize_postal_code("") is None
        assert normalize_postal_code("   ") is None
        assert normalize_postal_code("N/A") is None
        assert normalize_postal_code("NA") is None
        assert normalize_postal_code("-") is None

    def test_unknown_values_return_unknown(self):
        for value in ["UNKNOWN", "INCONNU", "INCONNUE", "NON RENSEIGNE", "NON RENSEIGNÉ"]:
            assert normalize_postal_code(value) == "UNKNOWN"


class TestNormalizeNumericCode:
    def test_integer(self):
        assert normalize_numeric_code(12) == "12"

    def test_integer_float(self):
        assert normalize_numeric_code(12.0) == "12"

    def test_numeric_string(self):
        assert normalize_numeric_code("12") == "12"

    def test_numeric_string_with_spaces(self):
        assert normalize_numeric_code(" 12 ") == "12"
        assert normalize_numeric_code("1 2") == "12"

    def test_excel_float_string(self):
        assert normalize_numeric_code("12.0") == "12"

    def test_empty_and_non_informative(self):
        assert normalize_numeric_code("") is None
        assert normalize_numeric_code("   ") is None
        assert normalize_numeric_code("N/A") is None
        assert normalize_numeric_code("NA") is None
        assert normalize_numeric_code("-") is None

    def test_unknown_values_return_unknown(self):
        for value in ["UNKNOWN", "INCONNU", "INCONNUE", "NON RENSEIGNE", "NON RENSEIGNÉ"]:
            assert normalize_numeric_code(value) == "UNKNOWN"
