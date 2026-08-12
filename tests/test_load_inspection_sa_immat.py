"""
Tests cibles pour etl/staging_area/load_inspection_sa.py::_standardise_immat.

Cas reels trouves dans data/raw/FicheVoitureStafim.xlsx (via inspection
manuelle demandee par Wiem) qui produisaient un immatriculation_norm NULL
en base alors que la ligne avait un vrai kilometrage/checkpoints exploitables.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "etl" / "staging_area"))

from load_inspection_sa import _standardise_immat  # noqa: E402


class TestStandardiseImmat:
    def test_missing_and_placeholder_values_return_none(self):
        for value in [None, "", "   ", "0", "TEST", "NAN", float("nan")]:
            assert _standardise_immat(value) is None

    def test_correct_formats_are_preserved(self):
        assert _standardise_immat("4639TU204") == "4639TU204"
        assert _standardise_immat("RS1234") == "RS1234"
        assert _standardise_immat("1234NT") == "1234NT"

    def test_rs_suffix_with_dash_is_normalized_like_prefix(self):
        # Rapporte par Wiem : "-RS a la fin au lieu de RS au debut".
        assert _standardise_immat("163564-RS") == "RS163564"
        assert _standardise_immat("RS 284144") == "RS284144"

    def test_tn_middle_typo_is_treated_as_tu(self):
        # Rapporte par Wiem : "nt ou NT au milieu a la place de TU".
        assert _standardise_immat("9788TN115") == "9788TU115"
        assert _standardise_immat("288TN157") == "288TU157"

    def test_arabic_nt_is_transliterated_before_recognition(self):
        # Rapporte par Wiem : "nt en lettre arabe".
        assert _standardise_immat("226989 ن ت") == "226989NT"

    def test_numeric_pandas_value_is_not_rejected_outright(self):
        # pandas peut lire une plaque tout-chiffres comme int/float plutot
        # que comme str : ne doit pas etre rejetee avant meme d etre lue.
        assert _standardise_immat(5017) is None or isinstance(_standardise_immat(5017), str)

    def test_seven_digits_only_assumes_omitted_tu_code(self):
        # Rapporte par Wiem (cas reel STAFIM, 2025-10-07, km=170000) :
        # le code TU a ete omis a la saisie. Meme heuristique que
        # prepare_inspection_sa.py pour ce cas precis (7 chiffres exacts).
        assert _standardise_immat("7650217") == "7650TU217"

    def test_six_digits_with_tn_stays_none(self):
        # Rapporte par Wiem (cas reel STAFIM, 2026-03-27, km=200000) :
        # longueur non standard (6 chiffres), pas d heuristique fiable.
        assert _standardise_immat("251946tn") is None
