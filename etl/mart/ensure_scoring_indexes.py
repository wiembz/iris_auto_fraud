"""
etl/mart/ensure_scoring_indexes.py
===================================
Index de performance pour les tables mart interrogees en direct par l'API
IRIS (backend/services/*.py). Sans eux, chaque page (dashboard, file de
travail, revue dossier) declenche un scan sequentiel complet des tables de
scoring a chaque requete.

Deux causes combinees rendaient l'API lente :
  1. Les index existants (crees pour l'UPSERT ETL) menent par claim_sk, alors
     que l'API filtre par (score_version, score_run_id) SANS claim_sk pour
     lister/compter tous les dossiers d'un run -> l'index est inutilisable,
     Postgres retombe sur un Seq Scan.
  2. `_latest_score_run_sql` / `_latest_ml_signal_run_sql` /
     `_latest_post_inspection_run_sql` (appelees a CHAQUE requete API) filtrent
     par version et trient par date -> aucun index ne menait par la colonne
     version, meme scan complet a chaque appel.

Idempotent (CREATE INDEX IF NOT EXISTS) : peut etre relance apres chaque
recalcul mart sans effet si deja en place.

Usage :
  python etl/mart/ensure_scoring_indexes.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from etl.utils.runtime import build_engine

INDEX_STATEMENTS = [
    # "Quel est le dernier run pour cette version ?" — appele a chaque requete API.
    """
    CREATE INDEX IF NOT EXISTS idx_fcas_version_created
        ON mart.fact_claim_attention_score (score_version, created_at DESC, score_run_id DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fcmas_version_created
        ON mart.fact_claim_ml_anomaly_signal (signal_version, created_at DESC, signal_run_id DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fpias_version_created
        ON mart.fact_post_inspection_attention_signal (signal_version, created_at DESC, signal_run_id DESC)
    """,
    # Liste/compte des dossiers d'un run (dashboard, file de travail) + tri
    # par defaut sur attention_score : couvre le filtre ET evite un sort.
    """
    CREATE INDEX IF NOT EXISTS idx_fcas_version_run_score
        ON mart.fact_claim_attention_score (score_version, score_run_id, attention_score DESC)
    """,
    # Signaux d'un dossier (revue dossier) : point de lecture le plus frequent
    # apres le chargement de la liste, table sans aucun index secondaire avant.
    """
    CREATE INDEX IF NOT EXISTS idx_fcasd_claim_version_run
        ON mart.fact_claim_attention_signal_detail (claim_sk, score_version, score_run_id)
    """,
]


def ensure_scoring_indexes() -> None:
    engine = build_engine()
    with engine.begin() as conn:
        for statement in INDEX_STATEMENTS:
            conn.execute(text(statement))
    print(f"OK : {len(INDEX_STATEMENTS)} index de performance verifies/crees sur mart.*")


if __name__ == "__main__":
    ensure_scoring_indexes()
