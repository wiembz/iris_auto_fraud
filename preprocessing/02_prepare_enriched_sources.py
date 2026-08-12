"""
preprocessing/02_prepare_enriched_sources.py
============================================
IRIS Auto Fraud Decision Platform — BNA Assurances Tunisie

Étape de preprocessing : enrichissement référentiel avant chargement PostgreSQL.

Rôle :
  Lit les fichiers bruts depuis data/raw/, applique les mappings référentiels
  validés, produit 4 fichiers Excel enrichis dans data/processed/ et
  5 rapports dans data/processed/reports/.

Ce script NE se connecte PAS à PostgreSQL.
Il NE construit PAS de dimensions, facts, mart, VHS ni scoring.
Il NE supprime PAS de lignes — les codes non mappés reçoivent un label fallback.

Usage :
  python preprocessing/02_prepare_enriched_sources.py
"""

# ─── 1. Imports ───────────────────────────────────────────────────────────────
from __future__ import annotations

import hashlib
import logging
import re
import sys
import unicodedata
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# Forcer UTF-8 sur stdout pour éviter UnicodeEncodeError sur Windows (cp1252)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ─── 2. Paths and constants ───────────────────────────────────────────────────
BASE_DIR  = Path(__file__).resolve().parent.parent

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from etl.utils.date_parsing import parse_date_value

DATA_RAW  = BASE_DIR / "data" / "raw"
DATA_PROC = BASE_DIR / "data" / "processed"
REPORTS   = DATA_PROC / "reports"
LOGS_DIR  = BASE_DIR / "logs"

