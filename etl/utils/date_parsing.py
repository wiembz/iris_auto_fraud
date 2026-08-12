"""
etl/utils/date_parsing.py
=========================
Parsing robuste des dates sources BNA/STAFIM, partagé entre le preprocessing
et les loaders DWH.

Les exports BNA encodent les dates en entiers YYYYMMDD (ex. 20160314).
Deux pièges pandas sur ce format :

  - pd.to_datetime("20160111", dayfirst=True) -> 2016-11-01 (lu YYYY-JJ-MM :
    jour et mois inversés dès que le jour réel <= 12) ;
  - pd.to_datetime(20170515) sur un entier -> interprété en nanosecondes
    epoch -> 1970-01-01.

Règles appliquées ici :
  - datetime/Timestamp : inchangé ;
  - entier/float/chaîne à 8 chiffres : format explicite %Y%m%d
    (calendrier invalide -> NaT ; les sentinelles type 29991231 "sans fin"
    restent des dates valides, filtrées ensuite par les bornes de dim_date) ;
  - placeholders (None, NaN, 0, '', '00000000'...) : NaT ;
  - autres chaînes : dayfirst=True (exports français jj/mm/aaaa).
"""
from __future__ import annotations

import re
from datetime import datetime

import numpy as np
import pandas as pd

_PLACEHOLDERS = {"", "0", "00000000", "nan", "NaT", "None", "NULL"}

_YYYYMMDD_RE = re.compile(r"(\d{8})(?:\.0+)?$")


def parse_date_value(value: object) -> pd.Timestamp:
    """Parse une valeur date source vers Timestamp (ou NaT)."""
    if value is None:
        return pd.NaT
    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value)
    if isinstance(value, bool):
        return pd.NaT
    if isinstance(value, (int, float, np.integer, np.floating)):
        if isinstance(value, (float, np.floating)) and (np.isnan(value) or value == 0):
            return pd.NaT
        if float(value).is_integer():
            s = str(int(value))
            if s == "0":
                return pd.NaT
            if len(s) == 8:
                return pd.to_datetime(s, format="%Y%m%d", errors="coerce")
        return pd.NaT
    s = str(value).strip()
    if s in _PLACEHOLDERS:
        return pd.NaT
    match = _YYYYMMDD_RE.fullmatch(s)
    if match:
        return pd.to_datetime(match.group(1), format="%Y%m%d", errors="coerce")
    try:
        return pd.to_datetime(s, dayfirst=True, errors="coerce")
    except Exception:
        return pd.NaT


def parse_date_series(series: pd.Series | None, index=None) -> pd.Series:
    """Version Series de parse_date_value (dtype datetime64, unité pandas)."""
    if series is None:
        return pd.Series(pd.NaT, index=index, dtype="datetime64[ns]")
    return pd.to_datetime(series.map(parse_date_value), errors="coerce")
