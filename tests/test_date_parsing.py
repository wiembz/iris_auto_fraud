import numpy as np
import pandas as pd
import pytest

from etl.utils.date_parsing import parse_date_value, parse_date_series


class TestParseDateValueYYYYMMDD:
    def test_int_yyyymmdd_day_below_13_not_swapped(self):
        # Le bug historique : 20160111 lu "2016-11-01" avec dayfirst=True
        assert parse_date_value(20160111) == pd.Timestamp("2016-01-11")

    def test_int_yyyymmdd_day_above_12(self):
        assert parse_date_value(20160314) == pd.Timestamp("2016-03-14")

    def test_float_yyyymmdd(self):
        assert parse_date_value(20170515.0) == pd.Timestamp("2017-05-15")

    def test_string_yyyymmdd(self):
        assert parse_date_value("20160111") == pd.Timestamp("2016-01-11")

    def test_string_yyyymmdd_excel_artifact(self):
        assert parse_date_value("20160111.0") == pd.Timestamp("2016-01-11")

    def test_int_not_epoch_nanoseconds(self):
        # Le bug dim_contrat : entier interprété en ns epoch -> 1970-01-01
        ts = parse_date_value(20170515)
        assert ts.year == 2017

    def test_invalid_calendar_yyyymmdd_is_nat(self):
        assert pd.isna(parse_date_value(62000016))  # mois 00

    def test_sentinel_no_end_date_stays_valid(self):
        # 2999... = sentinelle "sans fin" BNA ; reste une date, filtrée
        # ensuite par les bornes de dim_date (2010-2035) -> date_sk = 0
        assert parse_date_value(29991028) == pd.Timestamp("2999-10-28")


class TestParseDateValuePlaceholders:
    @pytest.mark.parametrize("value", [None, 0, 0.0, "", "0", "00000000", "nan", "None", float("nan"), np.nan])
    def test_placeholder_is_nat(self, value):
        assert pd.isna(parse_date_value(value))

    def test_bool_is_nat(self):
        assert pd.isna(parse_date_value(True))


class TestParseDateValueStringsAndDatetimes:
    def test_french_string_dayfirst(self):
        assert parse_date_value("06/02/2024") == pd.Timestamp("2024-02-06")

    def test_iso_string(self):
        assert parse_date_value("2016-03-14") == pd.Timestamp("2016-03-14")

    def test_timestamp_passthrough(self):
        ts = pd.Timestamp("2020-05-01 10:30:00")
        assert parse_date_value(ts) == ts

    def test_garbage_string_is_nat(self):
        assert pd.isna(parse_date_value("LOCATION DE VOITURE FLOTTE"))


class TestParseDateSeries:
    def test_mixed_series(self):
        s = pd.Series([20160111, "14/03/2016", None, 0, "20180511"])
        out = parse_date_series(s)
        assert out.dtype.kind == "M"  # datetime64, unité pandas (ns ou us)
        assert out.iloc[0] == pd.Timestamp("2016-01-11")
        assert out.iloc[1] == pd.Timestamp("2016-03-14")
        assert pd.isna(out.iloc[2])
        assert pd.isna(out.iloc[3])
        assert out.iloc[4] == pd.Timestamp("2018-05-11")

    def test_none_series_returns_nat_with_index(self):
        idx = pd.RangeIndex(3)
        out = parse_date_series(None, index=idx)
        assert len(out) == 3
        assert out.isna().all()
