import pandas as pd

from etl.dwh.load_dim_conducteur import (
    DEDUP_KEY,
    WEAK_PERMIS_ABNORMAL_USE_THRESHOLD,
    transform_dim_conducteur,
)


class DummyLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))


def _staging_df(rows):
    return pd.DataFrame(rows)


def _split_unknown(df):
    """Sépare la ligne technique UNKNOWN (conducteur_sk = 0) des conducteurs réels."""
    unknown = df[df["conducteur_sk"] == 0]
    real = df[df["conducteur_sk"] != 0].reset_index(drop=True)
    return unknown, real


def _row(numpermis=None, nomconduc=None, datnaicon=None, categperm=None, datepermi=None):
    return {
        "nomconduc": nomconduc,
        "datnaicon": datnaicon,
        "numpermis": numpermis,
        "categperm": categperm,
        "datepermi": datepermi,
        "dtdecsnt": "2025-01-01",
    }


def test_transform_always_emits_unknown_technical_row():
    df, _ = transform_dim_conducteur(_staging_df([_row(nomconduc="DUPONT JEAN")]), DummyLogger())

    unknown, _ = _split_unknown(df)
    assert len(unknown) == 1
    row = unknown.iloc[0]
    assert row["nom_conducteur"] == "UNKNOWN"
    assert row["source_system"] == "TECHNICAL"


# 1. Permis "1" sans autre identité, partagé par de nombreuses lignes → non retenu
def test_permis_generic_digit_shared_widely_excluded_from_real_drivers():
    rows = [_row(numpermis="1") for _ in range(WEAK_PERMIS_ABNORMAL_USE_THRESHOLD + 5)]
    df, metrics = transform_dim_conducteur(_staging_df(rows), DummyLogger())

    _, real = _split_unknown(df)
    assert "1" not in real["numero_permis"].tolist()
    assert metrics["n_identite_faible"] == len(rows)
    assert metrics["n_real_conducteur"] == 0


# 2. Permis "0", vide ou texte "UNKNOWN" → jamais retenu comme identité, quelle que soit la fréquence
def test_permis_placeholder_literals_excluded_even_when_rare():
    rows = [
        _row(numpermis="0"),
        _row(numpermis=None),
        _row(numpermis="UNKNOWN"),
        _row(numpermis="SANS COND"),
        _row(numpermis="STATIONNE"),
    ]
    df, metrics = transform_dim_conducteur(_staging_df(rows), DummyLogger())

    _, real = _split_unknown(df)
    assert len(real) == 0
    assert metrics["n_real_conducteur"] == 0


# 3. Numero_permis plausible, unique, sans nom → conservé comme identité distincte
def test_permis_plausible_and_rare_without_name_is_preserved():
    rows = [_row(numpermis="04TN881523")]
    df, metrics = transform_dim_conducteur(_staging_df(rows), DummyLogger())

    _, real = _split_unknown(df)
    assert len(real) == 1
    assert real.iloc[0]["numero_permis"] == "04TN881523"
    assert metrics["n_permis_seul_garde"] == 1
    assert metrics["n_identite_faible"] == 0


# 4. Conducteur avec nom et informations fiables → conservé
def test_driver_with_reliable_identity_is_preserved():
    rows = [
        _row(
            numpermis="12345",
            nomconduc="BEN ALI SAMIR",
            datnaicon="1985-04-12",
            categperm="B",
            datepermi="2006-01-10",
        )
    ]
    df, metrics = transform_dim_conducteur(_staging_df(rows), DummyLogger())

    _, real = _split_unknown(df)
    assert len(real) == 1
    assert real.iloc[0]["nom_conducteur"] == "BEN ALI SAMIR"
    assert metrics["n_real_conducteur"] == 1


# 5. Deux conducteurs réels distincts → deux clés (conducteur_sk) distinctes
def test_two_distinct_real_drivers_get_distinct_keys():
    rows = [
        _row(numpermis="P001", nomconduc="AAA", datnaicon="1980-01-01"),
        _row(numpermis="P002", nomconduc="BBB", datnaicon="1990-01-01"),
    ]
    df, _ = transform_dim_conducteur(_staging_df(rows), DummyLogger())

    _, real = _split_unknown(df)
    assert len(real) == 2
    assert real["conducteur_sk"].nunique() == 2
    assert set(real["nom_conducteur"]) == {"AAA", "BBB"}


# 6. Valeur générique utilisée par plusieurs lignes → jamais agrégée en un faux conducteur unique
def test_abnormally_shared_placeholder_never_creates_a_single_fake_driver():
    rows = [_row(numpermis="STATIONNE") for _ in range(WEAK_PERMIS_ABNORMAL_USE_THRESHOLD + 1)]
    df, metrics = transform_dim_conducteur(_staging_df(rows), DummyLogger())

    _, real = _split_unknown(df)
    assert len(real) == 0
    assert metrics["n_identite_faible"] == len(rows)


# 7 & 8. Mix réaliste : le conducteur_sk fantôme ne doit pas apparaître, un rare permis plausible
# reste bien isolé (grain fonctionnel distinct, pas de fusion avec la valeur suspecte)
def test_mixed_batch_isolates_rare_plausible_driver_from_generic_bucket():
    rows = (
        [_row(numpermis="1") for _ in range(50)]
        + [_row(numpermis="04TN881523")]
        + [_row(numpermis="12345", nomconduc="BEN ALI SAMIR", datnaicon="1985-04-12")]
    )
    df, metrics = transform_dim_conducteur(_staging_df(rows), DummyLogger())

    unknown, real = _split_unknown(df)
    assert len(unknown) == 1
    assert len(real) == 2
    assert set(real["numero_permis"]) == {"04TN881523", "12345"}
    assert metrics["n_identite_faible"] == 50
    assert metrics["duplicate_grain_count"] == 0
    assert real[DEDUP_KEY].duplicated().sum() == 0
