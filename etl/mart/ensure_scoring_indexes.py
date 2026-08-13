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
    # Dashboard summary : distributions par niveau d'attention et confiance.
    """
    CREATE INDEX IF NOT EXISTS idx_fcas_version_run_attention
        ON mart.fact_claim_attention_score (score_version, score_run_id, attention_level)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fcas_version_run_confidence
        ON mart.fact_claim_attention_score (score_version, score_run_id, confidence_level)
    """,
    # Dashboard top claims : EXISTS sur les signaux ML/STAFIM par claim_sk.
    """
    CREATE INDEX IF NOT EXISTS idx_fcmas_claim_version_run
        ON mart.fact_claim_ml_anomaly_signal (claim_sk, signal_version, signal_run_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fpias_claim_version_run
        ON mart.fact_post_inspection_attention_signal (claim_sk, signal_version, signal_run_id)
    """,
    # Portfolio insights : jointures s.claim_sk + f.feature_run_id et tendance par date.
    """
    CREATE INDEX IF NOT EXISTS idx_fcsf_feature_run_claim
        ON mart.fact_claim_scoring_features (feature_run_id, claim_sk)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fcsf_feature_run_claim_date
        ON mart.fact_claim_scoring_features (feature_run_id, claim_date)
    """,
    # Signaux d'un dossier (revue dossier) : point de lecture le plus frequent
    # apres le chargement de la liste, table sans aucun index secondaire avant.
    """
    CREATE INDEX IF NOT EXISTS idx_fcasd_claim_version_run
        ON mart.fact_claim_attention_signal_detail (claim_sk, score_version, score_run_id)
    """,
    # Registre VHS (page Vehicule) : les index existants sur ces deux tables
    # menent tous par (inspection_key, ..., run_id) avec run_id en DERNIERE
    # position -> inutilisables pour un filtre "WHERE run_id = :latest_run"
    # seul. Sans index dedie, le plan retombe sur un Nested Loop qui rescanne
    # entierement fact_vhs_penalty_detail (179k lignes) une fois par vehicule
    # du run (~280 fois) au lieu d'un hash join -- 22s mesures au lieu de
    # quelques dizaines de ms.
    """
    CREATE INDEX IF NOT EXISTS idx_fvs_run_score
        ON mart.fact_vhs_score (run_id, vhs_final_score)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fvpd_run_inspection
        ON mart.fact_vhs_penalty_detail (run_id, inspection_key)
        WHERE penalty_applied > 0
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
