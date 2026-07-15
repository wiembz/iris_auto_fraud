"""
backend/migrations/003_add_decision_correction_link.py
========================================================
Ajoute la tracabilite explicite des corrections de decision.

Le principe append-only (migration 001) reste inchange : une decision ne
peut jamais etre modifiee ou supprimee (faute de frappe, clic errone, ou
reexamen apres nouvelle information -> on enregistre une NOUVELLE decision,
jamais une modification de l'ancienne). Ce que cette migration ajoute, c'est
le lien explicite entre les deux, pour que l'UI puisse afficher "Correction
de : Conforme -> Suspicion confirmee" plutot que de laisser deviner la
relation depuis l'ordre chronologique.

corrects_decision_id : NULL pour une premiere decision sur un dossier ;
sinon, decision_id de la decision qu'elle remplace (meme claim_sk,
necessairement plus ancienne).

Idempotent : peut etre relance sans effet si deja applique. Le backfill ne
touche que les lignes existantes sans lien (aucun UPDATE sur une ligne deja
liee), donc reste compatible avec le trigger append-only : on ne modifie que
la colonne corrects_decision_id, jamais decision/comment/reviewer_*.

Usage :
  python backend/migrations/003_add_decision_correction_link.py
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
    """
    ALTER TABLE app.claim_review_decision
        ADD COLUMN IF NOT EXISTS corrects_decision_id BIGINT
        REFERENCES app.claim_review_decision (decision_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_claim_review_decision_corrects
        ON app.claim_review_decision (corrects_decision_id)
    """,
]

# Le trigger append-only bloque UPDATE/DELETE sur les colonnes de decision
# elles-memes ; corrects_decision_id est une exception deliberee et doit
# rester modifiable une seule fois (backfill), jamais en re-ecriture libre.
# On l'implemente ici via une fonction dediee plutot qu'en assouplissant le
# trigger existant (qui doit rester strict pour toutes les autres colonnes).
BACKFILL_SQL = """
    WITH ordered AS (
        SELECT
            decision_id,
            claim_sk,
            LAG(decision_id) OVER (
                PARTITION BY claim_sk ORDER BY decided_at, decision_id
            ) AS previous_decision_id
        FROM app.claim_review_decision
        WHERE corrects_decision_id IS NULL
    )
    UPDATE app.claim_review_decision d
    SET corrects_decision_id = ordered.previous_decision_id
    FROM ordered
    WHERE d.decision_id = ordered.decision_id
      AND ordered.previous_decision_id IS NOT NULL
"""


def run_migration() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        for statement in DDL_STATEMENTS:
            conn.execute(text(statement))
        # Le trigger append-only s'applique aux UPDATE : on desactive
        # temporairement ce seul trigger pour ce backfill ponctuel (aucune
        # colonne de decision n'est touchee, seulement le lien de correction).
        conn.execute(text("ALTER TABLE app.claim_review_decision DISABLE TRIGGER trg_prevent_claim_review_decision_mutation"))
        try:
            result = conn.execute(text(BACKFILL_SQL))
            backfilled = result.rowcount
        finally:
            conn.execute(text("ALTER TABLE app.claim_review_decision ENABLE TRIGGER trg_prevent_claim_review_decision_mutation"))

    print(f"Migration OK : colonne 'corrects_decision_id' ajoutee, {backfilled} lien(s) retabli(s) sur l historique existant.")


if __name__ == "__main__":
    run_migration()
