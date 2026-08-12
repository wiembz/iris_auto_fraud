"""
backend/migrations/001_create_claim_review_decision.py
========================================================
Cree le schema applicatif 'app' et la table append-only
app.claim_review_decision qui porte les decisions humaines de revue dossier.

Cette table est distincte de dwh/mart/staging : elle appartient a la couche
applicative (ecriture), pas a l'entrepot de donnees (lecture seule, recalcule
par les pipelines ETL). Elle ne sera jamais ecrasee par un rechargement DWH.

Append-only : un trigger interdit UPDATE/DELETE au niveau PostgreSQL. Changer
d'avis sur un dossier insere une nouvelle ligne ; l'historique complet reste
consultable (audit trail).

Idempotent : peut etre relance sans effet si deja applique.

Usage :
  python backend/migrations/001_create_claim_review_decision.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.db import get_engine

DDL_STATEMENTS = [
    "CREATE SCHEMA IF NOT EXISTS app",
    """
    CREATE TABLE IF NOT EXISTS app.claim_review_decision (
        decision_id     BIGSERIAL PRIMARY KEY,
        claim_sk        BIGINT NOT NULL,
        score_version   TEXT NOT NULL,
        score_run_id    TEXT,
        decision        TEXT NOT NULL CHECK (decision IN ('SUSPICION_CONFIRMED', 'CONFORME', 'A_COMPLETER')),
        comment         TEXT,
        reviewer_email  TEXT NOT NULL,
        reviewer_role   TEXT,
        decided_at      TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
        created_at      TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_claim_review_decision_claim_sk
        ON app.claim_review_decision (claim_sk, decided_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_claim_review_decision_reviewer
        ON app.claim_review_decision (reviewer_email, decided_at DESC)
    """,
    # Vue "dernier statut" : DISTINCT ON exploite l'index (claim_sk, decided_at DESC).
    """
    CREATE OR REPLACE VIEW app.claim_review_decision_latest AS
    SELECT DISTINCT ON (claim_sk) *
    FROM app.claim_review_decision
    ORDER BY claim_sk, decided_at DESC, decision_id DESC
    """,
    # Immuabilite : une decision existante ne peut jamais etre modifiee ou
    # supprimee. Changer d'avis = nouvelle ligne. C'est ce qui fait de cette
    # table un audit trail au sens propre, garanti par la base et non par
    # une simple convention applicative.
    """
    CREATE OR REPLACE FUNCTION app.prevent_claim_review_decision_mutation()
    RETURNS TRIGGER AS $$
    BEGIN
        RAISE EXCEPTION
            'app.claim_review_decision est append-only : UPDATE/DELETE interdits (audit trail)';
    END;
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS trg_prevent_claim_review_decision_mutation ON app.claim_review_decision",
    """
    CREATE TRIGGER trg_prevent_claim_review_decision_mutation
    BEFORE UPDATE OR DELETE ON app.claim_review_decision
    FOR EACH ROW EXECUTE FUNCTION app.prevent_claim_review_decision_mutation()
    """,
]


def run_migration() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        for statement in DDL_STATEMENTS:
            conn.execute(text(statement))
    print("Migration OK : schema 'app', table 'claim_review_decision' (append-only), vue 'claim_review_decision_latest'.")


if __name__ == "__main__":
    run_migration()
