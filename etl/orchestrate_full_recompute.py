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
  7. Controles metier finaux (lecture seule) : le recalcul peut "reussir"
     techniquement (tous les scripts renvoient 0) tout en produisant un
     resultat metier faux -- ces controles verifient le dossier de reference,
     la stabilite du nombre de sinistres notes, et des bornes de sante sur la
     population conducteur avant de declarer le run reellement valide.

Fail-fast : a la premiere etape en echec, l'orchestrateur s'arrete
immediatement, tente une restauration best-effort des vues (etape 6) pour ne
jamais laisser la base sans couche de restitution Power BI, puis sort en
erreur avec un rapport clair de l'etat atteint. Si les controles metier
(etape 7) echouent, les vues restent en place (elles sont structurellement
valides) mais le run est marque en echec : les donnees ne doivent pas etre
considerees fiables sans revue manuelle.

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
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "etl" / "dwh"))
import dwh_utils  # noqa: E402
from backend.config import DEFAULT_SCORE_VERSION  # noqa: E402

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

# Bornes de sante dérivées du rapport d'impact (data/quality_reports/dim_conducteur/) :
# ~161 439 conducteurs reels attendus (perte de ~85 vs avant correctif) et
# ~17% de conducteur_sk=0 dans fact_sinistre (contre 8.7% avant correctif).
# Marges larges : ces controles doivent detecter un run qui a mal tourne
# (mauvaise base, staging non rechargee, etc.), pas repeter le rapport d'impact.
MIN_EXPECTED_REAL_DRIVERS = 100_000
MAX_EXPECTED_UNKNOWN_DRIVER_SHARE_PCT = 30.0


def _check_no_other_connections(engine, logger) -> list[dict]:
    """Fenetre de maintenance : la base ne doit avoir aucune autre connexion
    active (backend Flask, refresh Power BI, psql/pgAdmin ouvert...) pendant
    le recalcul -- ces process verraient des tables disparaitre (DROP TABLE en
    mode replace) ou liraient des resultats partiels pendant le rechargement."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT pid, usename, application_name, COALESCE(client_addr::text, 'local') AS client_addr, state
                FROM pg_stat_activity
                WHERE datname = current_database() AND pid <> pg_backend_pid()
                """
            )
        ).fetchall()
    return [dict(r._mapping) for r in rows]


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


