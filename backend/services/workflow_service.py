"""Workflow gestionnaire service — statut operationnel, affectation, taches.

Les evenements sont ajoutes a app.claim_workflow_event (schema separe de
dwh/mart/staging, jamais touche par les rechargements ETL). La table est
append-only : un trigger PostgreSQL rejette UPDATE/DELETE, donc changer de
statut ou reaffecter un dossier insere toujours une nouvelle ligne et
l'historique complet reste consultable.

Pas de notifications, pas de table utilisateur : l'identite est l'e-mail de
la personne connectee, comme pour claim_review_decision (decision_service.py).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from backend.config import ApiConfig
from backend.services.query_helpers import latest_score_run_sql, scalar_or_none
from backend.services.serialization import row_to_dict, rows_to_dicts

ALLOWED_STATUSES = {
    "NOUVEAU",
    "AFFECTE",
    "EN_COURS",
    "EN_ATTENTE_PIECES",
    "PRET_POUR_DECISION",
    "TRANSMIS_INVESTIGATION",
    "RETOUR_INVESTIGATION",
    "CLOTURE",
}
MAX_COMMENT_LENGTH = 2000
MAX_TASK_LABEL_LENGTH = 500


class WorkflowError(Exception):
    """Raised for invalid workflow submissions; carries an HTTP status code."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _normalize_email(email: str | None, *, field: str = "actor_email") -> str:
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise WorkflowError(f"Adresse e-mail manquante ou invalide ({field}).")
    return email


def _normalize_comment(comment: str | None) -> str | None:
    comment = (comment or "").strip() or None
    if comment and len(comment) > MAX_COMMENT_LENGTH:
        raise WorkflowError(f"Commentaire trop long (max {MAX_COMMENT_LENGTH} caracteres).")
    return comment


def _require_claim_exists(conn, claim_sk: int) -> None:
    exists = scalar_or_none(
        conn,
        "SELECT 1 FROM mart.fact_claim_attention_score WHERE claim_sk = :claim_sk LIMIT 1",
        {"claim_sk": claim_sk},
    )
    if not exists:
        raise WorkflowError("Dossier introuvable.", status_code=404)


def record_status_change(
    engine,
    *,
    claim_sk: int,
    status: str | None,
    actor_email: str | None,
    comment: str | None = None,
) -> dict[str, Any]:
    """Append one STATUS_CHANGE event. Raises WorkflowError on invalid input."""
    if status not in ALLOWED_STATUSES:
        raise WorkflowError(
            f"Statut invalide. Valeurs autorisees : {', '.join(sorted(ALLOWED_STATUSES))}."
        )
    actor_email = _normalize_email(actor_email)
    comment = _normalize_comment(comment)

    with engine.begin() as conn:
        _require_claim_exists(conn, claim_sk)
        row = conn.execute(
            text(
                """
                INSERT INTO app.claim_workflow_event
                    (claim_sk, event_type, status, comment, actor_email)
                VALUES
                    (:claim_sk, 'STATUS_CHANGE', :status, :comment, :actor_email)
                RETURNING event_id, claim_sk, event_type, status, comment, actor_email, created_at
                """
            ),
            {
                "claim_sk": claim_sk,
                "status": status,
                "comment": comment,
                "actor_email": actor_email,
            },
        ).first()
    return row_to_dict(row)


def record_assignment(
    engine,
    *,
    claim_sk: int,
    assignee_email: str | None,
    actor_email: str | None,
    comment: str | None = None,
) -> dict[str, Any]:
    """Append one ASSIGNMENT event. assignee_email may be empty/None to unassign."""
    actor_email = _normalize_email(actor_email)
    comment = _normalize_comment(comment)
    normalized_assignee = (assignee_email or "").strip().lower() or None
    if normalized_assignee and "@" not in normalized_assignee:
        raise WorkflowError("Adresse e-mail du gestionnaire invalide.")

    with engine.begin() as conn:
        _require_claim_exists(conn, claim_sk)
        row = conn.execute(
            text(
                """
                INSERT INTO app.claim_workflow_event
                    (claim_sk, event_type, assignee_email, comment, actor_email)
                VALUES
                    (:claim_sk, 'ASSIGNMENT', :assignee_email, :comment, :actor_email)
                RETURNING event_id, claim_sk, event_type, assignee_email, comment, actor_email, created_at
                """
            ),
            {
                "claim_sk": claim_sk,
                "assignee_email": normalized_assignee,
                "comment": comment,
                "actor_email": actor_email,
            },
        ).first()
    return row_to_dict(row)


