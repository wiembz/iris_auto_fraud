"""
etl/orchestrate_full_recompute.py
==================================
Orchestrateur fail-fast pour un recalcul complet : DWH -> mart/scoring ->
vues Power BI.

Contexte : `load_all_dwh.py` echoue sur `load_dim_client`, `load_dim_geo`,
`load_fact_inspection_vehicule` (et le ferait aussi sur plusieurs tables mart)
car les vues `powerbi_v.*` dependent de ces tables et bloquent leur DROP TABLE
(mode replace). Cet orchestrateur :

  1. Verifie la base cible (garde-fou --confirm-db).
  2. Sauvegarde les definitions des vues powerbi_v (pg_get_viewdef, lecture
     seule) avant toute suppression -- filet de securite independant de
     etl/powerbi/create_powerbi_views.sql.
  3. Supprime les vues powerbi_v (DROP VIEW ... CASCADE).
  4. Lance etl/dwh/load_all_dwh.py (18 etapes dims+facts+audit).
  5. Lance la chaine mart/scoring dans l'ordre documente (features -> regles
     metier -> post-inspection -> ML -> hybride -> hybride ML -> index).
  6. Recree les vues via etl/powerbi/create_powerbi_views.py (CREATE OR
     REPLACE, smoke-test integre).

Fail-fast : a la premiere etape en echec, l'orchestrateur s'arrete
immediatement, tente une restauration best-effort des vues (etape 6) pour ne
jamais laisser la base sans couche de restitution Power BI, puis sort en
erreur avec un rapport clair de l'etat atteint.

Usage :
  python etl/orchestrate_full_recompute.py --confirm-db iris_auto_fraud_test_20260724

Le nom de base passe en --confirm-db DOIT correspondre exactement a DB_NAME
resolu depuis .env, sinon l'orchestrateur refuse de demarrer.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "etl" / "dwh"))
import dwh_utils  # noqa: E402

REPORT_DIR = BASE_DIR / "data" / "quality_reports" / "powerbi_views"

MART_CHAIN: list[tuple[str, Path]] = [
    ("compute_claim_scoring_features_v1", BASE_DIR / "etl" / "mart" / "compute_claim_scoring_features_v1.py"),
    ("compute_claim_business_rule_signals_v1_candidate", BASE_DIR / "etl" / "mart" / "compute_claim_business_rule_signals_v1_candidate.py"),
    ("compute_post_inspection_attention_signal_v1_candidate", BASE_DIR / "etl" / "mart" / "compute_post_inspection_attention_signal_v1_candidate.py"),
    ("compute_claim_ml_anomaly_signal_v1_candidate", BASE_DIR / "etl" / "mart" / "compute_claim_ml_anomaly_signal_v1_candidate.py"),
    ("compute_claim_attention_hybrid_score_v1_candidate", BASE_DIR / "etl" / "mart" / "compute_claim_attention_hybrid_score_v1_candidate.py"),
    ("compute_claim_attention_hybrid_ml_score_v1_candidate", BASE_DIR / "etl" / "mart" / "compute_claim_attention_hybrid_ml_score_v1_candidate.py"),
    ("ensure_scoring_indexes", BASE_DIR / "etl" / "mart" / "ensure_scoring_indexes.py"),
]

LOAD_ALL_DWH = BASE_DIR / "etl" / "dwh" / "load_all_dwh.py"
CREATE_POWERBI_VIEWS = BASE_DIR / "etl" / "powerbi" / "create_powerbi_views.py"


def _run_step(name: str, script: Path, logger) -> tuple[bool, float]:
    logger.info(f"[STEP] {name} ...")
    t0 = time.monotonic()
    result = subprocess.run([sys.executable, str(script)], cwd=str(BASE_DIR))
    elapsed = time.monotonic() - t0
    ok = result.returncode == 0
    if ok:
        logger.info(f"[OK]   {name} ({elapsed:.0f}s)")
    else:
        logger.error(f"[FAIL] {name} (exit={result.returncode}, {elapsed:.0f}s)")
    return ok, elapsed


def _backup_view_definitions(engine, logger, ts: str) -> Path:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT viewname, pg_get_viewdef(('powerbi_v.' || viewname)::regclass, true) AS def
            FROM pg_views WHERE schemaname = 'powerbi_v' ORDER BY viewname
        """)).fetchall()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORT_DIR / f"powerbi_v_definitions_backup_{ts}.sql"
    with open(out_path, "w", encoding="utf-8") as f:
        for name, definition in rows:
            f.write(f"-- powerbi_v.{name}\n")
            f.write(f"CREATE OR REPLACE VIEW powerbi_v.{name} AS\n{definition}\n\n")
    logger.info(f"[OK]   {len(rows)} definition(s) de vue sauvegardees -> {out_path.name}")
    return out_path


