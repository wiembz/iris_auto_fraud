"""
etl/dwh/load_dim_garantie.py
============================
Build dwh.dim_garantie for automobile claim guarantees only.

Grain:
  one row per CODPROD + GRNTSINI observed in staging.stg_sinistres for
  automobile products only (CODPROD starts with '5').

Business key:
  garantie_key = CODPROD || '|' || GRNTSINI

Important modelling rule:
  IRIS Auto Fraud is scoped to automobile claims. Non-automobile products are
  excluded from dim_garantie and documented in a quality report.

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
MISSING_REFERENCE_REPORT = REPORT_DIR / "dim_garantie_auto_missing_label.csv"
EXCLUDED_NON_AUTO_REPORT = REPORT_DIR / "dim_garantie_excluded_non_auto.csv"

UNKNOWN = "UNKNOWN"
UNKNOWN_KEY = "UNKNOWN|UNKNOWN"
QUALITY_VALIDATED_REFERENCE = "VALIDATED_REFERENCE"
QUALITY_VALIDATED_AUTO_MAPPING = "VALIDATED_AUTO_MAPPING"
QUALITY_OBSERVED_MISSING_REFERENCE = "OBSERVED_IN_AUTO_SINISTRES_MISSING_LABEL"

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

# Mapping metier des garanties automobiles observees dans les produits 5xx.
# Il complete les libelles lorsque le referentiel source ne couvre pas un couple
# CODPROD|GRNTSINI, sans ouvrir le perimetre aux produits non-auto.
AUTO_GARANTIE_LABEL_MAP: dict[str, str] = {
    "ASR": "AVANCE SUR RECOURS",
    "BG": "BRIS DE GLACE",
    "CAS": "CONTRE ASSURANCE SPECIALE",
    "CAT": "CATASTROPHES NATURELLES",
    "CONS": "CONSIGNATION",
    "DC": "DECES",
    "DEPA": "DEPANNAGE ACCIDENT",
    "DEPC": "DEPANNAGE CREVAISON",
    "DOC": "DOMMAGES COLLISION",
    "EME": "EMEUTE",
    "EXT": "EXTENSION DE GARANTIE",
    "FM": "FRAIS MEDICAUX",
    "IC": "INDIVIDUELLE CONDUCTEUR",
    "IDA": "INDEMNISATION DIRECTE DES ASSURES",
    "INC": "INCENDIE",
    "IND": "INDIVIDUELLE ACCIDENT",
    "IPT": "INVALIDITE PERMANENTE OU TEMPORAIRE",
    "RCA": "RESPONSABILITE CIVILE ARRERAGES",
    "RCC": "RESPONSABILITE CIVILE CORPORELLE",
    "RCDE": "RESPONSABILITE CIVILE DEFENSE ET RECOURS",
    "RCM": "RESPONSABILITE CIVILE MATERIELLE",
    "RCR": "RESPONSABILITE CIVILE RENTE MATHEMATIQUE",
    "REM": "REMORQUAGE",
    "TR": "TOUS RISQUES",
    "VOL": "VOL",
}

REFERENCE_LABEL_ALIASES = {
    "INDIVIDUAL CONDUCTEUR": "INDIVIDUELLE CONDUCTEUR",
    "RESPONSAB CIVILE ARRERAGES": "RESPONSABILITE CIVILE ARRERAGES",
    "RESP CIVILE RENTE MATHEMAT": "RESPONSABILITE CIVILE RENTE MATHEMATIQUE",
    "INVALIDITE PERMANANTE OU TEMPO": "INVALIDITE PERMANENTE OU TEMPORAIRE",
    "CONTRE ASSURANCE SPECIALE": "CONTRE ASSURANCE SPECIALE",
}


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
    if no_accents in REFERENCE_LABEL_ALIASES:
        return REFERENCE_LABEL_ALIASES[no_accents]

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
        "INDIVIDUEL ACCIDENT": "INDIVIDUELLE ACCIDENT",
        "TOUS RISQUE": "TOUS RISQUES",
        "TOUS RISQUES": "TOUS RISQUES",
        "TIERCE": "TIERCE",
        "VOL": "VOL",
        "INCENDIE": "INCENDIE",
        "FRAIS MEDICAUX": "FRAIS MEDICAUX",
        "DECES": "DECES",
        "CATAS NATURELLE": "CATASTROPHES NATURELLES",
        "CATASTROPHES NATURELLES": "CATASTROPHES NATURELLES",
        "EMEUTE": "EMEUTE",
        "INDEM DIRECTE DES ASSURES": "INDEMNISATION DIRECTE DES ASSURES",
        "INDEMNISATION DIRECTE DES ASSURES": "INDEMNISATION DIRECTE DES ASSURES",
        "AVANCE SUR RECOURS": "AVANCE SUR RECOURS",
        "CONSIGNATION": "CONSIGNATION",
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
    return no_accents


def _to_bool(value: object) -> bool:
    if _is_missing(value):
        return False
    s = str(value).strip().upper()
    return s in {"TRUE", "T", "1", "O", "OUI", "YES", "Y"}


def _garantie_key(code_produit: str, code_garantie: str) -> str:
    return f"{code_produit}|{code_garantie}"


def _best_label(labels: list[str], code_garantie: str) -> tuple[str, str]:
    mapped = AUTO_GARANTIE_LABEL_MAP.get(code_garantie)
    if mapped:
        return mapped, QUALITY_VALIDATED_REFERENCE if mapped in labels else QUALITY_VALIDATED_AUTO_MAPPING
    if labels:
        return labels[0], QUALITY_VALIDATED_REFERENCE
    return UNKNOWN, QUALITY_OBSERVED_MISSING_REFERENCE


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
        for col in ["codfam", "guarantee_label", "guarantee_mapping_status", "is_auto_scope"]
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


def transform_dim_garantie(df_raw: pd.DataFrame, logger) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    df = df_raw.copy()
    n_raw = len(df)

    df["code_produit"] = df["codprod"].map(_clean_code)
    df["code_garantie"] = df["grntsini"].map(_clean_code)
    if "codfam" in df.columns:
        df["code_famille"] = df["codfam"].map(_clean_code)
    else:
        df["code_famille"] = df["code_produit"].str[:1]

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

    df["_is_auto_product"] = df["code_produit"].str.startswith("5", na=False)
    df["_is_auto_family"] = df["code_famille"].eq("5")
    df["_is_auto_scope"] = df["_is_auto_product"] | df["_is_auto_family"]

    excluded = df[~df["_is_auto_scope"]].copy()
    df_auto = df[df["_is_auto_scope"]].copy()

    excluded_report = (
        excluded.groupby(["code_produit", "code_garantie"], dropna=False)
        .size()
        .rename("nb_sinistres")
        .reset_index()
    )
    if not excluded_report.empty:
        excluded_report["reason"] = "excluded from dim_garantie because CODPROD/CODFAM is outside automobile 5xx scope"

    grouped = (
        df_auto.groupby(["code_produit", "code_garantie"], dropna=False)
        .agg(
            nb_sinistres=("code_garantie", "size"),
            labels=("reference_label", lambda s: sorted(set(v for v in s if isinstance(v, str) and v.strip()))),
        )
        .reset_index()
    )
    grouped["garantie_key"] = grouped.apply(
        lambda r: _garantie_key(r["code_produit"], r["code_garantie"]), axis=1
    )

    resolved = grouped.apply(lambda r: _best_label(r["labels"], r["code_garantie"]), axis=1)
    grouped["libelle_garantie"] = resolved.map(lambda x: x[0])
    grouped["garantie_quality_level"] = resolved.map(lambda x: x[1])

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
    if not missing_reference.empty:
        missing_reference["reason"] = "auto guarantee observed in 5xx products but not covered by source/reference or auto mapping"
    report = missing_reference[
        [
            "code_produit",
            "code_garantie",
            "garantie_key",
            "nb_sinistres",
            "reason",
        ]
    ].copy() if not missing_reference.empty else pd.DataFrame(
        columns=["code_produit", "code_garantie", "garantie_key", "nb_sinistres", "reason"]
    )

    metrics = {
        "n_raw": n_raw,
        "n_invalid_key": n_invalid_key,
        "n_source_auto_rows": len(df_auto),
        "n_source_non_auto_rows_excluded": len(excluded),
        "n_distinct_auto_observed": len(grouped),
        "n_loaded": len(df_final),
        "n_validated_reference": int(grouped["garantie_quality_level"].eq(QUALITY_VALIDATED_REFERENCE).sum()),
        "n_validated_auto_mapping": int(grouped["garantie_quality_level"].eq(QUALITY_VALIDATED_AUTO_MAPPING).sum()),
        "n_missing_reference": int(grouped["garantie_quality_level"].eq(QUALITY_OBSERVED_MISSING_REFERENCE).sum()),
        "missing_reference_report_rows": len(report),
        "excluded_non_auto_combinations": len(excluded_report),
    }

    logger.info(f"  invalid CODPROD/GRNTSINI rows ignored: {n_invalid_key}")
    logger.info(f"  source auto rows retained: {len(df_auto)}")
    logger.info(f"  source non-auto rows excluded: {len(excluded)}")
    logger.info(f"  distinct auto guarantee keys: {len(grouped)}")
    return df_final[FINAL_COLS].copy(), report, excluded_report, metrics


def write_reports(missing_report: pd.DataFrame, excluded_report: pd.DataFrame) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    missing_report.to_csv(MISSING_REFERENCE_REPORT, index=False, encoding="utf-8-sig")
    excluded_report.to_csv(EXCLUDED_NON_AUTO_REPORT, index=False, encoding="utf-8-sig")


def load_dim_garantie(run_id: str, engine, logger) -> dict:
    logger.info(f"[READ] {SOURCE_TABLE}")
    df_raw = read_observed_guarantees(engine, logger)
    df_final, missing_reference_report, excluded_report, metrics = transform_dim_garantie(df_raw, logger)
    write_reports(missing_reference_report, excluded_report)

    _, elapsed = dwh_utils.write_to_dwh(df_final, engine, TABLE_NAME, logger)
    metrics["elapsed"] = elapsed
    metrics["missing_report_path"] = str(MISSING_REFERENCE_REPORT)
    metrics["excluded_report_path"] = str(EXCLUDED_NON_AUTO_REPORT)
    return metrics


def print_validation_sql() -> None:
    print(
        """