def create_task(
    engine,
    *,
    claim_sk: int,
    task_label: str | None,
    actor_email: str | None,
) -> dict[str, Any]:
    """Append one TASK_CREATED event."""
    task_label = (task_label or "").strip()
    if not task_label:
        raise WorkflowError("Intitule de tache manquant.")
    if len(task_label) > MAX_TASK_LABEL_LENGTH:
        raise WorkflowError(f"Intitule de tache trop long (max {MAX_TASK_LABEL_LENGTH} caracteres).")
    actor_email = _normalize_email(actor_email)

    with engine.begin() as conn:
        _require_claim_exists(conn, claim_sk)
        row = conn.execute(
            text(
                """
                INSERT INTO app.claim_workflow_event
                    (claim_sk, event_type, task_label, actor_email)
                VALUES
                    (:claim_sk, 'TASK_CREATED', :task_label, :actor_email)
                RETURNING event_id, claim_sk, event_type, task_label, actor_email, created_at
                """
            ),
            {"claim_sk": claim_sk, "task_label": task_label, "actor_email": actor_email},
        ).first()
    return row_to_dict(row)


def complete_task(
    engine,
    *,
    claim_sk: int,
    task_ref_id: int | None,
    actor_email: str | None,
    comment: str | None = None,
) -> dict[str, Any]:
    """Append one TASK_COMPLETED event referencing an existing, still-open task."""
    if not task_ref_id:
        raise WorkflowError("Identifiant de tache manquant.")
    actor_email = _normalize_email(actor_email)
    comment = _normalize_comment(comment)

    with engine.begin() as conn:
        _require_claim_exists(conn, claim_sk)
        task = conn.execute(
            text(
                """
                SELECT event_id, task_label
                FROM app.claim_workflow_event
                WHERE event_id = :task_ref_id
                  AND claim_sk = :claim_sk
                  AND event_type = 'TASK_CREATED'
                """
            ),
            {"task_ref_id": task_ref_id, "claim_sk": claim_sk},
        ).first()
        if task is None:
            raise WorkflowError("Tache introuvable pour ce dossier.", status_code=404)

        already_completed = scalar_or_none(
            conn,
            """
            SELECT 1 FROM app.claim_workflow_event
            WHERE event_type = 'TASK_COMPLETED' AND task_ref_id = :task_ref_id
            """,
            {"task_ref_id": task_ref_id},
        )
        if already_completed:
            raise WorkflowError("Cette tache est deja cloturee.", status_code=409)

        row = conn.execute(
            text(
                """
                INSERT INTO app.claim_workflow_event
                    (claim_sk, event_type, task_ref_id, comment, actor_email)
                VALUES
                    (:claim_sk, 'TASK_COMPLETED', :task_ref_id, :comment, :actor_email)
                RETURNING event_id, claim_sk, event_type, task_ref_id, comment, actor_email, created_at
                """
            ),
            {
                "claim_sk": claim_sk,
                "task_ref_id": task_ref_id,
                "comment": comment,
                "actor_email": actor_email,
            },
        ).first()

    result = row_to_dict(row)
    result["task_label"] = task.task_label
    return result