for _d in [DATA_PROC, REPORTS, LOGS_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

AUTO_SCOPE_RULE   = "AUTO_SCOPE_001"
AUTO_SCOPE_STATUS = "confirmed"

FALLBACK = {
    "produit":        "NON_MAPPED_PRODUCT",
    "garantie":       "NON_MAPPED_GUARANTEE",
    "nature_client":  "NON_MAPPED_CLIENT_NATURE",
    "intermediaire":  "NON_MAPPED_INTERMEDIARY",
    "cause_sinistre": "NON_MAPPED_CLAIM_CAUSE",
}


# ─── 3. Logging (délégué à etl.utils.runtime, namespace "preprocessing") ─────
try:
    from etl.utils.runtime import setup_logging as _runtime_setup_logging
except ModuleNotFoundError:  # standalone script execution
    sys.path.insert(0, str(BASE_DIR))
    from etl.utils.runtime import setup_logging as _runtime_setup_logging


def setup_logging(run_id: str) -> logging.Logger:
    return _runtime_setup_logging(
        run_id,
        log_name="02_prepare_enriched_sources",
        namespace="preprocessing",
    )


# ─── 4. Utility functions ─────────────────────────────────────────────────────

def normalize_code(value: Any) -> str | None:
    """Normalise un code : upper, strip, supprime .0. None si vide/NaN."""
    if value is None:
        return None
    if isinstance(value, float):
        if np.isnan(value):
            return None
        s = str(int(value)) if value == int(value) else str(value)
    else:
        s = str(value)
    s = s.strip()
    if s.endswith(".0"):
        s = s[:-2]
    s = re.sub(r"\s+", " ", s).upper()
    return s if s else None


def clean_text(value: Any) -> str | None:
    """Nettoie un texte libre. None si vide/NaN."""
    if value is None:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    s = re.sub(r"\s+", " ", str(value).strip())
    return s if s else None


def normalize_immat(value: Any) -> str | None:
    """Normalise immatriculation : alphanumérique seulement, upper."""
    if value is None:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    s = re.sub(r"[\s\-/\.]", "", str(value))
    s = re.sub(r"[^A-Za-z0-9]", "", s).upper()
    return s if s else None


def parse_date_safe(series: pd.Series) -> pd.Series:
    """Convertit une Series en datetime. Gère NaN, '0', '00000000'.

    Délègue à etl.utils.date_parsing : les exports BNA encodent les dates en
    entiers YYYYMMDD, que dayfirst=True inversait (jour<->mois) dès que le
    jour réel était <= 12 — format %Y%m%d explicite désormais.
    """
    return series.apply(parse_date_value)


def parse_numeric_safe(series: pd.Series) -> pd.Series:
    """Convertit en float. Gère virgules, espaces, NaN."""
    def _parse(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        s = str(v).replace(",", ".").replace(" ", "").strip()
        try:
            return float(s)
        except ValueError:
            return None
    return series.apply(_parse)


def normalize_column_name(col: str, max_len: int = 55) -> str:
    """
    Normalise un nom de colonne pour PostgreSQL :
    lowercase, sans accents, caractères spéciaux → '_', max_len chars.
    """
    col = str(col).strip()
    col = unicodedata.normalize("NFKD", col)
    col = "".join(c for c in col if not unicodedata.combining(c))
    col = col.lower()
    col = re.sub(r"[^a-z0-9]+", "_", col)
    col = re.sub(r"_+", "_", col).strip("_")
    return (col or "col")[:max_len]


def make_unique_columns(columns: list[str], max_len: int = 55) -> tuple[list[str], dict]:
    """Normalise et rend les noms de colonnes uniques (suffixe _2, _3…)."""
    seen: dict[str, int] = {}
    new_cols: list[str] = []
    mapping: dict[str, str] = {}
    for original in columns:
        base      = normalize_column_name(str(original), max_len=max_len)
        candidate = base
        if candidate in seen:
            seen[candidate] += 1
            suffix    = f"_{seen[candidate]}"
            candidate = f"{base[:max_len - len(suffix)]}{suffix}"
        else:
            seen[candidate] = 0
        new_cols.append(candidate)
        mapping[str(original)] = candidate
    return new_cols, mapping


def standardize_dataframe_columns(
    df: pd.DataFrame,
    table_name: str,
    logger: logging.Logger | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Standardise les noms de colonnes.
    Retourne (df renommé, DataFrame de mapping original → standardized).
    """
    original_cols = list(df.columns)
    new_cols, _   = make_unique_columns(original_cols)
    df            = df.copy()
    df.columns    = new_cols
    mapping_df    = pd.DataFrame({
        "table_name":          table_name,
        "original_column":     original_cols,
        "standardized_column": new_cols,
    })
    if logger:
        changed = sum(a != b for a, b in zip(original_cols, new_cols))
        if changed:
            logger.info(f"{table_name} : {changed} colonnes renommées pour compatibilité")
    dups = pd.Series(new_cols).duplicated().sum()
    if dups:
        raise ValueError(f"Colonnes dupliquées après standardisation dans {table_name}")
    return df, mapping_df


def make_composite_key(
    df: pd.DataFrame,
    cols: list[str],
    key_name: str,
    logger: logging.Logger | None = None,
) -> pd.Series:
    """Crée une clé composée '|'-séparée. None si l'une des parties est nulle."""
    missing = [c for c in cols if c not in df.columns]
    if missing:
        if logger:
            logger.warning(f"{key_name} : colonnes manquantes {missing}")
        return pd.Series([None] * len(df), index=df.index, name=key_name)
    result = []
    for i in range(len(df)):
        vals = [df[c].iloc[i] for c in cols]
        if any(v is None or (isinstance(v, float) and np.isnan(v))
               or str(v).strip() in ("", "nan", "None") for v in vals):
            result.append(None)
        else:
            result.append("|".join(str(v) for v in vals))
    return pd.Series(result, index=df.index, name=key_name)


def left_join_label(
    source_df: pd.DataFrame,
    source_key_col: str,
    ref_df: pd.DataFrame,
    ref_key_col: str,
    ref_label_col: str,
    out_label_col: str,
    out_status_col: str,
    fallback_label: str,
) -> pd.DataFrame:
    """
    LEFT JOIN générique pour enrichir source_df avec un libellé depuis ref_df.
    Les codes non mappés reçoivent fallback_label — aucune ligne supprimée.
    """
    df = source_df.copy()
    if source_key_col not in df.columns:
        df[out_label_col]  = fallback_label
        df[out_status_col] = "source_missing"
        return df
    if ref_df.empty or ref_key_col not in ref_df.columns or ref_label_col not in ref_df.columns:
        df[out_label_col]  = fallback_label
        df[out_status_col] = "ref_missing"
        return df
    ref_map           = ref_df.set_index(ref_key_col)[ref_label_col].to_dict()
    df[out_label_col] = df[source_key_col].map(ref_map).fillna(fallback_label)
    df[out_status_col] = df[source_key_col].apply(
        lambda v: "mapped"   if (v is not None and not (isinstance(v, float) and np.isnan(v)) and v in ref_map)
        else "unmapped"      if pd.notna(v)
        else "source_missing"
    )
    return df


def build_unmapped_codes(
    source_df: pd.DataFrame,
    source_col: str,
    ref_df: pd.DataFrame,
    ref_col: str,
    source_dataset: str,
    reference_dataset: str,
    mapping_name: str,
) -> pd.DataFrame:
    """Détecte les codes non mappés. Severity HIGH ≥ 1000, MEDIUM ≥ 100, LOW sinon."""
    if source_col not in source_df.columns:
        return pd.DataFrame()
    if ref_df.empty or ref_col not in ref_df.columns:
        return pd.DataFrame()
    ref_keys = set(ref_df[ref_col].dropna().unique())
    mask     = ~source_df[source_col].isin(ref_keys) & source_df[source_col].notna()
    if mask.sum() == 0:
        return pd.DataFrame()
    freq = source_df.loc[mask, source_col].value_counts().reset_index()
    freq.columns = ["code_value", "occurrences"]
    freq["source_dataset"]    = source_dataset
    freq["source_column"]     = source_col
    freq["reference_dataset"] = reference_dataset
    freq["mapping_name"]      = mapping_name
    freq["severity"]          = freq["occurrences"].apply(
        lambda n: "HIGH" if n >= 1000 else "MEDIUM" if n >= 100 else "LOW"
    )
    return freq[["source_dataset","source_column","code_value","occurrences",
                 "reference_dataset","mapping_name","severity"]]


def add_summary_row(
    summary_rows: list,
    dataset: str,
    mapping_name: str,
    df: pd.DataFrame,
    status_col: str,
    comment: str = "",
) -> None:
    """Accumule une ligne dans le rapport enrichment_summary."""
    if status_col not in df.columns:
        return
    counts = df[status_col].value_counts()
    total      = len(df)
    mapped     = int(counts.get("mapped", 0))
    unmapped   = int(counts.get("unmapped", 0))
    src_miss   = int(counts.get("source_missing", 0))
    rate       = round(100 * mapped / total, 2) if total else 0.0
    summary_rows.append({
        "dataset":             dataset,
        "mapping_name":        mapping_name,
        "rows_total":          total,
        "mapped_rows":         mapped,
        "unmapped_rows":       unmapped,
        "source_missing_rows": src_miss,
        "mapping_rate":        rate,
        "comment":             comment,
    })


def add_dq_check(
    dq_checks: list,
    dataset: str,
    check_name: str,
    columns: str,
    issue_count: int,
    total: int,
    severity: str,
    comment: str = "",
) -> None:
    """Accumule une ligne dans le rapport data_quality_checks."""
    rate = round(100 * issue_count / total, 2) if total else 0.0
    dq_checks.append({
        "dataset":     dataset,
        "check_name":  check_name,
        "columns":     columns,
        "issue_count": issue_count,
        "issue_rate":  rate,
        "severity":    severity,
        "comment":     comment,
    })


def safe_read_excel(
    path: Path,
    header: int | None = 0,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    """Lit un fichier Excel avec message clair si absent."""
    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {path}")
    df = pd.read_excel(path, header=header)
    msg = f"[READ] {path.name} -> {df.shape[0]} lignes x {df.shape[1]} cols"
    if logger:
        logger.info(msg)
    else:
        print(msg)
    return df


def _detect_date_cols(df: pd.DataFrame) -> list[str]:
    # Préfixes DT/DAT ou mot DATE, en excluant UPDATE_* : un simple substring
    # "DT" capturait LIBPRDT (libellé produit) et le détruisait en NaT.
    def _is_date_col(name: str) -> bool:
        u = str(name).upper()
        if "UPDATE" in u:
            return False
        return u.startswith(("DT", "DAT")) or "DATE" in u

    return [c for c in df.columns if _is_date_col(c)]


def _detect_amount_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns
            if any(k in c.upper() for k in ["MONT", "PRIME", "TARIF", "COUT", "VALEUR",
                                              "INDMN", "TOTAL", "MNT", "FRANCHIS"])]


# ─── 5. Reference loaders ─────────────────────────────────────────────────────

def load_ref_produit(logger: logging.Logger) -> pd.DataFrame:
    """Produit.xlsx (header=None) → product_code_norm, product_label_clean."""
    df = safe_read_excel(DATA_RAW / "Produit.xlsx", header=None, logger=logger)
    col_names = ["product_code", "product_family_code", "product_label"]
    df.columns = col_names[: len(df.columns)]
    if "product_code" in df.columns:
        df["product_code_norm"]        = df["product_code"].apply(normalize_code)
    if "product_family_code" in df.columns:
        df["product_family_code_norm"] = df["product_family_code"].apply(normalize_code)
    if "product_label" in df.columns:
        df["product_label_clean"]      = df["product_label"].apply(clean_text)
    return df


def load_ref_garantie(logger: logging.Logger) -> pd.DataFrame:
    """correspondance garantie.xlsx (header=None) → product_guarantee_key."""
    df = safe_read_excel(DATA_RAW / "correspondance garantie.xlsx", header=None, logger=logger)
    col_names = ["product_code", "guarantee_family_code", "guarantee_code",
                 "guarantee_group_code", "guarantee_label", "order_or_flag"]
    df.columns = col_names[: len(df.columns)]
    if "product_code" in df.columns:
        df["product_code_norm"]     = df["product_code"].apply(normalize_code)
    if "guarantee_code" in df.columns:
        df["guarantee_code_norm"]   = df["guarantee_code"].apply(normalize_code)
    if "guarantee_label" in df.columns:
        df["guarantee_label_clean"] = df["guarantee_label"].apply(clean_text)
    if "product_code_norm" in df.columns and "guarantee_code_norm" in df.columns:
        df["product_guarantee_key"] = df.apply(
            lambda r: (
                f"{r['product_code_norm']}|{r['guarantee_code_norm']}"
                if pd.notna(r["product_code_norm"]) and pd.notna(r["guarantee_code_norm"])
                else None
            ),
            axis=1,
        )
    return df


def load_ref_pe033(logger: logging.Logger) -> pd.DataFrame:
    """PE033.xlsx → cnat_norm, client_nature_label."""
    df = safe_read_excel(DATA_RAW / "PE033.xlsx", logger=logger)
    if "CNAT" in df.columns:
        df["cnat_norm"] = df["CNAT"].apply(normalize_code)
    else:
        logger.warning("PE033 : colonne CNAT absente")
    lib_col = next((c for c in df.columns if "LIB" in c.upper()), None)
    if lib_col:
        df["client_nature_label"] = df[lib_col].apply(clean_text)
    else:
        logger.warning("PE033 : colonne libellé absente")
    return df


def load_ref_si001(logger: logging.Logger) -> pd.DataFrame:
    """SI001.xlsx → causesini_norm, libcause_clean."""
    df = safe_read_excel(DATA_RAW / "SI001.xlsx", logger=logger)
    for col, norm in [("CAUSESINI", "causesini_norm"), ("NATSINI", "natsini_norm"),
                      ("GRNTSINI", "grntsini_norm")]:
        if col in df.columns:
            df[norm] = df[col].apply(normalize_code)
    lib_col = next((c for c in df.columns if "LIBCAUSE" in c.upper()), None)
    if lib_col:
        df["libcause_clean"] = df[lib_col].apply(clean_text)
    else:
        logger.warning("SI001 : colonne LIBCAUSE absente")
    return df


def load_ref_pr01(logger: logging.Logger) -> pd.DataFrame:
    """PR01.xlsx → natint_idint_key, local_clean."""
    df = safe_read_excel(DATA_RAW / "PR01.xlsx", logger=logger)
    for col, norm in [("NATINT", "natint_norm"), ("IDINT", "idint_norm")]:
        if col in df.columns:
            df[norm] = df[col].apply(normalize_code)
        else:
            logger.warning(f"PR01 : colonne {col} absente")
    if "LOCAL" in df.columns:
        df["local_clean"] = df["LOCAL"].apply(clean_text)
    if "natint_norm" in df.columns and "idint_norm" in df.columns:
        df["natint_idint_key"] = df.apply(
            lambda r: (
                f"{r['natint_norm']}|{r['idint_norm']}"
                if pd.notna(r["natint_norm"]) and pd.notna(r["idint_norm"])
                else None
            ),
            axis=1,
        )
    return df


def load_ref_pe02(logger: logging.Logger) -> pd.DataFrame:
    """PE02.xlsx — référentiel exploratoire, non utilisé dans les mappings V1."""
    df = safe_read_excel(DATA_RAW / "PE02.xlsx", logger=logger)
    logger.info("PE02 charge (exploratoire - non utilise dans l'enrichissement V1)")
    return df


# ─── 6. Enrichment functions ──────────────────────────────────────────────────

def enrich_production(
    ref_produit: pd.DataFrame,
    ref_pe033: pd.DataFrame,
    ref_pr01: pd.DataFrame,
    logger: logging.Logger,
    all_unmapped: list,
    dq_checks: list,
    summary_rows: list,
) -> pd.DataFrame:
    """
    Enrichit Production.xlsx avec :
      M001 : CODPROD → product_label
      M005 : NATCLT → client_nature_label
      M007 : NATINT+IDINT → intermediary_location_label
      AUTO_SCOPE_001 : is_auto_scope (CODPROD LIKE '5%')
    """
    logger.info("-- Enrichissement Production --------------------------------------------------")
    df = safe_read_excel(DATA_RAW / "Production.xlsx", logger=logger)

    # ── Normalisation codes ───────────────────────────────────────────────────
    code_map = {
        "NUMCNT":  "numcnt_norm",
        "NUMAVT":  "numavt_norm",
        "NUMMAJ":  "nummaj_norm",
        "CODPROD": "codprod_norm",
        "NATCLT":  "natclt_norm",
        "NATINT":  "natint_norm",
        "IDINT":   "idint_norm",
        "CODFAM":  "codfam_norm",
    }
    for src, tgt in code_map.items():
        if src in df.columns:
            df[tgt] = df[src].apply(normalize_code)
        else:
            logger.warning(f"Production : colonne '{src}' absente")

    # ── Clés composées ────────────────────────────────────────────────────────
    df["contract_key"] = make_composite_key(
        df, ["numcnt_norm", "numavt_norm", "nummaj_norm"], "contract_key", logger
    )
    if "natint_norm" in df.columns and "idint_norm" in df.columns:
        df["natint_idint_key"] = df.apply(
            lambda r: (
                f"{r['natint_norm']}|{r['idint_norm']}"
                if pd.notna(r["natint_norm"]) and pd.notna(r["idint_norm"])
                else None
            ),
            axis=1,
        )

    # ── Dates et montants ─────────────────────────────────────────────────────
    for col in _detect_date_cols(df):
        df[col] = parse_date_safe(df[col])
    for col in _detect_amount_cols(df):
        df[col] = parse_numeric_safe(df[col])

    # ── DQ checks ─────────────────────────────────────────────────────────────
    n = len(df)
    for col, check in [("contract_key", "contract_key_missing"),
                       ("codprod_norm", "codprod_missing")]:
        if col in df.columns:
            cnt = int(df[col].isna().sum())
            if cnt:
                sev = "HIGH" if col == "contract_key" else "MEDIUM"
                add_dq_check(dq_checks, "production", check, col, cnt, n, sev)
                logger.warning(f"Production.{col} : {cnt} nulls ({100*cnt/n:.1f}%)")

    if "contract_key" in df.columns:
        dup = int(df["contract_key"].dropna().duplicated().sum())
        if dup:
            add_dq_check(dq_checks, "production", "duplicate_contract_key",
                         "contract_key", dup, n, "HIGH")
            logger.warning(f"Production.contract_key : {dup} doublons")

    # ── M001 — Produit ────────────────────────────────────────────────────────
    df = left_join_label(
        df, "codprod_norm",
        ref_produit, "product_code_norm", "product_label_clean",
        "product_label", "product_mapping_status",
        FALLBACK["produit"],
    )
    um = build_unmapped_codes(df, "codprod_norm", ref_produit, "product_code_norm",
                               "enriched_production", "Produit.xlsx", "M001_produit")
    if not um.empty:
        all_unmapped.append(um)
        logger.warning(f"M001 : {len(um)} codes CODPROD non mappés")
    add_summary_row(summary_rows, "production", "M001_produit",
                    df, "product_mapping_status", "CODPROD → product_label")

    # ── M005 — Nature client ──────────────────────────────────────────────────
    df = left_join_label(
        df, "natclt_norm",
        ref_pe033, "cnat_norm", "client_nature_label",
        "client_nature_label", "client_nature_mapping_status",
        FALLBACK["nature_client"],
    )
    um = build_unmapped_codes(df, "natclt_norm", ref_pe033, "cnat_norm",
                               "enriched_production", "PE033.xlsx", "M005_nature_client")
    if not um.empty:
        all_unmapped.append(um)
    add_summary_row(summary_rows, "production", "M005_nature_client",
                    df, "client_nature_mapping_status", "NATCLT → client_nature_label")

    # ── M007 — Intermédiaire ──────────────────────────────────────────────────
    if "natint_idint_key" in df.columns and "natint_idint_key" in ref_pr01.columns:
        df = left_join_label(
            df, "natint_idint_key",
            ref_pr01, "natint_idint_key", "local_clean",
            "intermediary_location_label", "intermediary_mapping_status",
            FALLBACK["intermediaire"],
        )
        um = build_unmapped_codes(df, "natint_idint_key", ref_pr01, "natint_idint_key",
                                   "enriched_production", "PR01.xlsx", "M007_intermediaire")
        if not um.empty:
            all_unmapped.append(um)
        add_summary_row(summary_rows, "production", "M007_intermediaire",
                        df, "intermediary_mapping_status", "NATINT+IDINT → intermediary_location_label")
    else:
        df["intermediary_location_label"] = FALLBACK["intermediaire"]
        df["intermediary_mapping_status"] = "source_missing"
        logger.warning("M007 : cle NATINT+IDINT absente - fallback applique")

    # ── AUTO_SCOPE_001 ────────────────────────────────────────────────────────
    if "codprod_norm" in df.columns:
        df["is_auto_scope"]    = (
            df["codprod_norm"].notna() &
            df["codprod_norm"].astype(str).str.startswith("5")
        )
    else:
        df["is_auto_scope"] = False
    df["auto_scope_rule"]   = AUTO_SCOPE_RULE
    df["auto_scope_status"] = AUTO_SCOPE_STATUS

    n_auto = int(df["is_auto_scope"].sum())
    logger.info(
        f"Production enrichie : {len(df)} lignes | "
        f"AUTO_SCOPE_001 = {n_auto} ({100*n_auto/max(len(df),1):.1f}%)"
    )

    # ── Export ────────────────────────────────────────────────────────────────
    out = DATA_PROC / "enriched_production.xlsx"
    df.to_excel(out, index=False)
    logger.info(f"[OK] {out.name}")
    return df


def _diagnose_join(
    sin_df: pd.DataFrame,
    prod_df: pd.DataFrame,
    logger: logging.Logger,
) -> tuple[str, pd.DataFrame, list[dict]]:
    """
    Teste 3 strategies de jointure Sinistres -> Production pour recuperer CODPROD.

    Priorite metier (decroissante) :
      1. S1_3keys  si match_rate >= 95%  (cle la plus precise)
      2. S2_2keys  si match_rate >= 95%  (S1 insuffisant — NUMCNT+NUMAVT acceptable)
      3. S3_1key   fallback exceptionnel (NUMCNT seul = tres ambigu, risk HIGH)

    Retourne (selected_strategy_name, sin_df_with_codprod, diagnostics_rows).
    """
    logger.info("Diagnostic jointure Sinistres <-> Production :")

    strategies = [
        ("S1_3keys", ["numcnt_norm", "numavt_norm", "nummaj_norm"],
                     ["numcnt_norm", "numavt_norm", "nummaj_norm"]),
        ("S2_2keys", ["numcnt_norm", "numavt_norm"],
                     ["numcnt_norm", "numavt_norm"]),
        ("S3_1key",  ["numcnt_norm"],
                     ["numcnt_norm"]),
    ]

    # Niveau de risque métier par stratégie (précision décroissante)
    RISK = {"S1_3keys": "LOW", "S2_2keys": "LOW", "S3_1key": "HIGH"}

    # ── Passe 1 : calcul des stats sans copier le DataFrame complet ───────────
    # On garde uniquement les Series légères + le dict de mapping.
    computed: dict = {}   # strat_name -> stats dict
    missing:  dict = {}   # strat_name -> raison

    for strat_name, sin_cols, prod_cols in strategies:
        sin_ok  = all(c in sin_df.columns  for c in sin_cols)
        prod_ok = all(c in prod_df.columns for c in prod_cols)
        if not sin_ok or not prod_ok:
            missing[strat_name] = "Colonnes manquantes"
            continue

        sin_key = sin_df[sin_cols].apply(
            lambda r: "|".join(str(v) for v in r)
            if all(pd.notna(v) for v in r) else None,
            axis=1,
        )
        prod_key = prod_df[prod_cols].apply(
            lambda r: "|".join(str(v) for v in r)
            if all(pd.notna(v) for v in r) else None,
            axis=1,
        )

        prod_tmp       = prod_df.assign(_jk=prod_key)
        prod_dup_count = int(prod_tmp["_jk"].dropna().duplicated().sum())
        prod_dedup     = prod_tmp.dropna(subset=["_jk"]).drop_duplicates("_jk")
        key_to_codprod = prod_dedup.set_index("_jk")["codprod_norm"].to_dict()

        sin_has_key = sin_key.notna()
        matched     = int(sin_key[sin_has_key].isin(key_to_codprod).sum())
        total       = len(sin_df)
        match_rate  = round(100 * matched / total, 2) if total else 0.0

        computed[strat_name] = {
            "sin_cols":      sin_cols,
            "prod_cols":     prod_cols,
            "matched":       matched,
            "total":         total,
            "match_rate":    match_rate,
            "prod_dup_count": prod_dup_count,
            "key_to_codprod": key_to_codprod,
            "sin_key":       sin_key,
        }

        logger.info(
            f"  {strat_name:<12} -> {matched}/{total} matches ({match_rate:.1f}%) "
            f"| doublons prod : {prod_dup_count}"
        )

    # ── Passe 2 : sélection par priorité métier ───────────────────────────────
    s1 = computed.get("S1_3keys")
    s2 = computed.get("S2_2keys")
    s3 = computed.get("S3_1key")

    selected_name    = "NONE"
    selection_reason = ""

    if s1 and s1["match_rate"] >= 95.0:
        selected_name    = "S1_3keys"
        selection_reason = (
            f"S1 retenue : match_rate={s1['match_rate']:.1f}% >= 95%, "
            f"cle 3 champs (NUMCNT+NUMAVT+NUMMAJ) — precision maximale"
        )
    elif s2 and s2["match_rate"] >= 95.0:
        selected_name    = "S2_2keys"
        s1_info = f"{s1['match_rate']:.1f}%" if s1 else "N/A"
        selection_reason = (
            f"S2 retenue : match_rate={s2['match_rate']:.1f}% >= 95%, "
            f"doublons prod={s2['prod_dup_count']} (acceptable). "
            f"S1 insuffisant ({s1_info} < 95%)"
        )
    elif s3:
        selected_name    = "S3_1key"
        s2_info = f"{s2['match_rate']:.1f}%" if s2 else "N/A"
        selection_reason = (
            f"FALLBACK S3 : S1 et S2 sous 95% de match. "
            f"S2={s2_info}. NUMCNT seul tres ambigu "
            f"({s3['prod_dup_count']} doublons prod) — risque HIGH"
        )
    else:
        selection_reason = "Aucune strategie calculable — colonnes manquantes"

    # Log de la décision
    if selected_name in computed:
        sel = computed[selected_name]
        logger.info(f"Strategie retenue : {selected_name} ({sel['match_rate']:.1f}% de match)")
        logger.info(f"  Raison : {selection_reason}")
        if selected_name == "S3_1key":
            logger.warning(
                f"RISK HIGH : S3_1key retenu en fallback — "
                f"{sel['prod_dup_count']} doublons cote Production sur NUMCNT seul"
            )
        if sel["match_rate"] < 95.0:
            logger.warning(
                f"ATTENTION : strategie retenue {selected_name} = {sel['match_rate']:.1f}% < 95%. "
                f"Verifier coherence NUMCNT entre Production et Sinistres."
            )
    else:
        logger.warning(f"Aucune strategie valide : {selection_reason}")

    # ── Construction des diag_rows avec champs selection ─────────────────────
    diag_rows = []
    for strat_name, sin_cols, prod_cols in strategies:
        if strat_name in missing:
            diag_rows.append({
                "join_strategy":                strat_name,
                "join_columns_sinistres":       "+".join(sin_cols),
                "join_columns_production":      "+".join(prod_cols),
                "matched_rows":                 None,
                "unmatched_rows":               None,
                "match_rate":                   None,
                "duplicates_in_production_key": None,
                "risk_level":                   RISK[strat_name],
                "selected_strategy":            False,
                "selection_reason":             missing[strat_name],
            })
        else:
            c = computed[strat_name]
            is_selected = (strat_name == selected_name)
            reason = selection_reason if is_selected else (
                "Non retenue : priorite metier inferieure ou criteres non remplis"
            )
            diag_rows.append({
                "join_strategy":                strat_name,
                "join_columns_sinistres":       "+".join(c["sin_cols"]),
                "join_columns_production":      "+".join(c["prod_cols"]),
                "matched_rows":                 c["matched"],
                "unmatched_rows":               c["total"] - c["matched"],
                "match_rate":                   c["match_rate"],
                "duplicates_in_production_key": c["prod_dup_count"],
                "risk_level":                   RISK[strat_name],
                "selected_strategy":            is_selected,
                "selection_reason":             reason,
            })

    # ── Passe 3 : construction du DataFrame final (copie unique) ─────────────
    if selected_name in computed:
        sel = computed[selected_name]
        sin_result = sin_df.copy()
        sin_result["codprod_from_contract"]  = sel["sin_key"].map(sel["key_to_codprod"])
        sin_result["contract_join_strategy"] = selected_name
        sin_result["contract_join_status"]   = sin_result["codprod_from_contract"].apply(
            lambda v: "matched" if pd.notna(v) else "unmatched"
        )
        best_result = sin_result
    else:
        sin_result = sin_df.copy()
        sin_result["codprod_from_contract"]  = None
        sin_result["contract_join_strategy"] = "NONE"
        sin_result["contract_join_status"]   = "unmatched"
        best_result = sin_result

    return selected_name, best_result, diag_rows


def enrich_sinistres(
    enr_prod_df: pd.DataFrame,
    ref_garantie: pd.DataFrame,
    ref_pe033: pd.DataFrame,
    ref_si001: pd.DataFrame,
    logger: logging.Logger,
    all_unmapped: list,
    dq_checks: list,
    summary_rows: list,
) -> pd.DataFrame:
    """
    Enrichit Sinistres.xlsx avec :
      Pré-jointure Production : codprod_from_contract
      M002 : CODPROD+GRNTSINI → guarantee_label
      M006 : NATCLT → client_nature_label
      M008 : CAUSESINI → claim_cause_label
      AUTO_SCOPE_001 : is_auto_scope sur codprod_from_contract
    """
    logger.info("-- Enrichissement Sinistres ---------------------------------------------------")
    df = safe_read_excel(DATA_RAW / "Sinistres.xlsx", logger=logger)

    # ── Normalisation codes ───────────────────────────────────────────────────
    code_map = {
        "NUMSNT":   "numsnt_norm",
        "GRNTSINI": "grntsini_norm",
        "NATCLT":   "natclt_norm",
        "CAUSESINI":"causesini_norm",
        "NUMCNT":   "numcnt_norm",
        "NUMAVT":   "numavt_norm",
        "NUMMAJ":   "nummaj_norm",
        "NATINT":   "natint_norm",
        "IDINT":    "idint_norm",
    }
    for src, tgt in code_map.items():
        if src in df.columns:
            df[tgt] = df[src].apply(normalize_code)

    # ── Clé sinistre ─────────────────────────────────────────────────────────
    df["claim_key"] = make_composite_key(
        df, ["numsnt_norm", "grntsini_norm"], "claim_key", logger
    )
    df["contract_key"] = make_composite_key(
        df, ["numcnt_norm", "numavt_norm", "nummaj_norm"], "contract_key", logger
    )

    # ── Dates et montants ─────────────────────────────────────────────────────
    for col in _detect_date_cols(df):
        df[col] = parse_date_safe(df[col])
    for col in _detect_amount_cols(df):
        df[col] = parse_numeric_safe(df[col])

    # ── DQ checks sinistres ───────────────────────────────────────────────────
    n = len(df)
    for col, check in [("claim_key", "claim_key_missing"),
                       ("contract_key", "contract_key_missing")]:
        if col in df.columns:
            cnt = int(df[col].isna().sum())
            if cnt:
                add_dq_check(dq_checks, "sinistres", check, col, cnt, n,
                             "HIGH" if col == "claim_key" else "MEDIUM")
                logger.warning(f"Sinistres.{col} : {cnt} nulls ({100*cnt/n:.1f}%)")

    if "claim_key" in df.columns:
        dup = int(df["claim_key"].dropna().duplicated().sum())
        if dup:
            add_dq_check(dq_checks, "sinistres", "duplicate_claim_key",
                         "claim_key", dup, n, "HIGH")

    # ── Pré-jointure : récupération CODPROD depuis Production ────────────────
    best_strat, df, diag_rows = _diagnose_join(df, enr_prod_df, logger)

    # Export rapport diagnostic
    diag_df = pd.DataFrame(diag_rows)
    diag_path = REPORTS / "sinistres_production_join_diagnostics.xlsx"
    diag_df.to_excel(diag_path, index=False)
    logger.info(f"[OK] {diag_path.name}")

    # DQ : sinistres sans CODPROD
    if "codprod_from_contract" in df.columns:
        n_no_cp = int(df["codprod_from_contract"].isna().sum())
        if n_no_cp:
            rate = 100 * n_no_cp / n
            sev  = "HIGH" if rate > 10 else "MEDIUM"
            add_dq_check(dq_checks, "sinistres", "codprod_from_contract_missing",
                         "codprod_from_contract", n_no_cp, n, sev,
                         f"Stratégie retenue : {best_strat}")
            logger.warning(
                f"Sinistres : {n_no_cp} lignes sans CODPROD "
                f"({rate:.1f}%) | strategie {best_strat}"
            )

    # ── M002 — Garantie officielle (CODPROD + GRNTSINI) ──────────────────────
    if "codprod_from_contract" in df.columns and "grntsini_norm" in df.columns:
        df["product_guarantee_key"] = df.apply(
            lambda r: (
                f"{r['codprod_from_contract']}|{r['grntsini_norm']}"
                if pd.notna(r["codprod_from_contract"]) and pd.notna(r["grntsini_norm"])
                else None
            ),
            axis=1,
        )
    else:
        df["product_guarantee_key"] = None

    if "product_guarantee_key" in ref_garantie.columns:
        df = left_join_label(
            df, "product_guarantee_key",
            ref_garantie, "product_guarantee_key", "guarantee_label_clean",
            "guarantee_label", "guarantee_mapping_status",
            FALLBACK["garantie"],
        )
        um = build_unmapped_codes(
            df, "product_guarantee_key",
            ref_garantie, "product_guarantee_key",
            "enriched_sinistres", "correspondance garantie.xlsx", "M002_garantie",
        )
        if not um.empty:
            all_unmapped.append(um)
            logger.warning(f"M002 : {len(um)} clés CODPROD+GRNTSINI non mappées")
    else:
        df["guarantee_label"]          = FALLBACK["garantie"]
        df["guarantee_mapping_status"] = "ref_missing"
    add_summary_row(summary_rows, "sinistres", "M002_garantie",
                    df, "guarantee_mapping_status",
                    "CODPROD+GRNTSINI → guarantee_label (règle officielle)")

    # ── M006 — Nature client ──────────────────────────────────────────────────
    df = left_join_label(
        df, "natclt_norm",
        ref_pe033, "cnat_norm", "client_nature_label",
        "client_nature_label", "client_nature_mapping_status",
        FALLBACK["nature_client"],
    )
    um = build_unmapped_codes(df, "natclt_norm", ref_pe033, "cnat_norm",
                               "enriched_sinistres", "PE033.xlsx", "M006_nature_client")
    if not um.empty:
        all_unmapped.append(um)
    add_summary_row(summary_rows, "sinistres", "M006_nature_client",
                    df, "client_nature_mapping_status", "NATCLT → client_nature_label")

    # ── M008 — Cause sinistre ─────────────────────────────────────────────────
    si_cause_col = "causesini_norm" if "causesini_norm" in ref_si001.columns else None
    si_label_col = "libcause_clean" if "libcause_clean" in ref_si001.columns else None

    if si_cause_col and si_label_col:
        df = left_join_label(
            df, "causesini_norm",
            ref_si001, si_cause_col, si_label_col,
            "claim_cause_label", "claim_cause_mapping_status",
            FALLBACK["cause_sinistre"],
        )
        um = build_unmapped_codes(df, "causesini_norm", ref_si001, si_cause_col,
                                   "enriched_sinistres", "SI001.xlsx", "M008_cause_sinistre")
        if not um.empty:
            all_unmapped.append(um)
    else:
        df["claim_cause_label"]          = FALLBACK["cause_sinistre"]
        df["claim_cause_mapping_status"] = "ref_missing"
        logger.warning("M008 : colonnes CAUSESINI/LIBCAUSE absentes dans SI001")
    add_summary_row(summary_rows, "sinistres", "M008_cause_sinistre",
                    df, "claim_cause_mapping_status", "CAUSESINI → claim_cause_label")

    # ── AUTO_SCOPE_001 ────────────────────────────────────────────────────────
    codprod_col = "codprod_from_contract"
    if codprod_col in df.columns:
        df["is_auto_scope"] = (
            df[codprod_col].notna() &
            df[codprod_col].astype(str).str.startswith("5")
        )
    else:
        df["is_auto_scope"] = False
    df["auto_scope_rule"]   = AUTO_SCOPE_RULE
    df["auto_scope_status"] = AUTO_SCOPE_STATUS

    n_auto = int(df["is_auto_scope"].sum())
    logger.info(
        f"Sinistres enrichis : {len(df)} lignes | "
        f"AUTO_SCOPE_001 = {n_auto} ({100*n_auto/max(len(df),1):.1f}%)"
    )

    # ── Export ────────────────────────────────────────────────────────────────
    out = DATA_PROC / "enriched_sinistres.xlsx"
    df.to_excel(out, index=False)
    logger.info(f"[OK] {out.name}")
    return df


def enrich_clients(
    ref_pe033: pd.DataFrame,
    logger: logging.Logger,
    all_unmapped: list,
    dq_checks: list,
    summary_rows: list,
) -> pd.DataFrame:
    """
    Enrichit Clients.xlsx avec :
      M004 : CNAT → client_nature_label
    """
    logger.info("-- Enrichissement Clients -----------------------------------------------")
    df = safe_read_excel(DATA_RAW / "Clients.xlsx", logger=logger)

    for src, tgt in [("CNAT", "cnat_norm"), ("NUMPERS", "numpers_norm")]:
        if src in df.columns:
            df[tgt] = df[src].apply(normalize_code)
        else:
            logger.warning(f"Clients : colonne '{src}' absente")

    df["client_key"] = make_composite_key(
        df, ["cnat_norm", "numpers_norm"], "client_key", logger
    )

    for col in _detect_date_cols(df):
        df[col] = parse_date_safe(df[col])

    # ── DQ checks ─────────────────────────────────────────────────────────────
    n = len(df)
    if "client_key" in df.columns:
        cnt = int(df["client_key"].isna().sum())
        if cnt:
            add_dq_check(dq_checks, "clients", "client_key_missing",
                         "client_key", cnt, n, "HIGH")
            logger.warning(f"Clients.client_key : {cnt} nulls ({100*cnt/n:.1f}%)")
        dup = int(df["client_key"].dropna().duplicated().sum())
        if dup:
            add_dq_check(dq_checks, "clients", "duplicate_client_key",
                         "client_key", dup, n, "MEDIUM")

    # ── M004 — Nature client ──────────────────────────────────────────────────
    df = left_join_label(
        df, "cnat_norm",
        ref_pe033, "cnat_norm", "client_nature_label",
        "client_nature_label", "client_nature_mapping_status",
        FALLBACK["nature_client"],
    )
    um = build_unmapped_codes(df, "cnat_norm", ref_pe033, "cnat_norm",
                               "enriched_clients", "PE033.xlsx", "M004_nature_client")
    if not um.empty:
        all_unmapped.append(um)
    add_summary_row(summary_rows, "clients", "M004_nature_client",
                    df, "client_nature_mapping_status", "CNAT → client_nature_label")

    logger.info(f"Clients enrichis : {len(df)} lignes")

    out = DATA_PROC / "enriched_clients.xlsx"
    df.to_excel(out, index=False)
    logger.info(f"[OK] {out.name}")
    return df


def prepare_inspection(
    logger: logging.Logger,
    dq_checks: list,
    summary_rows: list,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Prépare FicheVoitureStafim.xlsx :
      - Normalise immat, date, km
      - Standardise les noms de colonnes (évite DuplicateColumn PostgreSQL)
      - Aucun enrichissement référentiel V1
    """
    logger.info("-- Preparation Inspection -----------------------------------------------")
    df = safe_read_excel(DATA_RAW / "FicheVoitureStafim.xlsx", logger=logger)

    # ── Détection des colonnes clés (avant renommage) ─────────────────────────
    immat_col = next(
        (c for c in df.columns
         if any(k in c.upper() for k in ["IMMATRICUL", "IMMAT", "N D IMMAT", "N°D'IMMAT",
                                          "IMMATR", "IMMATRICULATION"])),
        None,
    )
    date_col = next(
        (c for c in df.columns
         if any(k in c.upper() for k in ["HORODATEUR", "HORODAT"]) or c.upper() == "DATE"),
        None,
    )
    km_col = next(
        (c for c in df.columns
         if any(k in c.upper() for k in ["KILOMETRAGE", "KILOM", "KM"])),
        None,
    )
    logger.info(
        f"Inspection - detection : immat='{immat_col}' | date='{date_col}' | km='{km_col}'"
    )

    # ── Colonnes calculées (avant standardisation) ────────────────────────────
    if immat_col:
        df["immat_norm"] = df[immat_col].apply(normalize_immat)
    else:
        logger.warning("Inspection : colonne immatriculation non détectée")
        df["immat_norm"] = None

    if date_col:
        df["inspection_date"] = parse_date_safe(df[date_col])
    else:
        logger.warning("Inspection : colonne date non détectée")
        df["inspection_date"] = pd.NaT

    if km_col:
        df["kilometrage_numeric"] = parse_numeric_safe(df[km_col])

    df["inspection_key"] = df.apply(
        lambda r: (
            f"{r['immat_norm']}|{str(r['inspection_date'])[:10]}"
            if pd.notna(r.get("immat_norm")) and pd.notna(r.get("inspection_date"))
            else None
        ),
        axis=1,
    )

    # ── DQ checks ─────────────────────────────────────────────────────────────
    n = len(df)
    n_null_immat = int(df["immat_norm"].isna().sum())
    n_null_date  = int(df["inspection_date"].isna().sum()) if "inspection_date" in df.columns else 0
    if n_null_immat:
        add_dq_check(dq_checks, "inspection", "immat_norm_missing",
                     "immat_norm", n_null_immat, n, "MEDIUM")
        logger.warning(f"Inspection.immat_norm : {n_null_immat} nulls")
    if n_null_date:
        add_dq_check(dq_checks, "inspection", "inspection_date_missing",
                     "inspection_date", n_null_date, n, "MEDIUM")
        logger.warning(f"Inspection.inspection_date : {n_null_date} nulls")

    if "inspection_key" in df.columns:
        dup = int(df["inspection_key"].dropna().duplicated().sum())
        if dup:
            add_dq_check(dq_checks, "inspection", "duplicate_inspection_key",
                         "inspection_key", dup, n, "LOW",
                         "Même immat inspectée plusieurs fois (attendu)")

    summary_rows.append({
        "dataset": "inspection",
        "mapping_name": "preparation_technique",
        "rows_total": n,
        "mapped_rows": n - n_null_immat,
        "unmapped_rows": 0,
        "source_missing_rows": n_null_immat,
        "mapping_rate": round(100 * (n - n_null_immat) / n, 2) if n else 0.0,
        "comment": "Normalisation immat+date+km — pas d'enrichissement référentiel V1",
    })

    # ── Standardisation des noms de colonnes ──────────────────────────────────
    df, col_mapping_df = standardize_dataframe_columns(
        df, "enriched_inspection", logger
    )

    # Export mapping colonnes
    col_map_path = REPORTS / "column_mapping_inspection.xlsx"
    col_mapping_df.to_excel(col_map_path, index=False)
    logger.info(f"[OK] {col_map_path.name}")

    logger.info(f"Inspection préparée : {len(df)} lignes, {df.shape[1]} cols (noms standardisés)")

    out = DATA_PROC / "enriched_inspection.xlsx"
    df.to_excel(out, index=False)
    logger.info(f"[OK] {out.name}")
    return df, col_mapping_df


# ─── 7. Report exporters ──────────────────────────────────────────────────────

def _write_excel(path: Path, df: pd.DataFrame, logger: logging.Logger) -> None:
    """Exporte un DataFrame vers Excel."""
    df.to_excel(path, index=False)
    logger.info(f"[OK] {path.name} - {len(df)} lignes")


def export_unmapped_codes(
    all_unmapped: list[pd.DataFrame],
    logger: logging.Logger,
) -> None:
    path = REPORTS / "unmapped_codes.xlsx"
    if all_unmapped:
        df = pd.concat(all_unmapped, ignore_index=True)
    else:
        df = pd.DataFrame(columns=["source_dataset","source_column","code_value",
                                    "occurrences","reference_dataset","mapping_name","severity"])
    _write_excel(path, df, logger)


def export_enrichment_summary(
    summary_rows: list[dict],
    logger: logging.Logger,
) -> None:
    path = REPORTS / "enrichment_summary.xlsx"
    df = pd.DataFrame(summary_rows, columns=[
        "dataset","mapping_name","rows_total","mapped_rows",
        "unmapped_rows","source_missing_rows","mapping_rate","comment",
    ])
    _write_excel(path, df, logger)


def export_dq_checks(
    dq_checks: list[dict],
    logger: logging.Logger,
) -> None:
    path = REPORTS / "data_quality_checks.xlsx"
    df = pd.DataFrame(dq_checks, columns=[
        "dataset","check_name","columns","issue_count","issue_rate","severity","comment",
    ])
    _write_excel(path, df, logger)


# ─── 8. Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    started_at = datetime.utcnow()
    logger = setup_logging(run_id)

    logger.info("=" * 70)
    logger.info(f"IRIS Auto Fraud | Preprocessing enrichi | run_id : {run_id}")
    logger.info("=" * 70)

    all_unmapped: list[pd.DataFrame] = []
    dq_checks:    list[dict]         = []
    summary_rows: list[dict]         = []

    try:
        # ── Chargement des référentiels ───────────────────────────────────────
        logger.info("--- Referentiels -----------------------------------------------")
        ref_produit  = load_ref_produit(logger)
        ref_garantie = load_ref_garantie(logger)
        ref_pe033    = load_ref_pe033(logger)
        ref_si001    = load_ref_si001(logger)
        ref_pr01     = load_ref_pr01(logger)
        _            = load_ref_pe02(logger)

        # ── Enrichissements ───────────────────────────────────────────────────
        logger.info("--- Enrichissements -----------------------------------------------------------")
        enr_prod  = enrich_production(
            ref_produit, ref_pe033, ref_pr01,
            logger, all_unmapped, dq_checks, summary_rows,
        )
        enr_sin   = enrich_sinistres(
            enr_prod, ref_garantie, ref_pe033, ref_si001,
            logger, all_unmapped, dq_checks, summary_rows,
        )
        enr_cli   = enrich_clients(
            ref_pe033, logger, all_unmapped, dq_checks, summary_rows,
        )
        enr_insp, _ = prepare_inspection(logger, dq_checks, summary_rows)

        # ── Rapports ─────────────────────────────────────────────────────────
        logger.info("--- Rapports ------------------------------------------------------------------")
        export_unmapped_codes(all_unmapped, logger)
        export_enrichment_summary(summary_rows, logger)
        export_dq_checks(dq_checks, logger)

        # ── Résumé console ────────────────────────────────────────────────────
        elapsed = (datetime.utcnow() - started_at).total_seconds()

        n_auto_prod = int(enr_prod["is_auto_scope"].sum()) if "is_auto_scope" in enr_prod.columns else 0
        n_auto_sin  = int(enr_sin["is_auto_scope"].sum())  if "is_auto_scope" in enr_sin.columns  else 0
        rate_prod   = 100 * n_auto_prod / max(len(enr_prod), 1)
        rate_sin    = 100 * n_auto_sin  / max(len(enr_sin),  1)
        n_unmapped  = sum(len(u) for u in all_unmapped)

        strat = ""
        if "contract_join_strategy" in enr_sin.columns:
            strat = enr_sin["contract_join_strategy"].iloc[0] if len(enr_sin) else "N/A"
        match_rate = "N/A"
        if "contract_join_status" in enr_sin.columns and len(enr_sin):
            matched = int((enr_sin["contract_join_status"] == "matched").sum())
            match_rate = f"{100*matched/len(enr_sin):.1f}%"

        logger.info("=" * 70)
        logger.info(f"RESUME  run_id : {run_id} | {elapsed:.1f}s | STATUS : SUCCESS")
        logger.info(f"  enriched_production : {len(enr_prod):>8} lignes"
                    f"  | taux AUTO_SCOPE_001 = {rate_prod:.1f}%")
        logger.info(f"  enriched_sinistres  : {len(enr_sin):>8} lignes"
                    f"  | taux AUTO_SCOPE_001 = {rate_sin:.1f}%")
        logger.info(f"  enriched_clients    : {len(enr_cli):>8} lignes")
        logger.info(f"  enriched_inspection : {len(enr_insp):>8} lignes")
        logger.info(f"  Jointure sin-prod   : stratégie={strat} | match_rate={match_rate}")
        logger.info(f"  Codes non mappés    : {n_unmapped}")
        logger.info(f"  Issues DQ           : {len(dq_checks)}")
        logger.info(f"  Fichiers générés :")
        for f in [
            DATA_PROC / "enriched_production.xlsx",
            DATA_PROC / "enriched_sinistres.xlsx",
            DATA_PROC / "enriched_clients.xlsx",
            DATA_PROC / "enriched_inspection.xlsx",
            REPORTS   / "enrichment_summary.xlsx",
            REPORTS   / "unmapped_codes.xlsx",
            REPORTS   / "data_quality_checks.xlsx",
            REPORTS   / "sinistres_production_join_diagnostics.xlsx",
            REPORTS   / "column_mapping_inspection.xlsx",
        ]:
            status = "OK" if f.exists() else "MANQUANT"
            logger.info(f"    [{status}] {f.relative_to(BASE_DIR)}")
        logger.info("=" * 70)

    except Exception as exc:
        logger.exception(f"Erreur critique : {exc}")
        sys.exit(1)


# ─── 9. Entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