def _run_final_business_checks(
    engine,
    logger,
    reference_numero: str,
    reference_garantie: str,
    expected_score: int | None = None,
    expected_attention_level: str | None = None,
    expected_confidence_level: str | None = None,
    expected_scored_claims: int | None = None,
    expected_views_count: int | None = None,
) -> bool:
    """Controles metier de sortie, en lecture seule. Un run peut techniquement
    reussir (tous les scripts renvoient 0) tout en produisant un resultat
    metier faux (staging non rechargee, mauvaise base, regression silencieuse) :
    ces controles verifient le dossier de reference et des bornes de sante
    avant de qualifier le run de fiable.

    Les `expected_*` sont optionnels : quand fournis, ils comparent le resultat
    EXACT du run (score, niveau, confiance, nombre de dossiers, vues) aux
    valeurs validees par simulation (data/quality_reports/dim_conducteur/),
    au lieu des seules bornes de sante generiques ci-dessus."""
    ok = True
    with engine.connect() as conn:
        ref_row = conn.execute(
            text(
                """
                SELECT fs.fact_sinistre_sk AS claim_sk, fs.conducteur_sk
                FROM dwh.fact_sinistre fs
                WHERE fs.numero_sinistre = :n AND fs.code_garantie = :g
                """
            ),
            {"n": reference_numero, "g": reference_garantie},
        ).first()

        if ref_row is None:
            logger.error(
                f"[CHECK] dossier de reference {reference_numero}|{reference_garantie} introuvable dans fact_sinistre"
            )
            ok = False
        else:
            if ref_row.conducteur_sk != 0:
                logger.error(
                    f"[CHECK] dossier de reference : conducteur_sk={ref_row.conducteur_sk} (attendu 0)"
                )
                ok = False
            else:
                logger.info(f"[CHECK] dossier de reference (claim_sk={ref_row.claim_sk}) : conducteur_sk=0 OK")

            latest_signal_run = conn.execute(
                text(
                    """
                    SELECT signal_run_id FROM mart.fact_claim_business_rule_signal
                    GROUP BY signal_run_id ORDER BY MAX(created_at) DESC LIMIT 1
                    """
                )
            ).first()
            if latest_signal_run:
                driver_signals = conn.execute(
                    text(
                        """
                        SELECT rule_code FROM mart.fact_claim_business_rule_signal
                        WHERE claim_sk = :claim_sk AND signal_run_id = :run_id
                          AND rule_code IN ('DRIVER_CLAIMS_12M_HIGH', 'DRIVER_RECENT_PREVIOUS_CLAIM')
                        """
                    ),
                    {"claim_sk": ref_row.claim_sk, "run_id": latest_signal_run[0]},
                ).fetchall()
                if driver_signals:
                    logger.error(
                        f"[CHECK] signal(aux) conducteur encore present(s) pour le dossier de reference : "
                        f"{[r[0] for r in driver_signals]}"
                    )
                    ok = False
                else:
                    logger.info("[CHECK] aucun signal DRIVER_* pour le dossier de reference OK")

            score_row = conn.execute(
                text(
                    """
                    SELECT score_version, attention_score, attention_level, confidence_level
                    FROM mart.fact_claim_attention_score
                    WHERE claim_sk = :claim_sk AND score_version = :version
                    ORDER BY created_at DESC LIMIT 1
                    """
                ),
                {"claim_sk": ref_row.claim_sk, "version": DEFAULT_SCORE_VERSION},
            ).first()
            if score_row is None:
                logger.error(
                    f"[CHECK] aucun score trouve pour le dossier de reference sur la version live "
                    f"'{DEFAULT_SCORE_VERSION}' (backend.config.DEFAULT_SCORE_VERSION)"
                )
                ok = False
            else:
                logger.info(
                    f"[CHECK] version live utilisee par l'API : {score_row.score_version} OK"
                )
                if expected_score is not None and int(score_row.attention_score) != expected_score:
                    logger.error(
                        f"[CHECK] score du dossier de reference : {score_row.attention_score} (attendu {expected_score})"
                    )
                    ok = False
                else:
                    logger.info(f"[CHECK] score du dossier de reference : {score_row.attention_score} OK")

                if expected_attention_level is not None and score_row.attention_level != expected_attention_level:
                    logger.error(
                        f"[CHECK] niveau d'attention : '{score_row.attention_level}' (attendu '{expected_attention_level}')"
                    )
                    ok = False
                else:
                    logger.info(f"[CHECK] niveau d'attention : '{score_row.attention_level}' OK")

                if expected_confidence_level is not None and score_row.confidence_level != expected_confidence_level:
                    logger.error(
                        f"[CHECK] confiance : '{score_row.confidence_level}' (attendu '{expected_confidence_level}')"
                    )
                    ok = False
                else:
                    logger.info(f"[CHECK] confiance : '{score_row.confidence_level}' OK")

        n_fact_sinistre = conn.execute(text("SELECT COUNT(*) FROM dwh.fact_sinistre")).fetchone()[0]

        # NB: mart.fact_claim_scoring_features ne couvre pas 100% de dwh.fact_sinistre
        # (filtre metier en amont dans compute_claim_scoring_features_v1.py, ~367 464 sur
        # 381 893 de facon stable historiquement) -- on compare donc au run precedent,
        # pas a fact_sinistre, pour detecter une vraie perte de sinistres notes.
        feature_runs = conn.execute(
            text(
                """
                SELECT feature_run_id, COUNT(*) AS n, MAX(created_at) AS last_created
                FROM mart.fact_claim_scoring_features
                GROUP BY feature_run_id ORDER BY last_created DESC LIMIT 2
                """
            )
        ).fetchall()
        n_scored = feature_runs[0].n if feature_runs else 0
        if len(feature_runs) >= 2:
            n_previous = feature_runs[1].n
            if n_scored < n_previous:
                logger.error(
                    f"[CHECK] nombre de sinistres notes en baisse : {n_scored} (run precedent : {n_previous})"
                )
                ok = False
            else:
                logger.info(f"[CHECK] stabilite du nombre de sinistres notes : {n_scored} (precedent {n_previous}) OK")
        else:
            logger.info(f"[CHECK] nombre de sinistres notes : {n_scored} (aucun run precedent pour comparaison)")

        if expected_scored_claims is not None and n_scored != expected_scored_claims:
            logger.error(
                f"[CHECK] nombre de sinistres notes : {n_scored} (attendu exactement {expected_scored_claims})"
            )
            ok = False
        elif expected_scored_claims is not None:
            logger.info(f"[CHECK] nombre de sinistres notes = {expected_scored_claims} (valeur exacte attendue) OK")

        n_real_drivers = conn.execute(
            text("SELECT COUNT(*) FROM dwh.dim_conducteur WHERE conducteur_sk <> 0")
        ).fetchone()[0]
        if n_real_drivers < MIN_EXPECTED_REAL_DRIVERS:
            logger.error(
                f"[CHECK] conducteurs reels anormalement bas : {n_real_drivers} (seuil {MIN_EXPECTED_REAL_DRIVERS})"
            )
            ok = False
        else:
            logger.info(f"[CHECK] conducteurs reels : {n_real_drivers} OK")

        n_unknown_driver = conn.execute(
            text("SELECT COUNT(*) FROM dwh.fact_sinistre WHERE conducteur_sk = 0")
        ).fetchone()[0]
        pct_unknown = 100.0 * n_unknown_driver / n_fact_sinistre if n_fact_sinistre else 100.0
        if pct_unknown > MAX_EXPECTED_UNKNOWN_DRIVER_SHARE_PCT:
            logger.error(
                f"[CHECK] part de conducteur_sk=0 anormalement elevee : {pct_unknown:.1f}% "
                f"(seuil {MAX_EXPECTED_UNKNOWN_DRIVER_SHARE_PCT}%)"
            )
            ok = False
        else:
            logger.info(f"[CHECK] part de conducteur_sk=0 : {pct_unknown:.1f}% OK")

        if expected_views_count is not None:
            view_names = [
                r[0] for r in conn.execute(
                    text("SELECT viewname FROM pg_views WHERE schemaname = 'powerbi_v' ORDER BY viewname")
                ).fetchall()
            ]
            if len(view_names) != expected_views_count:
                logger.error(
                    f"[CHECK] nombre de vues powerbi_v : {len(view_names)} (attendu {expected_views_count})"
                )
                ok = False
            else:
                unreadable = []
                for v in view_names:
                    try:
                        conn.execute(text(f"SELECT 1 FROM powerbi_v.{v} LIMIT 1"))
                    except Exception as exc:  # noqa: BLE001 - report every broken view
                        unreadable.append((v, str(exc)))
                if unreadable:
                    logger.error(f"[CHECK] vue(s) powerbi_v non interrogeable(s) : {[v for v, _ in unreadable]}")
                    ok = False
                else:
                    logger.info(f"[CHECK] {len(view_names)} vues powerbi_v toutes interrogeables OK")

    return ok


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
    parser.add_argument(
        "--reference-numero", default="G26511000017765",
        help="numero_sinistre du dossier de reference pour les controles metier finaux.",
    )
    parser.add_argument(
        "--reference-garantie", default="REM",
        help="code_garantie du dossier de reference pour les controles metier finaux.",
    )
    parser.add_argument(
        "--expected-score", type=int, default=65,
        help="Score d'attention exact attendu pour le dossier de reference (valeur validee par "
             "simulation, cf. data/quality_reports/dim_conducteur/). Voir --no-expected-checks "
             "pour desactiver toutes les comparaisons a valeur exacte.",
    )
    parser.add_argument(
        "--expected-attention-level", default="Examen renforce suggere",
        help="Niveau d'attention exact attendu pour le dossier de reference.",
    )
    parser.add_argument(
        "--expected-confidence-level", default="HIGH",
        help="Niveau de confiance exact attendu pour le dossier de reference.",
    )
    parser.add_argument(
        "--expected-scored-claims", type=int, default=367464,
        help="Nombre exact de dossiers notes attendu dans le dernier run de features.",
    )
    parser.add_argument(
        "--expected-views-count", type=int, default=13,
        help="Nombre de vues powerbi_v attendu, toutes devant etre interrogeables.",
    )
    parser.add_argument(
        "--no-expected-checks", action="store_true",
        help="Desactive les comparaisons a des valeurs exactes ci-dessus (garde uniquement les "
             "controles structurels : dossier trouve, conducteur_sk=0, bornes de sante). A utiliser "
             "si les valeurs exactes validees par simulation ne s'appliquent plus (nouvelles donnees "
             "sources arrivees entre temps, par exemple).",
    )
    parser.add_argument(
        "--allow-active-connections", action="store_true",
        help="Ne pas abandonner si d'autres connexions sont detectees sur la base (deconseille : "
             "ces connexions verront des tables disparaitre pendant le rechargement).",
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

    other_connections = _check_no_other_connections(engine, logger)
    if other_connections:
        logger.error(f"[ABORT] {len(other_connections)} autre(s) connexion(s) active(s) detectee(s) sur '{actual_db}' :")
        for c in other_connections:
            logger.error(f"    pid={c['pid']} user={c['usename']} app={c['application_name']!r} "
                         f"client={c['client_addr']} state={c['state']}")
        if not args.allow_active_connections:
            logger.error(
                "[ABORT] fenetre de maintenance non respectee -- fermer le backend Flask, "
                "toute session psql/pgAdmin et desactiver le refresh Power BI avant de relancer. "
                "Rien n'a ete execute. (--allow-active-connections pour forcer, deconseille.)"
            )
            return 3
        logger.warning("[WARN] --allow-active-connections force le demarrage malgre des connexions actives.")

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

    logger.info("[STEP] controles metier finaux ...")
    t0 = time.monotonic()
    checks_ok = _run_final_business_checks(
        engine,
        logger,
        args.reference_numero,
        args.reference_garantie,
        expected_score=None if args.no_expected_checks else args.expected_score,
        expected_attention_level=None if args.no_expected_checks else args.expected_attention_level,
        expected_confidence_level=None if args.no_expected_checks else args.expected_confidence_level,
        expected_scored_claims=None if args.no_expected_checks else args.expected_scored_claims,
        expected_views_count=None if args.no_expected_checks else args.expected_views_count,
    )
    durations["controles_metier_finaux"] = time.monotonic() - t0
    if not checks_ok:
        logger.error(
            "[FAIL] controles metier finaux non conformes -- tous les scripts ont reussi mais le "
            "resultat ne doit PAS etre considere fiable sans revue manuelle. Vues conservees "
            "(structurellement valides), donnees a examiner avant toute utilisation."
        )
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
