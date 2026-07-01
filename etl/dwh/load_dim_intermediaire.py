"""
etl/dwh/load_dim_intermediaire.py
=================================
Charge staging.stg_production + data/raw/PR01.xlsx -> dwh.dim_intermediaire.

Grain      : une ligne par couple (nature_intermediaire, id_intermediaire)
Clé métier : code_intermediaire = natint_norm + '|' + idint_norm
Clé tech   : intermediaire_sk, entier séquentiel généré par le DWH

Sources :
  1. staging.stg_production  — couples (natint_norm, idint_norm) utilisés
  2. data/raw/PR01.xlsx      — référentiel libellés (NATINT, IDINT, LOCAL)

Usage :
  python etl/dwh/load_dim_intermediaire.py
"""
from __future__ import annotations

import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwh_utils

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
TABLE_NAME    = "dim_intermediaire"
SOURCE_TABLE  = "staging.stg_production"
SOURCE_SYSTEM = "BNA_ASSURANCES"
TODAY         = datetime.now(timezone.utc).replace(tzinfo=None)

NON_RENSEIGNE = "NON RENSEIGNÉ"

BASE_DIR  = Path(__file__).resolve().parent.parent.parent
PR01_PATH = BASE_DIR / "data" / "raw" / "PR01.xlsx"

