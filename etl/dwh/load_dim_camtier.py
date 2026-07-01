"""
etl/dwh/load_dim_camtier.py
============================
Charge staging.stg_sinistres -> dwh.dim_camtier.

Grain      : une ligne par couple (nature_camtier, id_camtier)
Clé métier : code_camtier = nature_camtier + '|' + id_camtier
Clé tech   : camtier_sk, entier séquentiel généré par le DWH

Colonnes source (noms normalisés staging) :
  natcamtie → nature_camtier
  idcamtier → id_camtier

Colonnes finales :
  camtier_sk, nature_camtier, id_camtier, code_camtier, source_system, created_at

Usage :
  python etl/dwh/load_dim_camtier.py
"""
from __future__ import annotations

import re
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

TABLE_NAME    = "dim_camtier"
SOURCE_TABLE  = "staging.stg_sinistres"
SOURCE_SYSTEM = "BNA_ASSURANCES"
TODAY         = datetime.now(timezone.utc).replace(tzinfo=None)

FINAL_COLS = [
    "camtier_sk",
    "nature_camtier",
    "id_camtier",
    "code_camtier",
    "source_system",
    "created_at",
]

_CAND_NATURE = ["natcamtie", "nature_camtier", "nat_camtier"]
_CAND_ID     = ["idcamtier", "id_camtier",     "id_cam"]

_INVALID = frozenset({
    "", "NULL", "NAN", "NONE", "0", "N/A", "NA", "ND", "NR",
    "INCONNU", "NON RENSEIGNE", "NON RENSEIGNÉ",
})

# nature_camtier : code alphabétique 2-3 lettres (ex. CA, CL, AA, BG)
_VALID_NATURE = re.compile(r"^[A-Z]{2,3}$")
# id_camtier    : identifiant numérique entier (ex. 1, 8, 22)
_VALID_ID = re.compile(r"^[0-9]+$")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _first_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _base_clean(val: object) -> str | None:
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    s = str(val).strip().upper()
    if s in _INVALID:
        return None
    try:
        f = float(s)
        if f.is_integer():
            return str(int(f))
    except ValueError:
        pass
    return s


def _clean_nature(val: object) -> str | None:
    s = _base_clean(val)
    if s is None:
        return None
    return s if _VALID_NATURE.match(s) else None


def _clean_id(val: object) -> str | None:
    s = _base_clean(val)
    if s is None:
        return None
    return s if _VALID_ID.match(s) else None


# ---------------------------------------------------------------------------
# Lecture staging
# ---------------------------------------------------------------------------

