"""
etl/dwh/dwh_utils.py
=====================
Utilitaires communs pour le chargement Data Warehouse PostgreSQL.

Fonctions :
  setup_logging    — logger fichier UTF-8 + console (delegue a etl.utils.runtime)
  build_engine     — SQLAlchemy engine via URL.create + .env (etl.utils.runtime)
  normalize_numcnt — normalisation des identifiants contrat
  create_dwh_schema — CREATE SCHEMA IF NOT EXISTS dwh
  write_to_dwh     — to_sql mode replace avec chunksize
"""
from __future__ import annotations

import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

# ---------------------------------------------------------------------------
# Chemins projet
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOGS_DIR = BASE_DIR / "logs"

LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Shared runtime helpers. Loaders run this module both standalone
# (sys.path = etl/dwh) and as part of the etl package (pytest/orchestrator),
# so fall back to inserting the repo root when the package form fails.
try:
    from etl.utils.runtime import build_engine as _runtime_build_engine
    from etl.utils.runtime import setup_logging as _runtime_setup_logging
except ModuleNotFoundError:  # standalone script execution
    sys.path.insert(0, str(BASE_DIR))
    from etl.utils.runtime import build_engine as _runtime_build_engine
    from etl.utils.runtime import setup_logging as _runtime_setup_logging



# ---------------------------------------------------------------------------
# Shared business-key normalization
# ---------------------------------------------------------------------------
def normalize_numcnt(value) -> str | None:
    """
    Normalize contract identifiers without destroying business information.

    Rules:
    - preserve identifiers as strings;
    - trim and uppercase;
    - remove Excel numeric artifacts only when safe, e.g. 123.0 -> 123;
    - preserve historical slash formats such as 20161.0000002/1;
    - return None for empty / NULL / NAN / UNKNOWN-like values.
    """
    if value is None or pd.isna(value):
        return None

    text = str(value).strip().upper()
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*/\s*", "/", text)

    invalid = {
        "",
        "NULL",
        "NAN",
        "NONE",
        "UNKNOWN",
        "INCONNU",
        "INCONNUE",
        "NON RENSEIGNE",
        "NON RENSEIGNEE",
        "N/A",
        "NA",
        "#N/A",
        "0",
        "0.0",
        "0,0",
    }
    if text in invalid:
        return None

    # Numeric Python/Excel values are safe to shorten only when truly integral.
    if not isinstance(value, str):
        try:
            number = float(value)
            if number.is_integer():
                return str(int(number))
        except (TypeError, ValueError):
            pass

    # Safe textual Excel artifacts: 123.0 / 123,0 / 123.000 -> 123.
    # Do not apply to slash-based or non-zero decimal identifiers.
    if "/" not in text:
        match = re.fullmatch(r"([A-Z0-9]+)[\.,]0+", text)
        if match:
            return match.group(1)

    return text or None
# ---------------------------------------------------------------------------
# Logging (delegue a etl.utils.runtime, namespace "dwh")
# ---------------------------------------------------------------------------
def setup_logging(run_id: str, log_name: str = "load_dwh") -> logging.Logger:
    """Configure un logger avec handler fichier UTF-8 et handler console."""
    return _runtime_setup_logging(run_id, log_name=log_name, namespace="dwh")


# ---------------------------------------------------------------------------
# Connexion PostgreSQL (delegue a etl.utils.runtime)
# ---------------------------------------------------------------------------
def build_engine(logger: logging.Logger | None = None):
    """Charge .env et construit l'engine SQLAlchemy avec URL.create."""
    return _runtime_build_engine(logger)


# ---------------------------------------------------------------------------
# Schema DWH
# ---------------------------------------------------------------------------
def create_dwh_schema(engine, logger: logging.Logger | None = None) -> None:
    """Cree le schema dwh s'il n'existe pas."""
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS dwh"))
    if logger:
        logger.info("Schema 'dwh' : OK")


# ---------------------------------------------------------------------------
# Chargement PostgreSQL
# ---------------------------------------------------------------------------
def write_to_dwh(
    df: pd.DataFrame,
    engine,
    table_name: str,
    logger: logging.Logger,
    chunksize: int = 5000,
) -> tuple[int, float]:
    """
    Charge df dans dwh.<table_name> en mode replace.
    Retourne (n_rows, elapsed_seconds).
    """
    full_name = f"dwh.{table_name}"
    t0 = datetime.now(timezone.utc)
    df.to_sql(
        table_name,
        engine,
        schema="dwh",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=chunksize,
    )
    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    n = len(df)
    logger.info(
        f"[LOAD] {full_name} : {n} lignes x {df.shape[1]} cols en {elapsed:.1f}s"
    )
    return n, elapsed