def get_workflow_state(engine, claim_sk: int) -> dict[str, Any]:
    """Current status, current assignee and open tasks for one claim."""
    with engine.connect() as conn:
        status_row = conn.execute(
            text(
                """
                SELECT status, comment, actor_email, created_at
                FROM app.claim_workflow_status_latest
                WHERE claim_sk = :claim_sk
                """
            ),
            {"claim_sk": claim_sk},
        ).first()
        assignment_row = conn.execute(
            text(
                """
                SELECT assignee_email, comment, actor_email, created_at
                FROM app.claim_workflow_assignment_latest
                WHERE claim_sk = :claim_sk
                """
            ),
            {"claim_sk": claim_sk},
        ).first()
        open_tasks = conn.execute(
            text(
                """
                SELECT created.event_id AS task_ref_id, created.task_label,
                       created.actor_email AS created_by, created.created_at AS created_at
                FROM app.claim_workflow_event created
                WHERE created.claim_sk = :claim_sk
                  AND created.event_type = 'TASK_CREATED'
                  AND NOT EXISTS (
                      SELECT 1 FROM app.claim_workflow_event completed
                      WHERE completed.event_type = 'TASK_COMPLETED'
                        AND completed.task_ref_id = created.event_id
                  )
                ORDER BY created.created_at DESC
                """
            ),
            {"claim_sk": claim_sk},
        ).fetchall()

    return {
        "claim_sk": claim_sk,
        "status": status_row.status if status_row else None,
        "status_changed_at": status_row.created_at if status_row else None,
        "status_changed_by": status_row.actor_email if status_row else None,
        "assignee_email": assignment_row.assignee_email if assignment_row else None,
        "assigned_at": assignment_row.created_at if assignment_row else None,
        "assigned_by": assignment_row.actor_email if assignment_row else None,
        "open_tasks": rows_to_dicts(open_tasks),
    }


def get_workflow_history(engine, claim_sk: int) -> list[dict[str, Any]]:
    """Full workflow event log for one claim, most recent first."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT event_id, claim_sk, event_type, status, assignee_email, task_label,
                       task_ref_id, comment, actor_email, created_at
                FROM app.claim_workflow_event
                WHERE claim_sk = :claim_sk
                ORDER BY created_at DESC, event_id DESC
                LIMIT 500
                """
            ),
            {"claim_sk": claim_sk},
        ).fetchall()
    return rows_to_dicts(rows)


def list_open_tasks(
    engine,
    config: ApiConfig,
    *,
    assignee_email: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Open-tasks feed across claims, optionally filtered to one assignee's claims.
    Filters by the claim's CURRENT assignee, not who created the task, so a
    reassigned dossier's open tasks follow the new gestionnaire. The claim label
    is read from the latest score run of the API's default score version — same
    convention as list_decisions, adapted since workflow events don't pin a
    score_version/score_run_id of their own."""
    limit = max(1, min(int(limit or 50), 200))
    filter_clause = ""
    params: dict[str, Any] = {"limit": limit, "score_version": config.default_score_version}
    if assignee_email:
        filter_clause = "AND assignment.assignee_email = :assignee_email"
        params["assignee_email"] = assignee_email.strip().lower()

    with engine.connect() as conn:
        score_run_id = scalar_or_none(conn, latest_score_run_sql(), {"score_version": config.default_score_version})
        params["score_run_id"] = score_run_id
        rows = conn.execute(
            text(
                f"""
                SELECT created.event_id AS task_ref_id, created.claim_sk, created.task_label,
                       created.actor_email AS created_by, created.created_at,
                       assignment.assignee_email,
                       s.claim_business_id, s.attention_level, s.attention_score
                FROM app.claim_workflow_event created
                LEFT JOIN app.claim_workflow_assignment_latest assignment
                    ON assignment.claim_sk = created.claim_sk
                LEFT JOIN mart.fact_claim_attention_score s
                    ON s.claim_sk = created.claim_sk
                   AND s.score_version = :score_version
                   AND s.score_run_id = :score_run_id
                WHERE created.event_type = 'TASK_CREATED'
                  AND NOT EXISTS (
                      SELECT 1 FROM app.claim_workflow_event completed
                      WHERE completed.event_type = 'TASK_COMPLETED'
                        AND completed.task_ref_id = created.event_id
                  )
                  {filter_clause}
                ORDER BY created.created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).fetchall()
    return rows_to_dicts(rows)
