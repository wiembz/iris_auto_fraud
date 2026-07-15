import pandas as pd

from etl.dwh.load_dim_vehicule import (
    FINAL_COLS,
    SOURCE_SYSTEM_BOTH,
    SOURCE_SYSTEM_CLAIM,
    SOURCE_SYSTEM_INSPECTION,
    transform_dim_vehicule,
)


class DummyLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))


def _inspection_df(rows):
    return pd.DataFrame(rows)


def _claim_df(rows):
    return pd.DataFrame(rows)


def _split_technical(df):
    """Sépare la ligne technique UNKNOWN (vehicule_sk = 0) des véhicules réels."""
    technical = df[df["vehicule_sk"] == 0]
    real = df[df["vehicule_sk"] != 0].reset_index(drop=True)
    return technical, real


def test_transform_always_emits_unknown_technical_row():
    df = transform_dim_vehicule(
        _inspection_df([]),
        DummyLogger(),
        _claim_df([{"immat": "4639 TU 204"}]),
    )

    technical, _ = _split_technical(df)
    assert len(technical) == 1
    row = technical.iloc[0]
    assert row["immatriculation"] == "UNKNOWN"
    assert row["source_system"] == "TECHNICAL"
    assert pd.isna(row["vin"])
    assert pd.isna(row["motorisation"])


def test_inspection_only_vehicle_preserves_vin_and_motorisation():
    df = transform_dim_vehicule(
        _inspection_df(
            [
                {
                    "immatriculation": " 1234 tu 567 ",
                    "vin": " vin-001 ",
                    "motorisation": " diesel ",
                    "date_inspection": "2024-03-01",
                    "horodateur": "2024-03-01 09:00:00",
                }
            ]
        ),
        DummyLogger(),
        _claim_df([]),
    )

    assert list(df.columns) == FINAL_COLS
    _, real = _split_technical(df)
    assert len(real) == 1
    row = real.iloc[0]
    assert row["immatriculation"] == "1234TU567"
    assert row["vin"] == "VIN-001"
    assert row["motorisation"] == "DIESEL"
    assert row["source_system"] == SOURCE_SYSTEM_INSPECTION


def test_claim_only_vehicle_is_kept_without_vin_or_motorisation():
    df = transform_dim_vehicule(
        _inspection_df([]),
        DummyLogger(),
        _claim_df([{"immat": "4639 TU 204"}]),
    )

    assert list(df.columns) == FINAL_COLS
    _, real = _split_technical(df)
    assert len(real) == 1
    row = real.iloc[0]
    assert row["immatriculation"] == "4639TU204"
    assert pd.isna(row["vin"])
    assert pd.isna(row["motorisation"])
    assert row["source_system"] == SOURCE_SYSTEM_CLAIM


def test_inspection_and_claim_duplicate_merge_to_one_vehicle():
    df = transform_dim_vehicule(
        _inspection_df(
            [
                {
                    "immatriculation": "4639-TU-204",
                    "vin": "VIN123",
                    "motorisation": "essence",
                    "date_inspection": "2024-03-01",
                    "horodateur": "2024-03-01 09:00:00",
                }
            ]
        ),
        DummyLogger(),
        _claim_df([{"immat": "4639 TU 204"}, {"immat": "4639TU204"}]),
    )

    assert list(df.columns) == FINAL_COLS
    _, real = _split_technical(df)
    assert len(real) == 1
    row = real.iloc[0]
    assert row["immatriculation"] == "4639TU204"
    assert row["vin"] == "VIN123"
    assert row["motorisation"] == "ESSENCE"
    assert row["source_system"] == SOURCE_SYSTEM_BOTH


def test_best_inspection_row_prefers_complete_vehicle_attributes():
    df = transform_dim_vehicule(
        _inspection_df(
            [
                {
                    "immatriculation": "9999TU111",
                    "vin": "VIN-OLD",
                    "motorisation": None,
                    "date_inspection": "2024-05-01",
                    "horodateur": "2024-05-01 09:00:00",
                },
                {
                    "immatriculation": "9999TU111",
                    "vin": "VIN-COMPLETE",
                    "motorisation": "hybride",
                    "date_inspection": "2024-04-01",
                    "horodateur": "2024-04-01 09:00:00",
                },
            ]
        ),
        DummyLogger(),
        _claim_df([]),
    )

    assert list(df.columns) == FINAL_COLS
    _, real = _split_technical(df)
    assert len(real) == 1
    row = real.iloc[0]
    assert row["vin"] == "VIN-COMPLETE"
    assert row["motorisation"] == "HYBRIDE"
    assert row["source_system"] == SOURCE_SYSTEM_INSPECTION


def test_invalid_immatriculations_do_not_create_dimension_rows():
    df = transform_dim_vehicule(
        _inspection_df([{"immatriculation": "0", "vin": "VIN", "motorisation": "diesel"}]),
        DummyLogger(),
        _claim_df([{"immat": "NON RENSEIGNE"}, {"immat": ""}]),
    )

    assert list(df.columns) == FINAL_COLS
    technical, real = _split_technical(df)
    assert len(technical) == 1
    assert real.empty
