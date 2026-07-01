"""
etl/dwh/load_dim_vehicule.py
============================
Charge staging.stg_inspection -> dwh.dim_vehicule.

Grain      : une ligne par immatriculation nettoyée et joinable
Clé métier : immatriculation (unique dans la dimension)
Clé tech   : vehicule_sk, entier séquentiel généré par le DWH

Source unique : Stafim (FicheVoitureStafim.xlsx via staging.stg_inspection)
Raison       : seule source disposant d'attributs descriptifs réels
               (vin, motorisation). Les immatriculations issues de Sinistres
               restent dans fact_sinistre comme identifiant dégénéré
               (immatriculation_sinistre). Le lien vehicule_sk y est optionnel.

Colonnes finales :
  vehicule_sk, immatriculation, vin, motorisation, source_system, created_at

Usage :
  python etl/dwh/load_dim_vehicule.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwh_utils

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

TABLE_NAME    = "dim_vehicule"
SOURCE_TABLE  = "staging.stg_inspection"
SOURCE_SYSTEM = "STAFIM"

FINAL_COLS = [
    "vehicule_sk",
    "immatriculation",
    "vin",
    "motorisation",
    "source_system",
    "created_at",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_str(val: object) -> str | None:
    """trim + uppercase ; vide ou None → None."""
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    s = str(val).strip().upper()
    return s if s else None


# ---------------------------------------------------------------------------
# Lecture staging
# ---------------------------------------------------------------------------

def _read_staging(engine, logger) -> pd.DataFrame:
    """
    Lit les colonnes utiles depuis staging.stg_inspection.
    Filtre immédiatement : is_valid_for_join = TRUE et immatriculation non nulle.
    """
    sql = text("""
        SELECT
            immatriculation,
            vin,
            motorisation,
            date_inspection,
            horodateur
        FROM staging.stg_inspection
        WHERE is_valid_for_join = TRUE
          AND immatriculation IS NOT NULL
    """)
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    logger.info(f"  staging lues (valides) : {len(df)} lignes")
    return df


# ---------------------------------------------------------------------------
# Déduplication : une ligne par immatriculation
# ---------------------------------------------------------------------------

def _select_best_per_immat(df: pd.DataFrame, logger) -> pd.DataFrame:
    """
    Produit une seule ligne par immatriculation.

    Critères par priorité décroissante :
      1. Score de complétude :
           vin renseigné      → +2 pts
           motorisation renseignée → +1 pt
         (priorité : vin+motor > vin seul > motor seul > aucun)
      2. date_inspection la plus récente
      3. horodateur le plus récent
    """
    df = df.copy()

    # Score de complétude
    df["_score"] = df["vin"].notna().astype(int) * 2 + df["motorisation"].notna().astype(int)

    # Colonnes de tri temporelles
    df["_date_sort"] = pd.to_datetime(df["date_inspection"], errors="coerce")
    df["_hora_sort"] = pd.to_datetime(df["horodateur"],      errors="coerce")

    df_sorted = df.sort_values(
        by=["_score", "_date_sort", "_hora_sort"],
        ascending=[False, False, False],
        na_position="last",
    )

    df_best = df_sorted.drop_duplicates(subset=["immatriculation"], keep="first")
    df_best = df_best.drop(columns=["_score", "_date_sort", "_hora_sort"])

    n_total   = len(df)
    n_uniq    = len(df_best)
    n_dropped = n_total - n_uniq
    logger.info(f"  déduplication : {n_total} → {n_uniq} véhicules distincts "
                f"({n_dropped} doublons d'immatriculation éliminés)")
    return df_best


# ---------------------------------------------------------------------------
# Transformation principale
# ---------------------------------------------------------------------------

def transform_dim_vehicule(df_staging: pd.DataFrame, logger) -> pd.DataFrame:
    """
    Applique filtrage, déduplication, nettoyage final et construction des colonnes DWH.
    Retourne le DataFrame prêt pour dwh.dim_vehicule.
    """
    n_source = len(df_staging)

    # ── Nettoyage final des champs texte ─────────────────────────────────────
    df_staging["immatriculation"] = df_staging["immatriculation"].map(_clean_str)
    df_staging["vin"]             = df_staging["vin"].map(_clean_str)
    df_staging["motorisation"]    = df_staging["motorisation"].map(_clean_str)

    # Supprimer les éventuelles immatriculations devenues nulles après clean
    df_staging = df_staging[df_staging["immatriculation"].notna()].copy()
    n_valides = len(df_staging)
    if n_valides < n_source:
        logger.warning(f"  {n_source - n_valides} ligne(s) écartée(s) après nettoyage immat")

    # ── Déduplication ────────────────────────────────────────────────────────
    df = _select_best_per_immat(df_staging, logger)

    # ── Clé technique séquentielle ───────────────────────────────────────────
    df = df.reset_index(drop=True)
    df.insert(0, "vehicule_sk", range(1, len(df) + 1))

    # ── Colonnes techniques DWH ──────────────────────────────────────────────
    df["source_system"] = SOURCE_SYSTEM
    df["created_at"]    = datetime.now(timezone.utc).replace(tzinfo=None)

    # ── Sélection finale ─────────────────────────────────────────────────────
    for col in FINAL_COLS:
        if col not in df.columns:
            df[col] = None

    df_final = df[FINAL_COLS].copy()

    # ── Métriques ────────────────────────────────────────────────────────────
    n_vin    = int(df_final["vin"].notna().sum())
    n_motor  = int(df_final["motorisation"].notna().sum())
    n_both   = int((df_final["vin"].notna() & df_final["motorisation"].notna()).sum())
    logger.info(f"  véhicules chargés          : {len(df_final)}")
    logger.info(f"  avec VIN renseigné         : {n_vin} "
                f"({100 * n_vin // max(len(df_final), 1)} %)")
    logger.info(f"  avec motorisation renseignée: {n_motor} "
                f"({100 * n_motor // max(len(df_final), 1)} %)")
    logger.info(f"  avec VIN + motorisation    : {n_both}")

    return df_final


# ---------------------------------------------------------------------------
# Chargement principal
# ---------------------------------------------------------------------------

def load_dim_vehicule(run_id: str, engine, logger) -> int:
    """
    Orchestre la lecture, la transformation et le chargement de dwh.dim_vehicule.
    Retourne le nombre de lignes chargées.
    """
    logger.info(f"[RUN {run_id}] {SOURCE_TABLE} -> dwh.{TABLE_NAME}")

    # Vérifier que la table source existe
    with engine.connect() as conn:
        exists = conn.execute(text("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'staging'
              AND table_name   = 'stg_inspection'
        """)).fetchone()
    if not exists:
        raise RuntimeError(
            f"Table source {SOURCE_TABLE} introuvable. "
            "Exécutez d'abord load_inspection_sa.py."
        )

    # Lecture
    df_staging = _read_staging(engine, logger)

    if df_staging.empty:
        logger.warning("  Aucune ligne valide dans staging.stg_inspection — chargement annulé")
        return 0

    # Transformation
    df_final = transform_dim_vehicule(df_staging, logger)

    # Chargement
    n_rows, elapsed = dwh_utils.write_to_dwh(df_final, engine, TABLE_NAME, logger)

    logger.info("=" * 60)
    logger.info(f"  lignes staging valides lues : {len(df_staging)}")
    logger.info(f"  véhicules distincts chargés : {n_rows}")
    logger.info(f"  durée chargement            : {elapsed:.1f}s")
    logger.info("=" * 60)

    return n_rows


# ---------------------------------------------------------------------------
# Point d'entrée autonome
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _run_id  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    _logger  = dwh_utils.setup_logging(_run_id, log_name="load_dim_vehicule")
    _engine  = dwh_utils.build_engine(_logger)
    dwh_utils.create_dwh_schema(_engine, _logger)
    _n = load_dim_vehicule(_run_id, _engine, _logger)
    _logger.info(f"Terminé : {_n} lignes -> dwh.{TABLE_NAME}")