Validation SQL:

SELECT COUNT(*) AS total
FROM dwh.dim_garantie;

SELECT COUNT(*) AS non_auto_rows
FROM dwh.dim_garantie
WHERE code_produit <> 'UNKNOWN'
  AND code_produit NOT LIKE '5%';

SELECT garantie_key, COUNT(*) AS nb
FROM dwh.dim_garantie
GROUP BY garantie_key
HAVING COUNT(*) > 1;

SELECT garantie_quality_level, COUNT(*) AS nb
FROM dwh.dim_garantie
GROUP BY garantie_quality_level
ORDER BY nb DESC;

SELECT *
FROM dwh.dim_garantie
WHERE libelle_garantie = 'UNKNOWN'
  AND garantie_sk <> 0;
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
    logger.info(f"  source auto rows retained                : {m['n_source_auto_rows']}")
    logger.info(f"  source non-auto rows excluded            : {m['n_source_non_auto_rows_excluded']}")
    logger.info(f"  distinct auto guarantee keys             : {m['n_distinct_auto_observed']}")
    logger.info(f"  rows loaded including UNKNOWN anchor     : {m['n_loaded']}")
    logger.info(f"  VALIDATED_REFERENCE rows                 : {m['n_validated_reference']}")
    logger.info(f"  VALIDATED_AUTO_MAPPING rows              : {m['n_validated_auto_mapping']}")
    logger.info(f"  missing auto labels remaining            : {m['n_missing_reference']}")
    logger.info(f"  missing label report rows                : {m['missing_reference_report_rows']}")
    logger.info(f"  excluded non-auto combinations           : {m['excluded_non_auto_combinations']}")
    logger.info(f"  missing label report                     : {m['missing_report_path']}")
    logger.info(f"  excluded non-auto report                 : {m['excluded_report_path']}")
    logger.info(f"  elapsed seconds                          : {m['elapsed']:.1f}")
    logger.info("=" * 72)
    print_validation_sql()

