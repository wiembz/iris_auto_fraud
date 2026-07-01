"""
etl/staging_area/load_all_sa.py
=================================
Orchestrateur du chargement Staging Area PostgreSQL.

Ordre d'execution :
  1. staging.stg_production  <- enriched_production.xlsx
  2. staging.stg_sinistres   <- enriched_sinistres.xlsx
  3. staging.stg_clients     <- enriched_clients.xlsx
  4. staging.stg_inspection  <- enriched_inspection.xlsx

Usage :
  python etl/staging_area/load_all_sa.py

Log :
  logs/load_all_sa_<run_id>.log
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sa_utils
from load_production_sa  import load_production_sa
from load_sinistres_sa   import load_sinistres_sa
from load_clients_sa     import load_clients_sa
from load_inspection_sa  import load_inspection_sa


def main() -> None:
    run_id  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logger  = sa_utils.setup_logging(run_id, log_name="load_all_sa")
    started = datetime.now(timezone.utc)

    logger.info("=" * 70)
    logger.info(f"IRIS Auto Fraud | Staging Area Load | run_id : {run_id}")
    logger.info("=" * 70)

    engine = sa_utils.build_engine(logger)
    sa_utils.create_schemas(engine, logger)

    # Suivi des resultats par table
    results: dict[str, int | str] = {}
    global_status = "SUCCESS"

    steps = [
        ("stg_production",  load_production_sa),
        ("stg_sinistres",   load_sinistres_sa),
        ("stg_clients",     load_clients_sa),
        ("stg_inspection",  load_inspection_sa),
    ]

    for table_key, load_fn in steps:
        logger.info(f"--- {table_key} " + "-" * (60 - len(table_key)))
        try:
            n = load_fn(run_id, engine, logger)
            results[table_key] = n
        except Exception as exc:
            logger.error(f"[ERREUR] {table_key} : {exc}")
            logger.debug(traceback.format_exc())
            results[table_key] = "FAILED"
            global_status = "FAILED"
            # Ecriture audit erreur
            try:
                sa_utils.write_audit_row(
                    engine, run_id,
                    table_name=f"staging.{table_key}",
                    source_file="",
                    n_rows=0,
                    n_cols=0,
                    elapsed=0.0,
                    status="FAILED",
                    logger=logger,
                    error_msg=str(exc),
                )
            except Exception:
                pass

    elapsed_total = (datetime.now(timezone.utc) - started).total_seconds()

    # Résumé final
    logger.info("=" * 70)
    logger.info(f"RESUME | run_id : {run_id} | {elapsed_total:.1f}s | STATUS : {global_status}")
    for table_key, val in results.items():
        tag = f"{val} lignes" if isinstance(val, int) else val
        logger.info(f"  staging.{table_key:<25} {tag}")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
