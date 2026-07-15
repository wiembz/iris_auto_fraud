"""
etl/dwh/load_dim_produit.py
============================
Charge staging.stg_production -> dwh.dim_produit.

Grain      : une ligne par produit automobile unique
Clé métier : code_produit (= codprod_norm ou codprod)
Clé tech   : produit_sk (entier séquentiel généré par le DWH)

Règle métier confirmée :
  code_produit commençant par '5' = périmètre automobile BNA

Usage :
  python etl/dwh/load_dim_produit.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwh_utils


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
TABLE_NAME = "dim_produit"
SOURCE_TABLE = "staging.stg_production"
SOURCE_SYSTEM = "BNA_ASSURANCES"
TODAY = datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _clean_code(s: pd.Series) -> pd.Series:
    """
    Nettoie un code produit.
    Retourne NULL si la valeur est vide, NAN ou NONE.
    """
    result = s.astype(str).str.strip().str.upper()

    result = result.where(
        (result.str.len() > 0)
        & (result != "NAN")
        & (result != "NONE")
        & (result != "NULL")
    )

    return result


def _clean_text(s: pd.Series) -> pd.Series:
    """
    Nettoie un texte métier.
    Retourne NULL si la valeur est vide, NAN ou NONE.
    """
    result = (
        s.astype(str)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )

    result = result.where(
        (result.str.len() > 0)
        & (result.str.upper() != "NAN")
        & (result.str.upper() != "NONE")
        & (result.str.upper() != "NULL")
    )

    return result


def _build_code_produit(df: pd.DataFrame) -> pd.Series:
    """
    Construit code_produit depuis codprod_norm ou codprod.
    """
    for col in ("codprod_norm", "codprod"):
        if col in df.columns:
            return _clean_code(df[col])

    return pd.Series(pd.NA, index=df.index, dtype=object)


def _build_libelle_produit(df: pd.DataFrame) -> pd.Series:
    """
    Construit libelle_produit depuis les colonnes disponibles.
    Fallback : NON_MAPPE.
    """
    candidats = [
        "product_label",
        "libelle_produit",
        "libprod",
        "libprdt",
    ]

    for col in candidats:
        if col in df.columns:
            libelle = _clean_text(df[col])
            if libelle.notna().any():
                return libelle.fillna("NON_MAPPE")

    return pd.Series("NON_MAPPE", index=df.index)


# ---------------------------------------------------------------------------
# Transformation
# ---------------------------------------------------------------------------
def transform_dim_produit(df_raw: pd.DataFrame, logger) -> tuple[pd.DataFrame, dict]:
    """
    Transforme staging.stg_production en dimension produit automobile.

    La dimension finale ne contient que les produits dont le code commence par 5.
    """
    n_raw = len(df_raw)
    logger.info(f"  Lignes lues depuis {SOURCE_TABLE} : {n_raw}")

    df = df_raw.copy()

    # 1. Construire la clé métier produit
    df["code_produit"] = _build_code_produit(df)

    n_code_null = int(df["code_produit"].isna().sum())

    if n_code_null:
        logger.info(f"  Lignes sans code_produit ignorées : {n_code_null}")

    df = df[df["code_produit"].notna()].copy()

    # 2. Filtrer uniquement le périmètre automobile confirmé
    n_before_auto_filter = len(df)

    df = df[df["code_produit"].str.startswith("5")].copy()

    n_after_auto_filter = len(df)
    n_non_auto_excluded = n_before_auto_filter - n_after_auto_filter

    logger.info(f"  Lignes après filtre automobile : {n_after_auto_filter}")
    logger.info(f"  Lignes non-auto exclues        : {n_non_auto_excluded}")

    # 3. Construire les libellés avant déduplication
    df["libelle_produit"] = _build_libelle_produit(df)

    # 4. Score de complétude pour garder le meilleur libellé par code_produit
    df["_score_libelle"] = df["libelle_produit"].ne("NON_MAPPE").astype(int)

    n_before_dedup = len(df)

    df = (
        df.sort_values(
            by=["code_produit", "_score_libelle"],
            ascending=[True, False],
        )
        .drop_duplicates(subset=["code_produit"], keep="first")
        .drop(columns=["_score_libelle"])
        .reset_index(drop=True)
    )

    n_dupes = n_before_dedup - len(df)

    logger.info(f"  Produits automobiles distincts : {len(df)}")
    logger.info(f"  Doublons produit supprimés     : {n_dupes}")

    # 5. Famille produit
    df["code_famille"] = df["code_produit"].str[0]
    df["libelle_famille"] = "AUTOMOBILE"

    # Sécurité : la dimension ne doit contenir que code_famille = 5
    df = df[df["code_famille"] == "5"].copy()

    # 6. Colonnes techniques
    df["source_system"] = SOURCE_SYSTEM
    df["created_at"] = TODAY

    # 7. Clé substitut DWH
    df = df.reset_index(drop=True)
    df.insert(0, "produit_sk", range(1, len(df) + 1))

    # 8. Sélection finale
    final_cols = [
        "produit_sk",
        "code_produit",
        "libelle_produit",
        "code_famille",
        "libelle_famille",
        "source_system",
        "created_at",
    ]

    # Ligne technique UNKNOWN (produit_sk = 0) : fact_contrat référence
    # produit_sk = 0 quand le produit source est absent ou hors périmètre.
    unknown_row = pd.DataFrame([{
        "produit_sk":      0,
        "code_produit":    "UNKNOWN",
        "libelle_produit": "UNKNOWN",
        "code_famille":    "UNKNOWN",
        "libelle_famille": "UNKNOWN",
        "source_system":   "TECHNICAL",
        "created_at":      TODAY,
    }])
    df_final = pd.concat([unknown_row[final_cols], df[final_cols]], ignore_index=True)
    df_final["produit_sk"] = df_final["produit_sk"].astype("int64")

    n_non_mappe = int((df_final["libelle_produit"] == "NON_MAPPE").sum())

    metrics = {
        "n_raw": n_raw,
        "n_code_null": n_code_null,
        "n_after_auto_filter": n_after_auto_filter,
        "n_non_auto_excluded": n_non_auto_excluded,
        "n_dupes": n_dupes,
        "n_loaded": len(df_final),
        "n_non_mappe": n_non_mappe,
    }

    return df_final, metrics


# ---------------------------------------------------------------------------
# Chargement
# ---------------------------------------------------------------------------
def load_dim_produit(run_id: str, engine, logger) -> dict:
    """
    Lit staging.stg_production, transforme et charge dwh.dim_produit.
    """
    logger.info(f"[READ] {SOURCE_TABLE}")

    # Lecture minimale, mais robuste :
    # certaines colonnes peuvent ne pas exister selon la version du staging.
    colonnes_candidates = [
        "codprod_norm",
        "codprod",
        "product_label",
        "libelle_produit",
        "libprod",
        "libprdt",
    ]

    query_columns = ", ".join(colonnes_candidates)

    try:
        df_raw = pd.read_sql(
            f"SELECT DISTINCT {query_columns} FROM {SOURCE_TABLE}",
            engine,
        )
    except Exception:
        # Fallback robuste si une colonne candidate n'existe pas dans PostgreSQL
        df_raw = pd.read_sql(
            f"SELECT * FROM {SOURCE_TABLE}",
            engine,
        )

    df_final, metrics = transform_dim_produit(df_raw, logger)

    _, elapsed = dwh_utils.write_to_dwh(df_final, engine, TABLE_NAME, logger)

    metrics["elapsed"] = elapsed

    return metrics


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    logger = dwh_utils.setup_logging(run_id, log_name="load_dim_produit")
    engine = dwh_utils.build_engine(logger)

    dwh_utils.create_dwh_schema(engine, logger)

    m = load_dim_produit(run_id, engine, logger)

    logger.info("=" * 60)
    logger.info("dwh.dim_produit chargée avec succès")
    logger.info(f"  lignes lues depuis staging       : {m['n_raw']}")
    logger.info(f"  lignes sans code_produit         : {m['n_code_null']}")
    logger.info(f"  lignes après filtre automobile   : {m['n_after_auto_filter']}")
    logger.info(f"  lignes non-auto exclues          : {m['n_non_auto_excluded']}")
    logger.info(f"  doublons produit supprimés       : {m['n_dupes']}")
    logger.info(f"  produits automobiles chargés     : {m['n_loaded']}")
    logger.info(f"  libellés NON_MAPPE               : {m['n_non_mappe']}")
    logger.info(f"  durée                            : {m['elapsed']:.1f}s")
    logger.info("=" * 60)

