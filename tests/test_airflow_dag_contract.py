from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DAG_PATH = PROJECT_ROOT / "airflow" / "dags" / "iris_full_pipeline.py"
COMPOSE_PATH = PROJECT_ROOT / "airflow" / "docker-compose.yml"


def _dag_source() -> str:
    return DAG_PATH.read_text(encoding="utf-8")


def _compose_source() -> str:
    return COMPOSE_PATH.read_text(encoding="utf-8")


def test_airflow_dag_is_valid_python() -> None:
    ast.parse(_dag_source(), filename=str(DAG_PATH))


def test_airflow_dag_exposes_expected_guarded_tasks() -> None:
    source = _dag_source()
    expected_task_ids = {
        "validate_configuration",
        "load_staging",
        "guarded_dwh_and_scoring_recompute",
        "compute_vhs_v4",
        "refresh_powerbi_views",
    }
    for task_id in expected_task_ids:
        assert f'task_id="{task_id}"' in source


def test_airflow_dag_keeps_destructive_safety_defaults() -> None:
    # The DAG carries a nightly schedule (see README.md) rather than being
    # schedule=None, but it must never run unattended: it has to be created
    # paused (checked against docker-compose.yml, the actual mechanism, not
    # just a comment), it must not run two recomputes concurrently, task
    # failures must never retry silently, and allow_active_connections must
    # default to false so a scheduled run fails fast if anyone else is
    # connected instead of racing a live session.
    source = _dag_source()
    compose_source = _compose_source()
    assert "schedule=" in source
    assert 'AIRFLOW__CORE__PAUSE_DAGS_AT_CREATION: "true"' in compose_source
    assert "max_active_runs=1" in source
    assert '"retries": 0' in source
    assert '"allow_active_connections"' in source
    assert "default=False" in source


def test_airflow_dag_delegates_to_existing_entry_points() -> None:
    source = _dag_source()
    expected_scripts = {
        "etl/staging_area/load_all_sa.py",
        "etl/orchestrate_full_recompute.py",
        "etl/mart/compute_vhs_v4_candidate.py",
        "etl/powerbi/create_powerbi_views.py",
    }
    for script in expected_scripts:
        assert script in source