# Mapping nature_intermediaire
_NATURE_MAP: dict[str, str] = {
    "AG":       "AGENT",
    "A":        "AGENT",
    "AGENT":    "AGENT",
    "CL":       "CLIENT",
    "C":        "COURTIER",
    "CR":       "COURTIER",
    "COURTIER": "COURTIER",
    "B":        "BANQUE",
    "BQ":       "BANQUE",
    "BANQUE":   "BANQUE",
    "D":        "DIRECT",
    "DIR":      "DIRECT",
    "DIRECT":   "DIRECT",
    "S":        "SIEGE",
    "SG":       "SIEGE",
    "SI":       "SIEGE",
    "SIEGE":    "SIEGE",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _clean_code(value) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip().upper()
    if text in {"", "NAN", "NONE", "NULL", "0"}:
        return None
    try:
        number = float(text)
        if number.is_integer():
            return str(int(number))
    except ValueError:
        pass
    return text


def _clean_text(value) -> str:
    if pd.isna(value):
        return NON_RENSEIGNE
    text = str(value).strip()
    if not text:
        return NON_RENSEIGNE
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.upper()
    text = " ".join(text.split())
    if text in {"", "NAN", "NONE", "NULL", "UNKNOWN",
                "NON RENSEIGNE", "NON RENSEIGNÉ", "NON_RENSEIGNE"}:
        return NON_RENSEIGNE
    return text


def _normaliser_nature(code: str | None) -> str:
    if not code:
        return NON_RENSEIGNE
    return _NATURE_MAP.get(code, code)


# ---------------------------------------------------------------------------
# Lecture PR01
# ---------------------------------------------------------------------------
def _load_pr01(logger) -> pd.DataFrame:
    """
    Lit data/raw/PR01.xlsx et retourne un DataFrame avec :
      code_intermediaire, libelle_intermediaire
    Colonnes attendues : NATINT, IDINT, LOCAL
    """
    if not PR01_PATH.exists():
        logger.warning(f"  [PR01] Fichier introuvable : {PR01_PATH} — libelles absents")
        return pd.DataFrame(columns=["code_intermediaire", "libelle_intermediaire"])

    df = pd.read_excel(PR01_PATH, dtype=str)
    n_raw = len(df)
    logger.info(f"  [PR01] {n_raw} lignes lues depuis {PR01_PATH.name}")

    natint_col = next((c for c in df.columns if c.strip().upper() == "NATINT"), None)
    idint_col  = next((c for c in df.columns if c.strip().upper() == "IDINT"),  None)
    local_col  = next((c for c in df.columns if c.strip().upper() == "LOCAL"),  None)

    if natint_col is None or idint_col is None:
        logger.warning("  [PR01] Colonnes NATINT/IDINT absentes — libelles absents")
        return pd.DataFrame(columns=["code_intermediaire", "libelle_intermediaire"])

    df["_natint"] = df[natint_col].map(_clean_code)
    df["_idint"]  = df[idint_col].map(_clean_code)

    df = df[df["_natint"].notna() & df["_idint"].notna()].copy()

    df["code_intermediaire"] = df["_natint"] + "|" + df["_idint"]

    if local_col:
        df["libelle_intermediaire"] = df[local_col].map(_clean_text)
    else:
        df["libelle_intermediaire"] = NON_RENSEIGNE

    # Garder libellé renseigné en priorité en cas de doublon
    df["_has_lib"] = (df["libelle_intermediaire"] != NON_RENSEIGNE).astype(int)
    df = (
        df.sort_values(["code_intermediaire", "_has_lib"], ascending=[True, False])
        .drop_duplicates(subset=["code_intermediaire"], keep="first")
    )

    n_lib = int((df["libelle_intermediaire"] != NON_RENSEIGNE).sum())
    logger.info(f"  [PR01] {len(df)} codes distincts | libelles renseignes : {n_lib}")

    return df[["code_intermediaire", "libelle_intermediaire"]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Transformation
# ---------------------------------------------------------------------------
def transform_dim_intermediaire(
    df_raw: pd.DataFrame,
    df_pr01: pd.DataFrame,
    logger,
) -> tuple[pd.DataFrame, dict]:
    n_raw = len(df_raw)
    logger.info(f"  Lignes lues depuis {SOURCE_TABLE} : {n_raw}")

    df = df_raw.copy()

    # Colonnes sources avec fallback
    natint_col = next((c for c in ("natint_norm", "natint") if c in df.columns), None)
    idint_col  = next((c for c in ("idint_norm",  "idint")  if c in df.columns), None)

    if natint_col is None or idint_col is None:
        raise ValueError("Colonnes natint/idint introuvables dans stg_production")

    df["_natint"] = df[natint_col].map(_clean_code)
    df["_idint"]  = df[idint_col].map(_clean_code)

    # Filtre clé non nulle
    n_before  = len(df)
    df        = df[df["_natint"].notna() & df["_idint"].notna()].copy()
    n_null_key = n_before - len(df)
    if n_null_key:
        logger.info(f"  Lignes ignorees avec cle nulle : {n_null_key}")

    df["code_intermediaire"] = df["_natint"] + "|" + df["_idint"]

    # Couples distincts de la production
    prod_distinct = (
        df[["code_intermediaire", "_natint", "_idint"]]
        .drop_duplicates(subset=["code_intermediaire"])
        .reset_index(drop=True)
    )
    n_prod_distinct = len(prod_distinct)
    logger.info(f"  Intermediaires distincts dans production : {n_prod_distinct}")

    # Jointure LEFT avec PR01
    merged = prod_distinct.merge(df_pr01, on="code_intermediaire", how="left")
    merged["libelle_intermediaire"] = merged["libelle_intermediaire"].fillna(NON_RENSEIGNE)

    n_match    = int(merged["libelle_intermediaire"].ne(NON_RENSEIGNE).sum())
    n_no_match = n_prod_distinct - n_match
    logger.info(f"  Matches avec PR01          : {n_match}")
    logger.info(f"  Sans match PR01            : {n_no_match}")

    # nature_intermediaire
    merged["nature_intermediaire"] = merged["_natint"].map(_normaliser_nature)
    merged = merged.rename(columns={"_idint": "id_intermediaire"})

    # Colonnes techniques
    merged["source_system"] = SOURCE_SYSTEM
    merged["created_at"]    = TODAY

    # Tri + clé substitut
    merged = merged.sort_values("code_intermediaire").reset_index(drop=True)
    merged.insert(0, "intermediaire_sk", range(1, len(merged) + 1))

    final_cols = [
        "intermediaire_sk",
        "code_intermediaire",
        "nature_intermediaire",
        "id_intermediaire",
        "libelle_intermediaire",
        "source_system",
        "created_at",
    ]

    for col in final_cols:
        if col not in merged.columns:
            merged[col] = None

    n_non_renseigne = int((merged["libelle_intermediaire"] == NON_RENSEIGNE).sum())

    top_natures = (
        merged["nature_intermediaire"]
        .value_counts(dropna=False)
        .head(20)
        .to_dict()
    )

    metrics = {
        "n_raw":           n_raw,
        "n_null_key":      n_null_key,
        "n_prod_distinct": n_prod_distinct,
        "n_pr01":          len(df_pr01),
        "n_match":         n_match,
        "n_no_match":      n_no_match,
        "n_loaded":        len(merged),
        "n_non_renseigne": n_non_renseigne,
        "top_natures":     top_natures,
    }

    return merged[final_cols], metrics


# ---------------------------------------------------------------------------
# Chargement
# ---------------------------------------------------------------------------
def load_dim_intermediaire(run_id: str, engine, logger) -> dict:
    logger.info(f"[READ] {SOURCE_TABLE}")
    df_raw = pd.read_sql(
        f"SELECT natint_norm, idint_norm FROM {SOURCE_TABLE} "
        "WHERE natint_norm IS NOT NULL AND idint_norm IS NOT NULL",
        engine,
    )

    df_pr01 = _load_pr01(logger)

    df_final, metrics = transform_dim_intermediaire(df_raw, df_pr01, logger)

    _, elapsed = dwh_utils.write_to_dwh(df_final, engine, TABLE_NAME, logger)
    metrics["elapsed"] = elapsed

    return metrics


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logger = dwh_utils.setup_logging(run_id, log_name="load_dim_intermediaire")
    engine = dwh_utils.build_engine(logger)
    dwh_utils.create_dwh_schema(engine, logger)

    m = load_dim_intermediaire(run_id, engine, logger)

    logger.info("=" * 60)
    logger.info("dwh.dim_intermediaire chargee avec succes")
    logger.info(f"  lignes lues depuis stg_production      : {m['n_raw']}")
    logger.info(f"  lignes avec cle nulle ignorees         : {m['n_null_key']}")
    logger.info(f"  intermediaires distincts (production)  : {m['n_prod_distinct']}")
    logger.info(f"  lignes lues depuis PR01                : {m['n_pr01']}")
    logger.info(f"  matches avec PR01                      : {m['n_match']}")
    logger.info(f"  sans match PR01                        : {m['n_no_match']}")
    logger.info(f"  intermediaires charges (DWH)           : {m['n_loaded']}")
    logger.info(f"  libelles NON RENSEIGNE                 : {m['n_non_renseigne']}")
    logger.info("  -- repartition nature_intermediaire --")
    for nature, count in m["top_natures"].items():
        logger.info(f"    {nature:<20} : {count}")
    logger.info(f"  duree                                  : {m['elapsed']:.1f}s")
    logger.info("=" * 60)