def _drop_views(engine, logger) -> list[str]:
    with engine.connect() as conn:
        views = [r[0] for r in conn.execute(text(
            "SELECT viewname FROM pg_views WHERE schemaname = 'powerbi_v' ORDER BY viewname"
        )).fetchall()]
    with engine.begin() as conn:
        for v in views:
            conn.execute(text(f"DROP VIEW IF EXISTS powerbi_v.{v} CASCADE"))
    logger.info(f"[OK]   {len(views)} vue(s) powerbi_v supprimee(s) : {views}")
    return views


def _restore_views_best_effort(logger) -> bool:
    logger.warning("[ROLLBACK] tentative de restauration des vues powerbi_v (create_powerbi_views.py) ...")
    result = subprocess.run([sys.executable, str(CREATE_POWERBI_VIEWS)], cwd=str(BASE_DIR))
    if result.returncode == 0:
        logger.warning("[ROLLBACK] vues powerbi_v restaurees avec succes.")
        return True
    logger.error(
        "[ROLLBACK] echec de la restauration des vues -- la base est dans un etat "
        "incomplet (tables partiellement rechargees et/ou vues manquantes). "
        "Intervention manuelle necessaire avant toute utilisation Power BI."
    )
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--confirm-db", required=True,
        help="Nom exact de la base cible (doit correspondre a DB_NAME resolu depuis .env). "
             "Garde-fou obligatoire : l'orchestrateur DROP des vues et recharge tout le DWH.",
    )
    parser.add_argument(
        "--skip-dwh", action="store_true",
        help="Sauter load_all_dwh.py (DWH deja rejoue) et ne lancer que la chaine mart + vues.",
    )
    args = parser.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logger = dwh_utils.setup_logging(run_id, log_name="orchestrate_full_recompute")
    engine = dwh_utils.build_engine(logger)

    with engine.connect() as conn:
        actual_db = conn.execute(text("SELECT current_database()")).fetchone()[0]

    if actual_db != args.confirm_db:
        logger.error(
            f"[ABORT] --confirm-db='{args.confirm_db}' ne correspond pas a la base "
            f"reellement configuree ('{actual_db}'). Rien n'a ete execute."
        )
        return 2

    logger.info("=" * 70)
    logger.info(f"[RUN {run_id}] orchestrate_full_recompute sur '{actual_db}'")
    logger.info("=" * 70)

    durations: dict[str, float] = {}

    backup_path = _backup_view_definitions(engine, logger, run_id)
    dropped_views = _drop_views(engine, logger)

    if not args.skip_dwh:
        t0 = time.monotonic()
        ok, elapsed = _run_step("load_all_dwh (18 etapes)", LOAD_ALL_DWH, logger)
        durations["load_all_dwh"] = elapsed
        if not ok:
            logger.error("[FAIL] load_all_dwh a echoue -- arret immediat (fail-fast).")
            _restore_views_best_effort(logger)
            _print_summary(logger, durations, success=False, backup_path=backup_path)
            return 1

    for name, script in MART_CHAIN:
        ok, elapsed = _run_step(name, script, logger)
        durations[name] = elapsed
        if not ok:
            logger.error(f"[FAIL] {name} a echoue -- arret immediat (fail-fast).")
            _restore_views_best_effort(logger)
            _print_summary(logger, durations, success=False, backup_path=backup_path)
            return 1

    ok, elapsed = _run_step("create_powerbi_views (recreation + smoke-test)", CREATE_POWERBI_VIEWS, logger)
    durations["create_powerbi_views"] = elapsed
    if not ok:
        logger.error("[FAIL] recreation des vues powerbi_v en echec apres un recalcul reussi.")
        _print_summary(logger, durations, success=False, backup_path=backup_path)
        return 1

    _print_summary(logger, durations, success=True, backup_path=backup_path)
    return 0


def _print_summary(logger, durations: dict[str, float], success: bool, backup_path: Path) -> None:
    logger.info("=" * 70)
    logger.info(f"  statut global      : {'SUCCES' if success else 'ECHEC'}")
    for name, elapsed in durations.items():
        logger.info(f"  {name:55s}: {elapsed:.0f}s")
    logger.info(f"  duree totale        : {sum(durations.values()):.0f}s")
    logger.info(f"  sauvegarde vues     : {backup_path}")
    logger.info("=" * 70)


if __name__ == "__main__":
    raise SystemExit(main())
