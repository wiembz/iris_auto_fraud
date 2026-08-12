import pandas as pd

from etl.staging_area.prepare_inspection_sa import transform_inspection


class DummyLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))


def test_prepare_inspection_preserves_bracketed_motorisation_column():
    df, metrics = transform_inspection(
        pd.DataFrame(
            [
                {
                    "immatriculation": "1234 TU 567",
                    "vin": " vin-001 ",
                    " [MOTORISATION]": " diesel ",
                }
            ]
        ),
        DummyLogger(),
    )

    assert len(df) == 1
    assert df.loc[0, "immatriculation"] == "1234TU567"
    assert df.loc[0, "vin"] == "VIN-001"
    assert df.loc[0, "motorisation"] == "DIESEL"
    assert metrics["n_valid_for_join"] == 1