"""
etl/staging_area/load_sinistres_sa.py
======================================
Charge enriched_sinistres.xlsx -> staging.stg_sinistres.

Usage autonome :
  python etl/staging_area/load_sinistres_sa.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sa_utils

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from etl.utils.geo_normalization import (
    normalize_geo_text,
    normalize_numeric_code,
    normalize_postal_code,
)

SOURCE_FILE = "enriched_sinistres.xlsx"
SCHEMA      = "staging"
TABLE_NAME  = "stg_sinistres"


def _find_column_case_insensitive(df: pd.DataFrame, column_name: str) -> str | None:
    matches = [col for col in df.columns if str(col).lower() == column_name.lower()]
    return matches[0] if matches else None


def add_geo_normalized_columns(df: pd.DataFrame, logger: logging.Logger) -> pd.DataFrame:
    """
    Add technical GEO normalization columns to the sinistres staging DataFrame.

    This keeps raw source columns unchanged and creates *_norm columns only.
    No business mapping is applied here.
    """
    geo_columns = [
        ("gouvsini",  "gouvsini_norm",  normalize_geo_text),
        ("citesini",  "citesini_norm",  normalize_geo_text),
        ("cpostsini", "cpostsini_norm", normalize_postal_code),
        ("iddelega",  "iddelega_norm",  normalize_numeric_code),
    ]

    for source_col, normalized_col, normalizer in geo_columns:
        found_col = _find_column_case_insensitive(df, source_col)
        if found_col:
            df[normalized_col] = df[found_col].map(normalizer)
            logger.info("[GEO NORM] Created column %s from %s", normalized_col, found_col)
        else:
            logger.warning(
                "[GEO NORM] Source column %s not found; %s not created",
                source_col, normalized_col,
            )

    return df


def load_sinistres_sa(
    run_id: str,
    engine,
    logger: logging.Logger,
) -> int:
    """
    Lit enriched_sinistres.xlsx, ajoute les colonnes techniques,
    charge staging.stg_sinistres, ecrit une ligne d'audit.
    Retourne le nombre de lignes chargees.
    """
    path = sa_utils.DATA_PROC / SOURCE_FILE
    logger.info(f"[READ] {SOURCE_FILE}")
    df = pd.read_excel(path)
    logger.info(f"  {len(df)} lignes x {df.shape[1]} cols")

    df = sa_utils.add_technical_columns(df, SOURCE_FILE, run_id)
    df = add_geo_normalized_columns(df, logger)

    n_rows, elapsed = sa_utils.write_to_postgres(
        df, engine, SCHEMA, TABLE_NAME, logger
    )

    sa_utils.write_audit_row(
        engine, run_id,
        table_name=f"{SCHEMA}.{TABLE_NAME}",
        source_file=SOURCE_FILE,
        n_rows=n_rows,
        n_cols=df.shape[1],
        elapsed=elapsed,
        status="SUCCESS",
        logger=logger,
    )

    return n_rows


if __name__ == "__main__":
    from datetime import datetime
    _run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    _logger = sa_utils.setup_logging(_run_id, log_name="load_sinistres_sa")
    _engine = sa_utils.build_engine(_logger)
    sa_utils.create_schemas(_engine, _logger)
    _n = load_sinistres_sa(_run_id, _engine, _logger)
    _logger.info(f"Termine : {_n} lignes -> {SCHEMA}.{TABLE_NAME}")