def _read_staging(engine, logger) -> tuple[pd.DataFrame, str | None, str | None]:
    with engine.connect() as conn:
        available = set(
            row[0] for row in conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'staging'
                  AND table_name   = 'stg_sinistres'
            """)).fetchall()
        )

    col_nat = next((c for c in _CAND_NATURE if c in available), None)
    col_id  = next((c for c in _CAND_ID     if c in available), None)

    missing = [n for n, c in [("natcamtie", col_nat), ("idcamtier", col_id)] if c is None]
    if missing:
        logger.warning(f"  Colonnes non trouvées dans stg_sinistres : {missing}")

    if col_nat is None and col_id is None:
        raise RuntimeError(
            "Aucune colonne camtier trouvée dans staging.stg_sinistres. "
            "Vérifiez que load_sinistres_sa.py a bien été exécuté."
        )

    select_cols = [c for c in [col_nat, col_id] if c is not None]
    sql = text(f"SELECT DISTINCT {', '.join(select_cols)} FROM staging.stg_sinistres")
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn)

    logger.info(f"  {len(df)} couples distincts lus depuis {SOURCE_TABLE}")
    return df, col_nat, col_id


# ---------------------------------------------------------------------------
# Transformation principale
# ---------------------------------------------------------------------------

def transform_dim_camtier(
    df_raw: pd.DataFrame,
    col_nat: str | None,
    col_id:  str | None,
    logger,
) -> tuple[pd.DataFrame, dict]:
    n_raw = len(df_raw)
    df    = df_raw.copy()

    if col_nat and col_nat != "nature_camtier":
        df["nature_camtier"] = df[col_nat]
    elif col_nat is None:
        df["nature_camtier"] = None

    if col_id and col_id != "id_camtier":
        df["id_camtier"] = df[col_id]
    elif col_id is None:
        df["id_camtier"] = None

    df["nature_camtier"] = df["nature_camtier"].map(_clean_nature)
    df["id_camtier"]     = df["id_camtier"].map(_clean_id)

    # Exiger un couple complet : nature ET id tous les deux renseignés
    mask_incomplet = df["nature_camtier"].isna() | df["id_camtier"].isna()
    n_vides        = int(mask_incomplet.sum())
    df             = df[~mask_incomplet].copy()
    if n_vides:
        logger.info(f"  Couples camtier incomplets exclus : {n_vides}")

    df["code_camtier"] = df["nature_camtier"] + "|" + df["id_camtier"]

    n_before = len(df)
    df       = df.drop_duplicates(subset=["code_camtier"], keep="first").copy()
    n_dupes  = n_before - len(df)
    if n_dupes:
        logger.info(f"  Doublons supprimés : {n_dupes}")
    logger.info(f"  Camtiers distincts après dédup : {len(df)}")

    df = df.reset_index(drop=True)
    df.insert(0, "camtier_sk", range(1, len(df) + 1))
    df["source_system"] = SOURCE_SYSTEM
    df["created_at"]    = TODAY

    for col in FINAL_COLS:
        if col not in df.columns:
            df[col] = None

    df_final = df[FINAL_COLS].copy()

    metrics = {
        "n_raw":          n_raw,
        "n_vides":        n_vides,
        "n_dupes":        n_dupes,
        "n_loaded":       len(df_final),
        "n_avec_nature":  int(df_final["nature_camtier"].notna().sum()),
        "n_avec_id":      int(df_final["id_camtier"].notna().sum()),
    }
    return df_final, metrics


# ---------------------------------------------------------------------------
# Chargement principal
# ---------------------------------------------------------------------------

def load_dim_camtier(run_id: str, engine, logger) -> int:
    logger.info(f"[RUN {run_id}] {SOURCE_TABLE} -> dwh.{TABLE_NAME}")

    with engine.connect() as conn:
        exists = conn.execute(text("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'staging' AND table_name = 'stg_sinistres'
        """)).fetchone()
    if not exists:
        raise RuntimeError(
            f"Table source {SOURCE_TABLE} introuvable. "
            "Exécutez d'abord load_sinistres_sa.py."
        )

    df_raw, col_nat, col_id = _read_staging(engine, logger)

    if df_raw.empty:
        logger.warning("  Aucune ligne dans staging.stg_sinistres — chargement annulé")
        return 0

    df_final, m = transform_dim_camtier(df_raw, col_nat, col_id, logger)

    n_rows, elapsed = dwh_utils.write_to_dwh(df_final, engine, TABLE_NAME, logger)

    logger.info("=" * 60)
    logger.info(f"  couples distincts lus          : {m['n_raw']}")
    logger.info(f"  sans clé camtier exclus        : {m['n_vides']}")
    logger.info(f"  doublons supprimés             : {m['n_dupes']}")
    logger.info(f"  camtiers chargés               : {m['n_loaded']}")
    logger.info(f"  avec nature_camtier            : {m['n_avec_nature']}")
    logger.info(f"  avec id_camtier                : {m['n_avec_id']}")
    logger.info(f"  durée chargement               : {elapsed:.1f}s")
    logger.info("=" * 60)

    return n_rows


# ---------------------------------------------------------------------------
# Point d'entrée autonome
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _run_id  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    _logger  = dwh_utils.setup_logging(_run_id, log_name="load_dim_camtier")
    _engine  = dwh_utils.build_engine(_logger)
    dwh_utils.create_dwh_schema(_engine, _logger)
    _n = load_dim_camtier(_run_id, _engine, _logger)
    _logger.info(f"Terminé : {_n} lignes -> dwh.{TABLE_NAME}")
