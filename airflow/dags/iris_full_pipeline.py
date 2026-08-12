"""
Airflow orchestration for the guarded IRIS full recompute.

Airflow owns scheduling, task state and observability. Existing IRIS entry
points keep all ETL, scoring, database guards and business validation logic.
The DAG carries a nightly schedule but is created paused (see README.md) and
manual triggering always remains available -- the full recompute replaces
DWH tables and requires a maintenance window, so it never runs unattended
until a human explicitly unpauses it.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    # Airflow 3 public interface.
    from airflow.sdk import Param, dag, get_current_context, task
except ImportError:  # pragma: no cover - compatibility with Airflow 2.10
    from airflow.decorators import dag, task
    from airflow.models.param import Param
    from airflow.operators.python import get_current_context


DAG_ID = "iris_full_pipeline"
PROJECT_ROOT_ENV = "IRIS_PROJECT_ROOT"
DEFAULT_PROJECT_ROOT = "/opt/airflow/iris"


def _project_root() -> Path:
    root = Path(os.environ.get(PROJECT_ROOT_ENV, DEFAULT_PROJECT_ROOT)).resolve()
    required = (
        root / "etl" / "staging_area" / "load_all_sa.py",
        root / "etl" / "orchestrate_full_recompute.py",
        root / "etl" / "mart" / "compute_vhs_v4_candidate.py",
        root / "etl" / "powerbi" / "create_powerbi_views.py",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            f"IRIS_PROJECT_ROOT invalide ({root}). Fichier(s) absent(s): {missing}"
        )
    return root


def _parameter(name: str):
    """Read a DAG-run parameter inside an executing Airflow task."""
    return get_current_context()["params"][name]


def _run_project_script(relative_path: str, *arguments: str) -> None:
    """Run one existing IRIS entry point without shell interpolation."""
    root = _project_root()
    command = [sys.executable, str(root / relative_path), *arguments]
    print(f"[IRIS] cwd={root}")
    print(f"[IRIS] command={' '.join(command)}")

    process = subprocess.Popen(
        command,
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=os.environ.copy(),
    )
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="")
    return_code = process.wait()
    if return_code:
        raise subprocess.CalledProcessError(return_code, command)


@dag(
    dag_id=DAG_ID,
    description="Pipeline IRIS garde: staging optionnel, DWH/scoring, VHS V4 et vues Power BI",
    # 02:00 UTC : fenetre de faible activite, avant l ouverture des agences.
    # Le declenchement manuel (Trigger DAG) reste toujours possible en plus de
    # ce planning ; il ne le remplace pas. Le DAG est cree en pause
    # (AIRFLOW__CORE__PAUSE_DAGS_AT_CREATION=true) : l activer explicitement
    # dans l UI pour que ce planning s applique reellement. Voir airflow/README.md
    # pour les autres garde-fous (allow_active_connections, base de test par defaut).
    schedule="0 2 * * *",
    start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    max_active_tasks=1,
    default_args={
        "owner": "iris",
        "depends_on_past": False,
        # Replace-mode tasks must never retry implicitly.
        "retries": 0,
        "execution_timeout": timedelta(hours=6),
        # Pas d alerte email/Slack configuree : aucun serveur SMTP ni webhook
        # n est fourni dans cet environnement de demonstration. Un echec de
        # tache n est visible que dans l UI Airflow (etat rouge) tant qu aucun
        # canal d alerte n est branche.
        "email_on_failure": False,
        "email_on_retry": False,
    },
    params={
        "confirm_db": Param(
            default=os.environ.get("IRIS_TARGET_DB", os.environ.get("DB_NAME", "")),
            type="string",
            minLength=1,
            title="Base IRIS cible",
            description=(
                "Doit correspondre exactement a DB_NAME. "
                "Le script refuse sinon toute modification."
            ),
        ),
        "reload_staging": Param(
            default=False,
            type="boolean",
            title="Recharger le staging",
            description="Remplace les quatre tables staging avant le DWH.",
        ),
        "allow_active_connections": Param(
            default=False,
            type="boolean",
            title="Autoriser les connexions actives",
            description="Deconseille: laisser faux pour imposer la fenetre de maintenance.",
        ),
        "skip_exact_checks": Param(
            default=False,
            type="boolean",
            title="Desactiver les valeurs attendues exactes",
            description=(
                "Conserve les controles structurels mais ignore les valeurs "
                "historiques exactes apres l'arrivee de nouvelles donnees."
            ),
        ),
    },
    tags=["iris", "etl", "dwh", "scoring", "powerbi"],
)
def iris_full_pipeline():
    @task(task_id="validate_configuration")
    def validate_configuration() -> str:
        root = _project_root()
        confirm_db = str(_parameter("confirm_db")).strip()
        configured_db = os.environ.get("DB_NAME", "").strip()
        if not confirm_db:
            raise ValueError("Le parametre confirm_db est obligatoire.")
        if configured_db and confirm_db != configured_db:
            raise ValueError(
                f"confirm_db={confirm_db!r} differe de DB_NAME={configured_db!r}."
            )
        print(f"[IRIS] projet={root}")
        print(f"[IRIS] base confirmee={confirm_db}")
        print("[IRIS] aucun traitement de donnees execute pendant ce preflight.")
        return confirm_db

    @task(task_id="load_staging")
    def load_staging() -> None:
        if not bool(_parameter("reload_staging")):
            print("[IRIS] rechargement staging ignore (reload_staging=false).")
            return
        _run_project_script("etl/staging_area/load_all_sa.py")

    @task(task_id="guarded_dwh_and_scoring_recompute")
    def guarded_dwh_and_scoring_recompute() -> None:
        arguments = ["--confirm-db", str(_parameter("confirm_db"))]
        if bool(_parameter("allow_active_connections")):
            arguments.append("--allow-active-connections")
        if bool(_parameter("skip_exact_checks")):
            arguments.append("--no-expected-checks")
        _run_project_script("etl/orchestrate_full_recompute.py", *arguments)

    @task(task_id="compute_vhs_v4")
    def compute_vhs_v4() -> None:
        _run_project_script("etl/mart/compute_vhs_v4_candidate.py")

    @task(task_id="refresh_powerbi_views")
    def refresh_powerbi_views() -> None:
        # Re-run the idempotent view build after VHS so its smoke tests include
        # the latest scoring outputs exposed to Power BI.
        _run_project_script("etl/powerbi/create_powerbi_views.py")

    confirmed = validate_configuration()
    staging = load_staging()
    recompute = guarded_dwh_and_scoring_recompute()
    vhs = compute_vhs_v4()
    powerbi = refresh_powerbi_views()

    confirmed >> staging >> recompute >> vhs >> powerbi


iris_full_pipeline()
