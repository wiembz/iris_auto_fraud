"""
etl/powerbi/create_powerbi_views.py
===================================
Creates (or replaces) the read-only Power BI views in schema `powerbi_v`.

The views are the ONLY objects Power BI reads: no mart/dwh table is exposed
directly, no table is created or modified, no score is recomputed. The DDL
lives in `create_powerbi_views.sql` next to this script.

After creation, each view is smoke-tested with a LIMIT 1 read and the
governance view content is logged (component, version, run_id, row_count).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "etl" / "dwh"))

SQL_PATH = Path(__file__).with_name("create_powerbi_views.sql")

EXPECTED_VIEWS = [
    "v_score_version_config",
    "v_current_run",
    "v_claim_attention_guarantee",
    "v_dossier_attention",
    "v_signal_detail",
    "v_client_cohort",
    "v_inspection",
    "v_inspection_checkpoint_defect",
    "v_vhs_score",
    "v_post_inspection_signal",
    "v_ml_anomaly",
    "v_quality_kpis",
    "v_governance",
]


def _load_dwh_utils():
    import dwh_utils
    return dwh_utils


def main() -> int:
    dwh_utils = _load_dwh_utils()
    run_id = f"POWERBI_VIEWS_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    logger = dwh_utils.setup_logging(run_id, log_name="create_powerbi_views")
    logger.info("=" * 70)
    logger.info(f"[RUN] {run_id}")
    logger.info("      read-only restitution views for Power BI; no table write")
    logger.info("=" * 70)

    sql = SQL_PATH.read_text(encoding="utf-8")
    engine = dwh_utils.build_engine(logger)

    with engine.begin() as conn:
        conn.exec_driver_sql(sql)
    logger.info(f"[OK] DDL executed from {SQL_PATH.name}")

    failures: list[str] = []
    with engine.connect() as conn:
        for view in EXPECTED_VIEWS:
            try:
                conn.execute(text(f"SELECT * FROM powerbi_v.{view} LIMIT 1"))
                logger.info(f"[OK] powerbi_v.{view} readable")
            except Exception as exc:  # noqa: BLE001 - report every broken view
                failures.append(view)
                logger.error(f"[KO] powerbi_v.{view}: {exc}")

        if not failures:
            governance = conn.execute(
                text("SELECT component, version, run_id, row_count FROM powerbi_v.v_governance ORDER BY component")
            ).fetchall()
            logger.info("[GOVERNANCE] components exposed to Power BI:")
            for row in governance:
                logger.info(f"    {row.component}: version={row.version} run={row.run_id} rows={row.row_count}")

    if failures:
        logger.error(f"[FAIL] {len(failures)} view(s) not readable: {failures}")
        return 1
    logger.info(f"[DONE] {len(EXPECTED_VIEWS)} views ready in schema powerbi_v")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
