import pandas as pd

from etl.utils.vehicle_normalization import normalize_immatriculation


class TestNormalizeImmatriculation:
    def test_missing_and_placeholder_values_return_none(self):
        for value in [
            None,
            pd.NA,
            "",
            "   ",
            "0",
            "000000",
            "nan",
            "NULL",
            "non renseigné",
            "NEANT",
            "PIETON",
            "MOBYLETTE",
            "NON ASSURE",
        ]:
            assert normalize_immatriculation(value) is None

    def test_trim_uppercase_and_remove_obvious_separators(self):
        assert normalize_immatriculation(" 4639tu204 ") == "4639TU204"
        assert normalize_immatriculation("4639 TU 204") == "4639TU204"
        assert normalize_immatriculation("4639-TU-204") == "4639TU204"
        assert normalize_immatriculation("4639/TU/204") == "4639TU204"
        assert normalize_immatriculation("4639.TU.204") == "4639TU204"

    def test_numeric_values_are_preserved_without_tu_heuristic(self):
        assert normalize_immatriculation(1234) == "1234"
        assert normalize_immatriculation(1234.0) == "1234"
        assert normalize_immatriculation("1234.0") == "1234"
        assert normalize_immatriculation("1234567") == "1234567"

    def test_existing_rs_and_nt_inversions_are_preserved(self):
        assert normalize_immatriculation("RS1234") == "RS1234"
        assert normalize_immatriculation("1234RS") == "RS1234"
        assert normalize_immatriculation("1234NT") == "1234NT"
        assert normalize_immatriculation("NT1234") == "1234NT"

    def test_existing_cautious_tu_inversion_is_preserved(self):
        assert normalize_immatriculation("567TU1234") == "1234TU567"
        assert normalize_immatriculation("4639TU204") == "4639TU204"
        assert normalize_immatriculation("429TU146") == "429TU146"
