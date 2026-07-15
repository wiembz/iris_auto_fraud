"""Human validation service — the only write path in the IRIS API.

Decisions are appended to app.claim_review_decision (schema separate from
dwh/mart/staging, never touched by ETL reloads). The table is append-only:
a PostgreSQL trigger rejects UPDATE/DELETE, so changing one's mind about a
claim always creates a new row and the full history stays auditable.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from backend.config import ApiConfig
from backend.services.query_helpers import latest_score_run_sql, scalar_or_none
from backend.services.serialization import rows_to_dicts

ALLOWED_DECISIONS = {"SUSPICION_CONFIRMED", "CONFORME", "A_COMPLETER"}
MAX_COMMENT_LENGTH = 2000


class DecisionError(Exception):
    """Raised for invalid decision submissions; carries an HTTP status code."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def create_decision(
    engine,
    config: ApiConfig,
    *,
    claim_sk: int,
    decision: str | None,
    comment: str | None,
    reviewer_email: str | None,
    reviewer_role: str | None,
    score_version: str | None = None,
) -> dict[str, Any]:
    """Append one review decision. Raises DecisionError on invalid input."""
    if decision not in ALLOWED_DECISIONS:
        raise DecisionError(
            f"Decision invalide. Valeurs autorisees : {', '.join(sorted(ALLOWED_DECISIONS))}."
        )

    reviewer_email = (reviewer_email or "").strip().lower()
    if not reviewer_email or "@" not in reviewer_email:
        raise DecisionError("Adresse e-mail du reviewer manquante ou invalide.")

    comment = (comment or "").strip() or None
    if comment and len(comment) > MAX_COMMENT_LENGTH:
        raise DecisionError(f"Commentaire trop long (max {MAX_COMMENT_LENGTH} caracteres).")

    selected_version = score_version or config.default_score_version

    with engine.begin() as conn:
        score_run_id = scalar_or_none(conn, latest_score_run_sql(), {"score_version": selected_version})
        if not score_run_id:
            raise DecisionError("Aucune analyse disponible pour cette version de score.", status_code=404)

        claim_exists = scalar_or_none(
            conn,
            """
            SELECT 1
            FROM mart.fact_claim_attention_score
            WHERE claim_sk = :claim_sk
              AND score_version = :score_version
              AND score_run_id = :score_run_id
            """,
            {"claim_sk": claim_sk, "score_version": selected_version, "score_run_id": score_run_id},
        )
        if not claim_exists:
            raise DecisionError("Dossier introuvable dans la derniere analyse.", status_code=404)

        # Une decision existante pour ce dossier (tout run confondu) n'est
        # jamais modifiee : la nouvelle decision la remplace et la reference
        # explicitement, pour que l'UI puisse afficher "correction de X".
        previous_decision = conn.execute(
            text(
                """
                SELECT decision_id, decision
                FROM app.claim_review_decision_latest
                WHERE claim_sk = :claim_sk
                """
            ),
            {"claim_sk": claim_sk},
        ).first()
        corrects_decision_id = previous_decision.decision_id if previous_decision else None
        previous_decision_value = previous_decision.decision if previous_decision else None

        row = conn.execute(
            text(
                """
                INSERT INTO app.claim_review_decision
                    (claim_sk, score_version, score_run_id, decision, comment, reviewer_email,
                     reviewer_role, corrects_decision_id)
                VALUES
                    (:claim_sk, :score_version, :score_run_id, :decision, :comment, :reviewer_email,
                     :reviewer_role, :corrects_decision_id)
                RETURNING decision_id, claim_sk, score_version, score_run_id, decision, comment,
                          reviewer_email, reviewer_role, decided_at, created_at, corrects_decision_id
                """
            ),
            {
                "claim_sk": claim_sk,
                "score_version": selected_version,
                "score_run_id": score_run_id,
                "decision": decision,
                "comment": comment,
                "reviewer_email": reviewer_email,
                "reviewer_role": reviewer_role,
                "corrects_decision_id": corrects_decision_id,
            },
        ).first()

    result = dict(row._mapping)
    result["corrected_decision_value"] = previous_decision_value
    return result


def get_decision_history(engine, claim_sk: int) -> list[dict[str, Any]]:
    """Full decision history for one claim, most recent first. Each row
    carries the decision it corrected (if any), so the UI can render
    "Correction de : Conforme -> Suspicion confirmee" explicitly."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT d.decision_id, d.claim_sk, d.score_version, d.score_run_id, d.decision, d.comment,
                       d.reviewer_email, d.reviewer_role, d.decided_at, d.created_at,
                       d.corrects_decision_id, prev.decision AS corrected_decision_value
                FROM app.claim_review_decision d
                LEFT JOIN app.claim_review_decision prev ON prev.decision_id = d.corrects_decision_id
                WHERE d.claim_sk = :claim_sk
                ORDER BY d.decided_at DESC, d.decision_id DESC
                LIMIT 200
                """
            ),
            {"claim_sk": claim_sk},
        ).fetchall()
    return rows_to_dicts(rows)


def list_decisions(
    engine,
    *,
    reviewer_email: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Recent decisions feed. Filtered to one reviewer for 'Mes validations',
    unfiltered for the team oversight view. Joins the exact score run stored
    on the decision (not the current latest one) so the claim label always
    matches what the reviewer actually saw when deciding."""
    limit = max(1, min(int(limit or 50), 200))
    where = ""
    params: dict[str, Any] = {"limit": limit}
    if reviewer_email:
        where = "WHERE d.reviewer_email = :reviewer_email"
        params["reviewer_email"] = reviewer_email.strip().lower()

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT
                    d.decision_id, d.claim_sk, d.score_version, d.score_run_id, d.decision,
                    d.comment, d.reviewer_email, d.reviewer_role, d.decided_at, d.created_at,
                    d.corrects_decision_id, prev.decision AS corrected_decision_value,
                    s.claim_business_id, s.attention_level, s.attention_score
                FROM app.claim_review_decision d
                LEFT JOIN mart.fact_claim_attention_score s
                    ON s.claim_sk = d.claim_sk
                   AND s.score_version = d.score_version
                   AND s.score_run_id = d.score_run_id
                LEFT JOIN app.claim_review_decision prev ON prev.decision_id = d.corrects_decision_id
                {where}
                ORDER BY d.decided_at DESC, d.decision_id DESC
                LIMIT :limit
                """
            ),
            params,
        ).fetchall()
    return rows_to_dicts(rows)
