"""
etl/dwh/load_dim_garantie.py
============================
Build dwh.dim_garantie from observed claim guarantees.

Grain:
  one row per CODPROD + GRNTSINI observed in staging.stg_sinistres.

Business key:
  garantie_key = CODPROD || '|' || GRNTSINI

Important modelling rule:
  observed guarantee combinations must not disappear from dim_garantie only
  because the reference label is missing. Missing-reference combinations are
  loaded with libelle_garantie = UNKNOWN and documented in a quality report.

Usage:
  python etl/dwh/load_dim_garantie.py
"""
from __future__ import annotations

import math
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwh_utils


BASE_DIR = Path(__file__).resolve().parent.parent.parent
TABLE_NAME = "dim_garantie"
SOURCE_TABLE = "staging.stg_sinistres"
SOURCE_SYSTEM = "BNA_ASSURANCES"
TODAY = datetime.now(timezone.utc).replace(tzinfo=None)

REPORT_DIR = BASE_DIR / "data" / "quality_reports" / "dim_garantie"
MISSING_REFERENCE_REPORT = REPORT_DIR / "dim_garantie_missing_reference_observed.csv"

UNKNOWN = "UNKNOWN"
UNKNOWN_KEY = "UNKNOWN|UNKNOWN"
QUALITY_VALIDATED_REFERENCE = "VALIDATED_REFERENCE"
QUALITY_OBSERVED_MISSING_REFERENCE = "OBSERVED_IN_SINISTRES_MISSING_REFERENCE"

FINAL_COLS = [
    "garantie_sk",
    "garantie_key",
    "code_produit",
    "code_garantie",
    "libelle_garantie",
    "garantie_quality_level",
    "source_system",
    "created_at",
]

INVALID_TEXT = frozenset(
    {
        "",
        "NAN",
        "NONE",
        "NULL",
        "UNKNOWN",
        "NON MAPPE",
        "NON MAPPED",
        "NON MAPPED GUARANTEE",
        "NON MAPPED GARANTIE",
        "NON RENSEIGNE",
        "NON RENSEIGNEE",
        "NOT MAPPED",
        "#N/A",
        "N/A",
        "NA",
    }
)


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value)


def _remove_accents(value: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFD", value)
        if unicodedata.category(c) != "Mn"
    )


def _clean_code(value: object) -> str | None:
    if _is_missing(value):
        return None
    s = str(value).strip().upper()
    if s in INVALID_TEXT:
        return None
    try:
        number = float(s)
        if number.is_integer():
            s = str(int(number))
    except ValueError:
        pass
    if s.endswith(".0"):
        s = s[:-2]
    s = re.sub(r"\s+", "", s)
    return s if s and s not in INVALID_TEXT else None


def _clean_text(value: object) -> str | None:
    if _is_missing(value):
        return None
    s = str(value).strip().upper()
    s = s.replace("-", " ").replace("_", " ").replace("'", " ").replace(".", " ")
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None
    s_no_accents = _remove_accents(s)
    return None if s_no_accents in INVALID_TEXT else s


def _normalise_label(value: object) -> str | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None

    no_accents = _remove_accents(cleaned)
    exact = {
        "RC": "RESPONSABILITE CIVILE",
        "R C": "RESPONSABILITE CIVILE",
        "RESP CIVILE": "RESPONSABILITE CIVILE",
        "RESPONSABILITE CIVILE": "RESPONSABILITE CIVILE",
        "RESP CIVILE MATERIELLE": "RESPONSABILITE CIVILE MATERIELLE",
        "RESPONSABILITE CIVILE MATERIELLE": "RESPONSABILITE CIVILE MATERIELLE",
        "RESP CIVILE CORPORELLE": "RESPONSABILITE CIVILE CORPORELLE",
        "RESPONSABILITE CIVILE CORPORELLE": "RESPONSABILITE CIVILE CORPORELLE",
        "DEFENSE ET RECOURS": "DEFENSE ET RECOURS",
        "DEFENSE RECOURS": "DEFENSE ET RECOURS",
        "RECOURS ET DEFENSE": "DEFENSE ET RECOURS",
        "DOMMAGE COLLISION": "DOMMAGES COLLISION",
        "DOMMAGES COLLISION": "DOMMAGES COLLISION",
        "BRIS GLACE": "BRIS DE GLACE",
        "BRIS DE GLACE": "BRIS DE GLACE",
        "ASSISTANCE": "ASSISTANCE",
        "ASSISTANCE AUTO": "ASSISTANCE",
        "ASSISTANCE AUTOMOBILE": "ASSISTANCE",
        "INDIVIDUELLE ACCIDENT": "INDIVIDUELLE ACCIDENT",
        "INDIVIDUELLE ACCIDENTS": "INDIVIDUELLE ACCIDENT",
        "TOUS RISQUE": "TOUS RISQUES",
        "TOUS RISQUES": "TOUS RISQUES",
        "TIERCE": "TIERCE",
        "VOL": "VOL",
        "INCENDIE": "INCENDIE",
        "FRAIS MEDICAUX": "FRAIS MEDICAUX",
        "DECES": "DECES",
        "CATAS NATURELLE": "CATASTROPHES NATURELLES",
        "EMEUTE": "EMEUTE",
        "INDEM DIRECTE DES ASSURES": "INDEMNISATION DIRECTE DES ASSURES",
    }
    if no_accents in exact:
        return exact[no_accents]
    if "RESPONSABILITE" in no_accents and "CIVILE" in no_accents:
        return "RESPONSABILITE CIVILE"
    if "DEFENSE" in no_accents and "RECOURS" in no_accents:
        return "DEFENSE ET RECOURS"
    if "BRIS" in no_accents and "GLACE" in no_accents:
        return "BRIS DE GLACE"
    if "DOMMAGE" in no_accents and "COLLISION" in no_accents:
        return "DOMMAGES COLLISION"
    if "ASSISTANCE" in no_accents:
        return "ASSISTANCE"
    if "INDIVIDUEL" in no_accents and "ACCIDENT" in no_accents:
        return "INDIVIDUELLE ACCIDENT"
    if "TOUS" in no_accents and "RISQUE" in no_accents:
        return "TOUS RISQUES"
    return cleaned


