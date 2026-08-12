"""
etl/dwh/dwh_utils.py
=====================
Utilitaires communs pour le chargement Data Warehouse PostgreSQL.

Fonctions :
  setup_logging    — logger fichier UTF-8 + console (delegue a etl.utils.runtime)
  build_engine     — SQLAlchemy engine via URL.create + .env (etl.utils.runtime)
  normalize_numcnt — normalisation des identifiants contrat
  create_dwh_schema — CREATE SCHEMA IF NOT EXISTS dwh
  write_to_dwh     — DROP/CREATE (schema) + COPY natif (donnees), mode replace
"""
from __future__ import annotations

import logging
import re
import sys
from datetime import datetime, timezone
from io import StringIO
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
    chunksize: int = 100_000,
) -> tuple[int, float]:
    """
    Charge df dans dwh.<table_name> en mode replace.

    Schema (DROP/CREATE) via to_sql sur un DataFrame vide (rapide, dtypes
    corrects) ; donnees via COPY natif Postgres (psycopg2 copy_expert),
    memes idiomes que _copy_frame_to_db() dans les scripts mart
    (compute_claim_attention_hybrid_score_v1_candidate.py et consorts) :
    CSV tabule en memoire, sentinelle NULL '\\N', colonnes datetime
    formatees explicitement. Remplace l'ancien to_sql(method="multi") --
    des INSERT par lots de 5000 lignes via psycopg2 -- mesure ~x10 plus
    lent que COPY sur les tables de plusieurs centaines de milliers de
    lignes de ce projet (voir docs/soutenance/LIMITES_SCALABILITE_PERSPECTIVES.md).

    Colonnes dtype object contenant uniquement des Timestamp/date (et NaN) --
    frequent quand une ligne technique est construite via pd.DataFrame([{...
    "col": None ...}]) puis pd.concat() avec un bloc deja en datetime64, ce
    qui retombe en object -- sont detectees et reconverties en datetime64
    AVANT le schema (sinon to_sql(df.head(0)) n'a aucune valeur a inspecter
    et cree une colonne TEXT plutot que TIMESTAMP ; les dates y sont alors
    stockees en texte ISO puis re-parsees ailleurs avec dayfirst=True, qui
    inverse jour/mois silencieusement -- bug reel trouve le 2026-08-12,
    cause de l'anomalie conducteur_sk=0 : voir memoire de session).

    Retourne (n_rows, elapsed_seconds).
    """
    full_name = f"dwh.{table_name}"
    t0 = datetime.now(timezone.utc)

    export = df.copy()
    for col in export.columns:
        if export[col].dtype == object:
            non_null = export[col].dropna()
            if len(non_null) > 0 and non_null.map(lambda v: isinstance(v, (pd.Timestamp, datetime))).all():
                export[col] = pd.to_datetime(export[col])

    export.head(0).to_sql(
        table_name,
        engine,
        schema="dwh",
        if_exists="replace",
        index=False,
    )

    n = len(export)
    if n > 0:
        columns = list(export.columns)
        columns_sql = ", ".join(f'"{c}"' for c in columns)
        copy_sql = (
            f"COPY {full_name} ({columns_sql}) "
            f"FROM STDIN WITH (FORMAT CSV, HEADER FALSE, DELIMITER E'\\t', NULL '\\N')"
        )

        datetime_cols = export.select_dtypes(include=["datetime64[ns]", "datetimetz"]).columns
        for col in datetime_cols:
            export[col] = export[col].dt.strftime("%Y-%m-%d %H:%M:%S.%f")

        raw_conn = engine.raw_connection()
        try:
            with raw_conn.cursor() as cursor:
                for start in range(0, n, chunksize):
                    chunk = export.iloc[start:start + chunksize]
                    buffer = StringIO()
                    chunk.to_csv(
                        buffer,
                        sep="\t",
                        header=False,
                        index=False,
                        na_rep="\\N",
                        lineterminator="\n",
                    )
                    buffer.seek(0)
                    cursor.copy_expert(copy_sql, buffer)
            raw_conn.commit()
        except Exception:
            raw_conn.rollback()
            raise
        finally:
            raw_conn.close()

    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    logger.info(
        f"[LOAD] {full_name} : {n} lignes x {df.shape[1]} cols en {elapsed:.1f}s"
    )
    return n, elapsed


