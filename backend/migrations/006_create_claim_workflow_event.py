"""
backend/migrations/006_create_claim_workflow_event.py
=======================================================
Cree la table append-only app.claim_workflow_event qui porte le workflow
gestionnaire d'un dossier : statut operationnel, affectation, taches/relances.

Meme famille que app.claim_review_decision (voir 001_create_claim_review_decision.py) :
couche applicative (ecriture), separee de dwh/mart/staging, jamais ecrasee par
un rechargement DWH. Un seul evenement par ligne, trois types :
  - STATUS_CHANGE  : nouveau statut operationnel (8 etapes)
  - ASSIGNMENT     : (re)affectation a un gestionnaire (par e-mail)
  - TASK_CREATED   : creation d'une tache/relance
  - TASK_COMPLETED : cloture d'une tache existante (task_ref_id -> event_id)

Append-only : un trigger interdit UPDATE/DELETE. Changer de statut ou
reaffecter insere une nouvelle ligne ; l'etat courant se lit via les vues
"latest" (DISTINCT ON), l'historique complet via la table elle-meme.

Pas de notifications, pas de table utilisateur : l'identite est l'e-mail de
la personne connectee, comme pour app.claim_review_decision.

Idempotent : peut etre relance sans effet si deja applique.

Usage :
  python backend/migrations/006_create_claim_workflow_event.py
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
    CREATE TABLE IF NOT EXISTS app.claim_workflow_event (
        event_id        BIGSERIAL PRIMARY KEY,
        claim_sk        BIGINT NOT NULL,
        event_type      TEXT NOT NULL CHECK (event_type IN (
                            'STATUS_CHANGE', 'ASSIGNMENT', 'TASK_CREATED', 'TASK_COMPLETED'
                        )),
        status          TEXT CHECK (status IN (
                            'NOUVEAU', 'AFFECTE', 'EN_COURS', 'EN_ATTENTE_PIECES',
                            'PRET_POUR_DECISION', 'TRANSMIS_INVESTIGATION',
                            'RETOUR_INVESTIGATION', 'CLOTURE'
                        )),
        assignee_email  TEXT,
        task_label      TEXT,
        task_ref_id     BIGINT REFERENCES app.claim_workflow_event (event_id),
        comment         TEXT,
        actor_email     TEXT NOT NULL,
        created_at      TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_claim_workflow_event_claim_sk
        ON app.claim_workflow_event (claim_sk, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_claim_workflow_event_type
        ON app.claim_workflow_event (claim_sk, event_type, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_claim_workflow_event_task_ref
        ON app.claim_workflow_event (task_ref_id)
        WHERE task_ref_id IS NOT NULL
    """,
    # Vue "statut courant" : DISTINCT ON exploite l'index (claim_sk, event_type, created_at DESC).
    """
    CREATE OR REPLACE VIEW app.claim_workflow_status_latest AS
    SELECT DISTINCT ON (claim_sk) *
    FROM app.claim_workflow_event
    WHERE event_type = 'STATUS_CHANGE'
    ORDER BY claim_sk, created_at DESC, event_id DESC
    """,
    # Vue "affectation courante" : meme logique pour le dernier evenement ASSIGNMENT.
    """
    CREATE OR REPLACE VIEW app.claim_workflow_assignment_latest AS
    SELECT DISTINCT ON (claim_sk) *
    FROM app.claim_workflow_event
    WHERE event_type = 'ASSIGNMENT'
    ORDER BY claim_sk, created_at DESC, event_id DESC
    """,
    # Immuabilite : meme garantie que app.claim_review_decision.
    """
    CREATE OR REPLACE FUNCTION app.prevent_claim_workflow_event_mutation()
    RETURNS TRIGGER AS $$
    BEGIN
        RAISE EXCEPTION
            'app.claim_workflow_event est append-only : UPDATE/DELETE interdits (audit trail)';
    END;
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS trg_prevent_claim_workflow_event_mutation ON app.claim_workflow_event",
    """
    CREATE TRIGGER trg_prevent_claim_workflow_event_mutation
    BEFORE UPDATE OR DELETE ON app.claim_workflow_event
    FOR EACH ROW EXECUTE FUNCTION app.prevent_claim_workflow_event_mutation()
    """,
]


def run_migration() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        for statement in DDL_STATEMENTS:
            conn.execute(text(statement))
    print(
        "Migration OK : table 'claim_workflow_event' (append-only), "
        "vues 'claim_workflow_status_latest' / 'claim_workflow_assignment_latest'."
    )


if __name__ == "__main__":
    run_migration()