def _to_bool(value: object) -> bool:
    if _is_missing(value):
        return False
    s = str(value).strip().upper()
    return s in {"TRUE", "T", "1", "O", "OUI", "YES", "Y"}


def _garantie_key(code_produit: str, code_garantie: str) -> str:
    return f"{code_produit}|{code_garantie}"


def _available_columns(engine) -> set[str]:
    with engine.connect() as conn:
        return set(
            row[0]
            for row in conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'staging'
                      AND table_name = 'stg_sinistres'
                    """
                )
            )
        )


def read_observed_guarantees(engine, logger) -> pd.DataFrame:
    available = _available_columns(engine)
    required = {"codprod", "grntsini"}
    missing = required.difference(available)
    if missing:
        raise RuntimeError(
            "staging.stg_sinistres must contain CODPROD and GRNTSINI "
            f"for dim_garantie. Missing: {sorted(missing)}"
        )

    optional = [
        col
        for col in ["guarantee_label", "guarantee_mapping_status", "is_auto_scope"]
        if col in available
    ]
    select_cols = ["codprod", "grntsini", *optional]
    with engine.connect() as conn:
        df = pd.read_sql(
            text(
                f"""
                SELECT {', '.join(select_cols)}
                FROM {SOURCE_TABLE}
                WHERE codprod IS NOT NULL
                  AND grntsini IS NOT NULL
                """
            ),
            conn,
        )
    logger.info(f"  source rows with CODPROD + GRNTSINI: {len(df)}")
    return df


def transform_dim_garantie(df_raw: pd.DataFrame, logger) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    df = df_raw.copy()
    n_raw = len(df)

    df["code_produit"] = df["codprod"].map(_clean_code)
    df["code_garantie"] = df["grntsini"].map(_clean_code)
    df = df[df["code_produit"].notna() & df["code_garantie"].notna()].copy()
    n_invalid_key = n_raw - len(df)

    if "guarantee_label" in df.columns:
        df["reference_label"] = df["guarantee_label"].map(_normalise_label)
    else:
        df["reference_label"] = None

    if "is_auto_scope" in df.columns:
        df["_is_auto_scope_source"] = df["is_auto_scope"].map(_to_bool)
    else:
        df["_is_auto_scope_source"] = False
    df["_is_auto_scope_product"] = df["code_produit"].str.startswith("5", na=False)
    df["_is_auto_scope"] = df["_is_auto_scope_source"] | df["_is_auto_scope_product"]

    grouped = (
        df.groupby(["code_produit", "code_garantie"], dropna=False)
        .agg(
            nb_sinistres=("code_garantie", "size"),
            is_auto_scope=("_is_auto_scope", "max"),
            labels=("reference_label", lambda s: sorted(set(v for v in s if isinstance(v, str) and v.strip()))),
        )
        .reset_index()
    )
    grouped["garantie_key"] = grouped.apply(
        lambda r: _garantie_key(r["code_produit"], r["code_garantie"]), axis=1
    )

    grouped["libelle_garantie"] = grouped["labels"].map(
        lambda labels: labels[0] if labels else UNKNOWN
    )
    grouped["garantie_quality_level"] = grouped["labels"].map(
        lambda labels: QUALITY_VALIDATED_REFERENCE
        if labels
        else QUALITY_OBSERVED_MISSING_REFERENCE
    )

    grouped = grouped.sort_values(["code_produit", "code_garantie"]).reset_index(drop=True)
    grouped.insert(0, "garantie_sk", range(1, len(grouped) + 1))
    grouped["source_system"] = SOURCE_SYSTEM
    grouped["created_at"] = TODAY

    unknown_row = pd.DataFrame(
        [
            {
                "garantie_sk": 0,
                "garantie_key": UNKNOWN_KEY,
                "code_produit": UNKNOWN,
                "code_garantie": UNKNOWN,
                "libelle_garantie": UNKNOWN,
                "garantie_quality_level": UNKNOWN,
                "source_system": SOURCE_SYSTEM,
                "created_at": TODAY,
            }
        ]
    )
    df_final = pd.concat([unknown_row, grouped[FINAL_COLS]], ignore_index=True)

    missing_reference = grouped[
        grouped["garantie_quality_level"].eq(QUALITY_OBSERVED_MISSING_REFERENCE)
    ].copy()
    missing_reference["reason"] = (
        "observed in staging.stg_sinistres but no trusted guarantee reference label"
    )
    report = missing_reference[
        [
            "code_produit",
            "code_garantie",
            "garantie_key",
            "nb_sinistres",
            "is_auto_scope",
            "reason",
        ]
    ].copy()

    metrics = {
        "n_raw": n_raw,
        "n_invalid_key": n_invalid_key,
        "n_distinct_observed": len(grouped),
        "n_loaded": len(df_final),
        "n_validated_reference": int(
            grouped["garantie_quality_level"].eq(QUALITY_VALIDATED_REFERENCE).sum()
        ),
        "n_missing_reference": int(
            grouped["garantie_quality_level"].eq(QUALITY_OBSERVED_MISSING_REFERENCE).sum()
        ),
        "n_auto_scope": int(grouped["is_auto_scope"].sum()),
        "missing_reference_report_rows": len(report),
    }

    logger.info(f"  invalid CODPROD/GRNTSINI rows ignored: {n_invalid_key}")
    logger.info(f"  distinct observed guarantee keys: {len(grouped)}")
    return df_final[FINAL_COLS].copy(), report, metrics


def write_reports(report: pd.DataFrame) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report.to_csv(MISSING_REFERENCE_REPORT, index=False, encoding="utf-8-sig")


def load_dim_garantie(run_id: str, engine, logger) -> dict:
    logger.info(f"[READ] {SOURCE_TABLE}")
    df_raw = read_observed_guarantees(engine, logger)
    df_final, missing_reference_report, metrics = transform_dim_garantie(df_raw, logger)
    write_reports(missing_reference_report)

    _, elapsed = dwh_utils.write_to_dwh(df_final, engine, TABLE_NAME, logger)
    metrics["elapsed"] = elapsed
    metrics["report_path"] = str(MISSING_REFERENCE_REPORT)
    return metrics


def print_validation_sql() -> None:
    print(
        """
Validation SQL:

SELECT COUNT(*) AS total
FROM dwh.dim_garantie;

SELECT garantie_key, COUNT(*) AS nb
FROM dwh.dim_garantie
GROUP BY garantie_key
HAVING COUNT(*) > 1;

SELECT garantie_quality_level, COUNT(*) AS nb
FROM dwh.dim_garantie
GROUP BY garantie_quality_level
ORDER BY nb DESC;

SELECT COUNT(*) AS missing_reference_observed
FROM dwh.dim_garantie
WHERE garantie_quality_level = 'OBSERVED_IN_SINISTRES_MISSING_REFERENCE';
"""
    )


if __name__ == "__main__":
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logger = dwh_utils.setup_logging(run_id, log_name="load_dim_garantie")
    engine = dwh_utils.build_engine(logger)

    dwh_utils.create_dwh_schema(engine, logger)
    m = load_dim_garantie(run_id, engine, logger)

    logger.info("=" * 72)
    logger.info("dwh.dim_garantie loaded successfully")
    logger.info(f"  source rows with CODPROD + GRNTSINI       : {m['n_raw']}")
    logger.info(f"  invalid CODPROD/GRNTSINI rows ignored    : {m['n_invalid_key']}")
    logger.info(f"  distinct observed guarantee keys          : {m['n_distinct_observed']}")
    logger.info(f"  rows loaded including UNKNOWN anchor      : {m['n_loaded']}")
    logger.info(f"  VALIDATED_REFERENCE rows                  : {m['n_validated_reference']}")
    logger.info(f"  observed missing-reference rows           : {m['n_missing_reference']}")
    logger.info(f"  observed auto-scope rows                  : {m['n_auto_scope']}")
    logger.info(f"  missing reference report rows             : {m['missing_reference_report_rows']}")
    logger.info(f"  missing reference report                  : {m['report_path']}")
    logger.info(f"  elapsed seconds                           : {m['elapsed']:.1f}")
    logger.info("=" * 72)
    print_validation_sql()

