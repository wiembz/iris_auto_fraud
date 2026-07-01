"""
etl/staging_area/load_production_sa.py
=======================================
Charge enriched_production.xlsx -> staging.stg_production.

Usage autonome :
  python etl/staging_area/load_production_sa.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sa_utils

SOURCE_FILE = "enriched_production.xlsx"
SCHEMA      = "staging"
TABLE_NAME  = "stg_production"


def load_production_sa(
    run_id: str,
    engine,
    logger: logging.Logger,
) -> int:
    """
    Lit enriched_production.xlsx, ajoute les colonnes techniques,
    charge staging.stg_production, ecrit une ligne d'audit.
    Retourne le nombre de lignes chargees.
    """
    path = sa_utils.DATA_PROC / SOURCE_FILE
    logger.info(f"[READ] {SOURCE_FILE}")
    df = pd.read_excel(path)
    logger.info(f"  {len(df)} lignes x {df.shape[1]} cols")

    df = sa_utils.add_technical_columns(df, SOURCE_FILE, run_id)

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
    _logger = sa_utils.setup_logging(_run_id, log_name="load_production_sa")
    _engine = sa_utils.build_engine(_logger)
    sa_utils.create_schemas(_engine, _logger)
    _n = load_production_sa(_run_id, _engine, _logger)
    _logger.info(f"Termine : {_n} lignes -> {SCHEMA}.{TABLE_NAME}")
