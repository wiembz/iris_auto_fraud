"""
etl/dwh/load_fact_contrat.py
=============================
Build dwh.fact_contrat from staging.stg_production.

Grain: one row per NUMCNT + NUMAVT + NUMMAJ.
Business key: contrat_mouvement_key = contrat_key || '|' || num_avt || '|' || num_maj.

This is a contract movement / contract version fact table. It does not contain
fraud scoring logic.
"""
from __future__ import annotations

import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwh_utils

BASE_DIR = Path(__file__).resolve().parent.parent.parent
TABLE_NAME = "fact_contrat"
SOURCE_TABLE = "staging.stg_production"
SOURCE_SYSTEM = "BNA_ASSURANCES"
TODAY = datetime.now(timezone.utc).replace(tzinfo=None)

REPORT_DIR = BASE_DIR / "data" / "quality_reports" / "fact_contrat"
UNMATCHED_DIMS_PATH = REPORT_DIR / "fact_contrat_unmatched_dimensions.csv"
DUPLICATE_GRAIN_PATH = REPORT_DIR / "fact_contrat_duplicate_grain.csv"
DATE_ANOMALIES_PATH = REPORT_DIR / "fact_contrat_date_anomalies.csv"
AMOUNT_ANOMALIES_PATH = REPORT_DIR / "fact_contrat_amount_anomalies.csv"
INVALID_KEYS_PATH = REPORT_DIR / "fact_contrat_invalid_contract_keys.csv"
LOAD_SUMMARY_PATH = REPORT_DIR / "fact_contrat_load_summary.csv"

UNKNOWN = "UNKNOWN"
INVALID_TEXT = frozenset({"", "NULL", "NAN", "NONE", "UNKNOWN", "INCONNU", "INCONNUE", "N/A", "NA", "#N/A"})
TRUE_VALUES = frozenset({"O", "OUI", "Y", "YES", "1", "TRUE", "T"})
FALSE_VALUES = frozenset({"N", "NON", "NO", "0", "FALSE", "F"})
RESILIE_VALUES = frozenset({"R", "RESILIE", "RESILIEE", "ANNULE", "ANNULEE", "CANCELLED", "TERMINE", "TERMINEE"})
ACTIVE_VALUES = frozenset({"A", "ACTIF", "ACTIVE", "V", "VALIDE", "VALIDEE", "EN COURS"})

SOURCE_CANDIDATES = {
    "numcnt": ["numcnt", "numcnt_norm", "NUMCNT", "numero_contrat"],
    "numavt": ["numavt", "numavt_norm", "NUMAVT", "numero_avenant"],
    "nummaj": ["nummaj", "nummaj_norm", "NUMMAJ", "numero_maj", "numero_mise_a_jour"],
    "codfam": ["codfam", "codfam_norm", "CODFAM"],
    "codprod": ["codprod", "codprod_norm", "CODPROD", "code_produit"],
    "libprdt": ["libprdt", "libprod", "product_label", "libelle_produit", "LIBPRDT"],
    "natclt": ["natclt", "natclt_norm", "NATCLT"],
    "idclt": ["idclt", "idclt_norm", "IDCLT", "client_key"],
    "natint": ["natint", "natint_norm", "NATINT"],
    "idint": ["idint", "idint_norm", "IDINT"],
    "iddelega": ["iddelega", "IDDELEGA"],
    "duree": ["duree", "DUREE"],
    "debcnt": ["debcnt", "DEBCNT", "date_debut_contrat"],
    "fincnt": ["fincnt", "FINCNT", "date_fin_contrat"],
    "debeffet": ["debeffet", "DEBEFFET", "date_debut_effet"],
    "fineffet": ["fineffet", "FINEFFET", "date_fin_effet"],
    "coassur": ["coassur", "COASSUR"],
    "situat": ["situat", "SITUAT", "statut", "situation_contrat"],
    "dateprec": ["dateprec", "DATEPREC", "date_derniere_operation"],
    "typeresil": ["typeresil", "TYPERESIL", "type_resiliation"],
    "lib_resil": ["lib_resil", "LIB_RESIL", "libelle_resiliation"],
    "total_prime": ["total_prime", "TOTAL_PRIME"],
}

FINAL_COLS = [
    "fact_contrat_sk",
    "contrat_mouvement_key",
    "contrat_key",
    "numero_contrat",
    "numero_avenant",
    "numero_mise_a_jour",
    "contrat_sk",
    "client_sk",
    "produit_sk",
    "intermediaire_sk",
    "date_debut_contrat_sk",
    "date_fin_contrat_sk",
    "date_debut_effet_sk",
    "date_fin_effet_sk",
    "date_derniere_operation_sk",
    "date_resiliation_sk",
    "duree_contrat",
    "total_prime",
    "nombre_contrat_mouvement",
    "est_contrat_actif",
    "est_contrat_resilie",
    "est_coassurance",
    "est_avenant",
    "est_mise_a_jour",
    "est_auto_scope",
    "situation_contrat",
    "type_resiliation",
    "libelle_resiliation",
    "source_system",
    "created_at",
]


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value)


def _clean_code(value: object, *, allow_zero: bool = False) -> str | None:
    if _is_missing(value):
        return None
    s = str(value).strip().upper()
    if s in INVALID_TEXT:
        return None
    try:
        number = float(s.replace(",", "."))
        if number.is_integer():
            s = str(int(number))
    except ValueError:
        pass
    if s.endswith(".0"):
        s = s[:-2]
    s = re.sub(r"\s+", "", s)
    if not s or s in INVALID_TEXT:
        return None
    if not allow_zero and s in {"0", "0.0"}:
        return None
    return s


def _clean_text(value: object) -> str | None:
    if _is_missing(value):
        return None
    s = re.sub(r"\s+", " ", str(value).strip().upper())
    return None if s in INVALID_TEXT else s


def _join_key(parts: list[object]) -> str | None:
    values = []
    for value in parts:
        if _is_missing(value):
            values.append(UNKNOWN)
        else:
            s = str(value).strip().upper()
            values.append(s if s and s not in INVALID_TEXT else UNKNOWN)
    return None if all(v == UNKNOWN for v in values) else "|".join(values)


def _date_missing(value: object) -> bool:
    """Return True for source placeholders that mean no date."""
    if _is_missing(value):
        return True
    s = str(value).strip().upper()
    return s in INVALID_TEXT or s in {"0", "0.0", "00000000", "0000-00-00"}


def _valid_calendar_yyyymmdd(value: int) -> pd.Timestamp | pd.NaT:
    """Validate an integer YYYYMMDD as a real calendar date."""
    s = str(value)
    if not re.fullmatch(r"\d{8}", s):
        return pd.NaT
    try:
        return pd.Timestamp(datetime.strptime(s, "%Y%m%d"))
    except ValueError:
        return pd.NaT


def _extract_yyyymmdd_candidate(value: object) -> int | None:
    """
    Detect values that are already date keys in YYYYMMDD format.

    Production date columns such as DEBCNT, FINCNT, DEBEFFET and FINEFFET
    often arrive as 20160106, 20240206, etc. Those values must NOT be
    interpreted as Excel serial dates or generic timestamps.
    """
    if _date_missing(value):
        return None

    if isinstance(value, (int,)) and not isinstance(value, bool):
        s = str(value)
    elif isinstance(value, float) and math.isfinite(value) and value.is_integer():
        s = str(int(value))
    else:
        s = str(value).strip()
        # Handle values read as 20160106.0 without losing historical values
        # that contain slashes or true decimal-like contract identifiers.
        if re.fullmatch(r"\d{8}\.0+", s):
            s = s.split(".")[0]

    if re.fullmatch(r"\d{8}", s):
        return int(s)
    return None


def _parse_generic_date_to_key(value: object) -> tuple[int, pd.Timestamp | pd.NaT]:
    """Parse timestamp-like values and convert to integer YYYYMMDD."""
    if _date_missing(value):
        return 0, pd.NaT

    raw = str(value).strip()
    # Prefer year-first parsing for ISO strings, otherwise use day-first for
    # common French/Tunisian Excel exports such as 06/02/2024.
    if re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}", raw):
        ts = pd.to_datetime(raw, errors="coerce", dayfirst=False)
    else:
        ts = pd.to_datetime(raw, errors="coerce", dayfirst=True)

    if pd.isna(ts):
        return 0, pd.NaT
    ts = pd.Timestamp(ts).normalize()
    return int(ts.strftime("%Y%m%d")), ts


def _date_sk_result(value: object, valid_date_keys: set[int]) -> dict[str, object]:
    """
    Convert a raw source date to a DWH date_sk with a detailed status.

    Rules:
    - 0/NULL/empty placeholders return date_sk=0 with SOURCE_DATE_MISSING.
    - 8-digit YYYYMMDD values are treated as already-encoded date keys.
    - timestamp/date strings are parsed and converted to YYYYMMDD.
    - date_sk must exist in dim_date; otherwise it is set to 0 and reported.
    """
    if _date_missing(value):
        return {
            "date_sk": 0,
            "parsed_date": pd.NaT,
            "date_status": "SOURCE_DATE_MISSING",
            "date_reason": "source date is null, empty, zero or placeholder",
        }

    key_candidate = _extract_yyyymmdd_candidate(value)
    if key_candidate is not None:
        ts = _valid_calendar_yyyymmdd(key_candidate)
        if pd.isna(ts):
            return {
                "date_sk": 0,
                "parsed_date": pd.NaT,
                "date_status": "SOURCE_DATE_INVALID",
                "date_reason": f"invalid YYYYMMDD calendar date: {value}",
            }
        if key_candidate not in valid_date_keys:
            return {
                "date_sk": 0,
                "parsed_date": ts,
                "date_status": "DATE_OUTSIDE_DIM_DATE",
                "date_reason": f"valid date {key_candidate} not found in dwh.dim_date",
            }
        return {
            "date_sk": key_candidate,
            "parsed_date": ts,
            "date_status": "DATE_JOIN_OK",
            "date_reason": "source value is valid YYYYMMDD date key",
        }

    parsed_key, ts = _parse_generic_date_to_key(value)
    if parsed_key == 0 or pd.isna(ts):
        return {
            "date_sk": 0,
            "parsed_date": pd.NaT,
            "date_status": "SOURCE_DATE_INVALID",
            "date_reason": f"unable to parse source date: {value}",
        }
    if parsed_key not in valid_date_keys:
        return {
            "date_sk": 0,
            "parsed_date": ts,
            "date_status": "DATE_OUTSIDE_DIM_DATE",
            "date_reason": f"valid date {parsed_key} not found in dwh.dim_date",
        }
    return {
        "date_sk": parsed_key,
        "parsed_date": ts,
        "date_status": "DATE_JOIN_OK",
        "date_reason": "source timestamp parsed and matched dim_date",
    }


def _apply_date_field(df: pd.DataFrame, source_col: str, target_prefix: str, valid_date_keys: set[int]) -> pd.DataFrame:
    """Create parsed timestamp, date_sk, status and reason columns for one source date."""
    parsed = df[source_col].map(lambda value: _date_sk_result(value, valid_date_keys))
    df[target_prefix] = pd.to_datetime(parsed.map(lambda r: r["parsed_date"]), errors="coerce")
    df[f"{target_prefix}_sk"] = parsed.map(lambda r: r["date_sk"]).astype("int64")
    df[f"{target_prefix}_status"] = parsed.map(lambda r: r["date_status"])
    df[f"{target_prefix}_reason"] = parsed.map(lambda r: r["date_reason"])
    return df


def _to_numeric_series(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    raw = series.astype(str).str.strip().str.replace(" ", "", regex=False).str.replace(",", ".", regex=False)
    raw = raw.mask(raw.str.upper().isin(INVALID_TEXT), pd.NA)
    numeric = pd.to_numeric(raw, errors="coerce").astype("Float64")
    invalid = series.notna() & numeric.isna()
    return numeric, invalid


def _bool_from_source(value: object) -> bool | pd.NA:
    if _is_missing(value):
        return pd.NA
    s = str(value).strip().upper()
    if s in TRUE_VALUES:
        return True
    if s in FALSE_VALUES:
        return False
    return pd.NA


def _is_non_zero_code(value: object) -> bool | pd.NA:
    code = _clean_code(value, allow_zero=True)
    if code is None:
        return pd.NA
    return code not in {"0", "00", "000"}


def _resilie_flag(situat: object, typeresil: object, lib_resil: object) -> bool | pd.NA:
    if _clean_code(typeresil) is not None or _clean_text(lib_resil) is not None:
        return True
    situation = _clean_text(situat)
    if situation in RESILIE_VALUES:
        return True
    if situation in ACTIVE_VALUES or situation in {"E", "EXPIRE", "EXPIREE"}:
        return False
    return pd.NA


def _actif_flag(situat: object, est_resilie: object) -> bool | pd.NA:
    if str(est_resilie).upper() == "TRUE":
        return False
    situation = _clean_text(situat)
    if situation in ACTIVE_VALUES:
        return True
    if situation in RESILIE_VALUES:
        return False
    return pd.NA


def _available_columns(engine) -> set[str]:
    with engine.connect() as conn:
        return set(row[0] for row in conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'staging' AND table_name = 'stg_production'
        """)))


def _pick_columns(available: set[str], logger) -> dict[str, str | None]:
    lower_to_actual = {col.lower(): col for col in available}
    mapping: dict[str, str | None] = {}
    for canonical, candidates in SOURCE_CANDIDATES.items():
        actual = None
        for candidate in candidates:
            actual = lower_to_actual.get(candidate.lower())
            if actual:
                break
        mapping[canonical] = actual
        if actual:
            logger.info(f"  source mapping {canonical:<13} <- {actual}")
        else:
            logger.warning(f"  optional source column missing for {canonical}; target values will be NULL")
    return mapping


def _read_staging(engine, logger) -> pd.DataFrame:
    available = _available_columns(engine)
    mapping = _pick_columns(available, logger)
    selected = [(canonical, actual) for canonical, actual in mapping.items() if actual]
    if not selected:
        raise RuntimeError("No expected columns found in staging.stg_production.")
    select_sql = ", ".join(f'"{actual}" AS "{canonical}"' for canonical, actual in selected)
    with engine.connect() as conn:
        df = pd.read_sql(text(f"SELECT {select_sql} FROM {SOURCE_TABLE}"), conn)
    for canonical in SOURCE_CANDIDATES:
        if canonical not in df.columns:
            df[canonical] = pd.NA
    logger.info(f"  source rows read from {SOURCE_TABLE}: {len(df)}")
    return df


def _read_table(engine, table_name: str, columns: list[str]) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text(f"SELECT {', '.join(columns)} FROM dwh.{table_name}"), conn)


def _dimension_maps(engine, logger) -> dict[str, dict | set[int]]:
    dims: dict[str, dict | set[int]] = {}

    dim = _read_table(engine, "dim_contrat", ["contrat_sk", "contrat_key", "numero_contrat"])
    dim["_key"] = dim["contrat_key"].map(dwh_utils.normalize_numcnt)
    fallback = dim["numero_contrat"].map(dwh_utils.normalize_numcnt)
    dim["_key"] = dim["_key"].where(dim["_key"].notna(), fallback)
    dims["contrat"] = dim.dropna(subset=["_key"]).drop_duplicates("_key").set_index("_key")["contrat_sk"].to_dict()

    dim = _read_table(engine, "dim_client", ["client_sk", "idclt"])
    dim["_key"] = dim["idclt"].map(_clean_code)
    dims["client"] = dim.dropna(subset=["_key"]).drop_duplicates("_key").set_index("_key")["client_sk"].to_dict()

    dim = _read_table(engine, "dim_produit", ["produit_sk", "code_produit"])
    dim["_key"] = dim["code_produit"].map(_clean_code)
    dims["produit"] = dim.dropna(subset=["_key"]).drop_duplicates("_key").set_index("_key")["produit_sk"].to_dict()

    dim = _read_table(engine, "dim_intermediaire", ["intermediaire_sk", "code_intermediaire"])
    dim["_key"] = dim["code_intermediaire"].map(lambda v: _join_key(str(v).split("|")) if not _is_missing(v) else None)
    dims["intermediaire"] = dim.dropna(subset=["_key"]).drop_duplicates("_key").set_index("_key")["intermediaire_sk"].to_dict()

    dim = _read_table(engine, "dim_date", ["date_sk"])
    dims["date_keys"] = set(pd.to_numeric(dim["date_sk"], errors="coerce").dropna().astype(int))

    logger.info(
        "  dimension maps loaded: "
        f"contrat={len(dims['contrat'])}, client={len(dims['client'])}, "
        f"produit={len(dims['produit'])}, intermediaire={len(dims['intermediaire'])}, "
        f"date_keys={len(dims['date_keys'])}"
    )
    return dims


def _write_duplicate_report(df: pd.DataFrame) -> int:
    cols = ["contrat_mouvement_key", "contrat_key", "numero_contrat", "numero_avenant", "numero_mise_a_jour"]
    duplicated = df[df["contrat_mouvement_key"].duplicated(keep=False)].copy()
    if duplicated.empty:
        pd.DataFrame(columns=cols + ["duplicate_count"]).to_csv(DUPLICATE_GRAIN_PATH, index=False, encoding="utf-8-sig")
        return 0
    counts = duplicated.groupby("contrat_mouvement_key").size().rename("duplicate_count").reset_index()
    report = duplicated[cols].merge(counts, on="contrat_mouvement_key", how="left")
    report.to_csv(DUPLICATE_GRAIN_PATH, index=False, encoding="utf-8-sig")
    return len(report)


def _deduplicate_grain(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if not df["contrat_mouvement_key"].duplicated().any():
        return df, 0
    ranked = df.copy()
    ranked["_has_prime"] = ranked["total_prime"].notna().astype(int)
    ranked["_date_completeness"] = ranked[["date_debut_contrat", "date_fin_contrat", "date_debut_effet", "date_fin_effet", "date_derniere_operation"]].notna().sum(axis=1)
    ranked["_dateprec_sort"] = ranked["date_derniere_operation"].fillna(pd.Timestamp.min)
    ranked["_fineffet_sort"] = ranked["date_fin_effet"].fillna(pd.Timestamp.min)
    ranked = ranked.sort_values(
        ["contrat_mouvement_key", "_has_prime", "_date_completeness", "_dateprec_sort", "_fineffet_sort", "_source_order"],
        ascending=[True, False, False, False, False, True],
    )
    deduped = ranked.drop_duplicates("contrat_mouvement_key", keep="first")
    deduped = deduped.drop(columns=["_has_prime", "_date_completeness", "_dateprec_sort", "_fineffet_sort"])
    return deduped, len(df) - len(deduped)


def _write_invalid_contract_keys_report(df: pd.DataFrame) -> dict[str, int]:
    report = df[["numcnt", "numavt", "nummaj", "contrat_key", "numero_avenant", "numero_mise_a_jour", "contrat_mouvement_key"]].copy()
    report["missing_numcnt"] = report["contrat_key"].isna()
    report["missing_numavt"] = report["numero_avenant"].isna()
    report["missing_nummaj"] = report["numero_mise_a_jour"].isna()
    report["malformed_contrat_key"] = report["contrat_key"].map(lambda v: False if pd.isna(v) else re.fullmatch(r"[A-Z0-9][A-Z0-9./-]*", str(v)) is None)
    flags = ["missing_numcnt", "missing_numavt", "missing_nummaj", "malformed_contrat_key"]
    report = report.loc[report[flags].any(axis=1)]
    report.to_csv(INVALID_KEYS_PATH, index=False, encoding="utf-8-sig")
    return {"invalid_contract_key_rows": len(report), **{flag: int(report[flag].sum()) for flag in flags}}


def _write_unmatched_dimensions_report(df: pd.DataFrame) -> dict[str, int]:
    cols = [
        "contrat_mouvement_key", "contrat_key", "numero_contrat", "numero_avenant", "numero_mise_a_jour",
        "contrat_sk", "client_sk", "produit_sk", "intermediaire_sk",
    ]
    report = df[cols].copy()
    for col in ["contrat_sk", "client_sk", "produit_sk", "intermediaire_sk"]:
        report[f"missing_{col}"] = report[col].eq(0)
    out_cols = ["contrat_mouvement_key", "contrat_key", "numero_contrat", "numero_avenant", "numero_mise_a_jour", "missing_contrat_sk", "missing_client_sk", "missing_produit_sk", "missing_intermediaire_sk"]
    flags = [c for c in out_cols if c.startswith("missing_")]
    filtered = report.loc[report[flags].any(axis=1), out_cols]
    filtered.to_csv(UNMATCHED_DIMS_PATH, index=False, encoding="utf-8-sig")
    return {flag: int(report[flag].sum()) for flag in flags}


def _write_date_anomalies_report(df: pd.DataFrame) -> dict[str, int]:
    """Write date parsing/join issues and chronological anomalies."""
    rows: list[dict[str, object]] = []
    date_fields = [
        ("debcnt", "date_debut_contrat", "date_debut_contrat_sk"),
        ("fincnt", "date_fin_contrat", "date_fin_contrat_sk"),
        ("debeffet", "date_debut_effet", "date_debut_effet_sk"),
        ("fineffet", "date_fin_effet", "date_fin_effet_sk"),
        ("dateprec", "date_derniere_operation", "date_derniere_operation_sk"),
    ]

    metrics: dict[str, int] = {
        "missing_date_debut_contrat": int(df["date_debut_contrat_sk"].eq(0).sum()),
        "missing_date_fin_contrat": int(df["date_fin_contrat_sk"].eq(0).sum()),
        "missing_date_debut_effet": int(df["date_debut_effet_sk"].eq(0).sum()),
        "missing_date_fin_effet": int(df["date_fin_effet_sk"].eq(0).sum()),
        "missing_date_derniere_operation": int(df["date_derniere_operation_sk"].eq(0).sum()),
    }

    for source_col, target_prefix, target_sk_col in date_fields:
        status_col = f"{target_prefix}_status"
        reason_col = f"{target_prefix}_reason"
        issue_mask = df[status_col].ne("DATE_JOIN_OK")
        if issue_mask.any():
            issue_df = df.loc[issue_mask, [
                "contrat_mouvement_key",
                "contrat_key",
                source_col,
                target_prefix,
                target_sk_col,
                status_col,
                reason_col,
            ]].copy()
            issue_df = issue_df.rename(columns={
                source_col: "source_date_value",
                target_prefix: "parsed_date",
                target_sk_col: "parsed_date_sk",
                status_col: "date_status",
                reason_col: "reason",
            })
            issue_df.insert(2, "date_field", target_prefix)
            rows.extend(issue_df.to_dict("records"))

        for status, count in df[status_col].value_counts(dropna=False).items():
            safe_status = str(status).lower().replace(" ", "_").replace("<na>", "missing_status")
            metrics[f"{target_prefix}_{safe_status}"] = int(count)

    chrono = pd.DataFrame({
        "contrat_mouvement_key": df["contrat_mouvement_key"],
        "contrat_key": df["contrat_key"],
        "date_debut_contrat": df["date_debut_contrat"],
        "date_fin_contrat": df["date_fin_contrat"],
        "date_debut_effet": df["date_debut_effet"],
        "date_fin_effet": df["date_fin_effet"],
        "date_derniere_operation": df["date_derniere_operation"],
        "duree_contrat": df["duree_contrat"],
    })
    chrono["negative_duree"] = chrono["duree_contrat"] < 0
    chrono["fin_before_debut_contrat"] = (
        chrono["date_fin_contrat"].notna()
        & chrono["date_debut_contrat"].notna()
        & (chrono["date_fin_contrat"] < chrono["date_debut_contrat"])
    )
    chrono["fin_effet_before_debut_effet"] = (
        chrono["date_fin_effet"].notna()
        & chrono["date_debut_effet"].notna()
        & (chrono["date_fin_effet"] < chrono["date_debut_effet"])
    )
    chrono["dateprec_before_debut_contrat"] = (
        chrono["date_derniere_operation"].notna()
        & chrono["date_debut_contrat"].notna()
        & (chrono["date_derniere_operation"] < chrono["date_debut_contrat"])
    )

    chrono_flags = ["negative_duree", "fin_before_debut_contrat", "fin_effet_before_debut_effet", "dateprec_before_debut_contrat"]
    for flag in chrono_flags:
        metrics[flag] = int(chrono[flag].sum())

    chrono_issues = chrono.loc[chrono[chrono_flags].any(axis=1)].copy()
    if not chrono_issues.empty:
        chrono_issues["date_field"] = "CHRONOLOGY"
        chrono_issues["source_date_value"] = ""
        chrono_issues["parsed_date"] = ""
        chrono_issues["parsed_date_sk"] = 0
        chrono_issues["date_status"] = "CHRONOLOGY_ANOMALY"
        # Pandas nullable booleans can contain pd.NA, and bool(pd.NA) raises
        # "TypeError: boolean value of NA is ambiguous". Fill nullable flags
        # before building the human-readable reason.
        chrono_reason_flags = chrono_issues[chrono_flags].fillna(False).astype(bool)
        chrono_issues["reason"] = chrono_reason_flags.apply(
            lambda r: "; ".join(flag for flag, is_issue in r.items() if is_issue),
            axis=1,
        )
        rows.extend(chrono_issues[[
            "contrat_mouvement_key",
            "contrat_key",
            "date_field",
            "source_date_value",
            "parsed_date",
            "parsed_date_sk",
            "date_status",
            "reason",
            "date_debut_contrat",
            "date_fin_contrat",
            "date_debut_effet",
            "date_fin_effet",
            "date_derniere_operation",
            "duree_contrat",
        ]].to_dict("records"))

    report_cols = [
        "contrat_mouvement_key",
        "contrat_key",
        "date_field",
        "source_date_value",
        "parsed_date",
        "parsed_date_sk",
        "date_status",
        "reason",
        "date_debut_contrat",
        "date_fin_contrat",
        "date_debut_effet",
        "date_fin_effet",
        "date_derniere_operation",
        "duree_contrat",
    ]
    pd.DataFrame(rows, columns=report_cols).to_csv(DATE_ANOMALIES_PATH, index=False, encoding="utf-8-sig")
    return metrics

def _write_amount_anomalies_report(df: pd.DataFrame, invalid_total_prime: pd.Series) -> dict[str, int]:
    report = df[["contrat_mouvement_key", "contrat_key", "total_prime"]].copy()
    report["invalid_total_prime_cast"] = invalid_total_prime.reindex(report.index).fillna(False).astype(bool)
    report["negative_total_prime"] = report["total_prime"] < 0
    positive = report.loc[report["total_prime"] > 0, "total_prime"].dropna()
    threshold = float(positive.quantile(0.99)) if not positive.empty else None
    report["very_high_total_prime"] = False if threshold is None else report["total_prime"] > threshold
    flags = ["invalid_total_prime_cast", "negative_total_prime", "very_high_total_prime"]
    metrics = {flag: int(report[flag].sum()) for flag in flags}
    report = report.loc[report[flags].any(axis=1)]
    report.to_csv(AMOUNT_ANOMALIES_PATH, index=False, encoding="utf-8-sig")
    metrics["amount_anomaly_rows"] = len(report)
    return metrics


def _write_load_summary(metrics: dict) -> None:
    pd.DataFrame([{"metric": k, "value": v} for k, v in sorted(metrics.items())]).to_csv(LOAD_SUMMARY_PATH, index=False, encoding="utf-8-sig")


def transform_fact_contrat(df_raw: pd.DataFrame, dims: dict, logger) -> tuple[pd.DataFrame, dict]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    df = df_raw.copy()
    df["_source_order"] = range(len(df))
    n_source = len(df)

    df["contrat_key"] = df["numcnt"].map(dwh_utils.normalize_numcnt)
    df["numero_contrat"] = df["contrat_key"]
    df["numero_avenant"] = df["numavt"].map(lambda v: _clean_code(v, allow_zero=True))
    df["numero_mise_a_jour"] = df["nummaj"].map(lambda v: _clean_code(v, allow_zero=True))
    df["contrat_mouvement_key"] = df.apply(lambda r: _join_key([r["contrat_key"], r["numero_avenant"], r["numero_mise_a_jour"]]), axis=1)

    key_metrics = _write_invalid_contract_keys_report(df)
    df = df[df["contrat_key"].notna() & df["contrat_mouvement_key"].notna()].copy()

    df["code_produit"] = df["codprod"].map(_clean_code)
    df["client_key"] = df["idclt"].map(_clean_code)
    df["natint_key"] = df["natint"].map(_clean_code)
    df["idint_key"] = df["idint"].map(_clean_code)
    df["intermediaire_key"] = df.apply(lambda r: _join_key([r["natint_key"], r["idint_key"]]), axis=1)

    valid_date_keys = dims["date_keys"]
    _apply_date_field(df, "debcnt", "date_debut_contrat", valid_date_keys)
    _apply_date_field(df, "fincnt", "date_fin_contrat", valid_date_keys)
    _apply_date_field(df, "debeffet", "date_debut_effet", valid_date_keys)
    _apply_date_field(df, "fineffet", "date_fin_effet", valid_date_keys)
    _apply_date_field(df, "dateprec", "date_derniere_operation", valid_date_keys)

    duree_source, invalid_duree = _to_numeric_series(df["duree"])
    calculated_duree = (df["date_fin_contrat"].dt.normalize() - df["date_debut_contrat"].dt.normalize()).dt.days.astype("Int64")
    df["duree_contrat"] = duree_source.round().astype("Int64").where(duree_source.notna(), calculated_duree)
    df["total_prime"], invalid_total_prime = _to_numeric_series(df["total_prime"])

    df["situation_contrat"] = df["situat"].map(_clean_text)
    df["type_resiliation"] = df["typeresil"].map(_clean_code)
    df["libelle_resiliation"] = df["lib_resil"].map(_clean_text)
    df["est_contrat_resilie"] = df.apply(lambda r: _resilie_flag(r.get("situat"), r.get("typeresil"), r.get("lib_resil")), axis=1).astype("boolean")
    df["est_contrat_actif"] = df.apply(lambda r: _actif_flag(r.get("situat"), r.get("est_contrat_resilie")), axis=1).astype("boolean")
    df["est_coassurance"] = df["coassur"].map(_bool_from_source).astype("boolean")
    df["est_avenant"] = df["numavt"].map(_is_non_zero_code).astype("boolean")
    df["est_mise_a_jour"] = df["nummaj"].map(_is_non_zero_code).astype("boolean")
    df["est_auto_scope"] = df["code_produit"].map(lambda v: pd.NA if v is None else str(v).startswith("5")).astype("boolean")

    n_duplicate_report_rows = _write_duplicate_report(df)
    df, n_duplicate_resolved = _deduplicate_grain(df)

    df["contrat_sk"] = df["contrat_key"].map(dims["contrat"]).fillna(0).astype("int64")
    df["client_sk"] = df["client_key"].map(dims["client"]).fillna(0).astype("int64")
    df["produit_sk"] = df["code_produit"].map(dims["produit"]).fillna(0).astype("int64")
    df["intermediaire_sk"] = df["intermediaire_key"].map(dims["intermediaire"]).fillna(0).astype("int64")

    df["date_resiliation_sk"] = df.apply(
        lambda r: int(r["date_derniere_operation_sk"]) if str(r["est_contrat_resilie"]).upper() == "TRUE" else 0,
        axis=1,
    ).astype("int64")

    df["nombre_contrat_mouvement"] = 1
    df["source_system"] = SOURCE_SYSTEM
    df["created_at"] = TODAY

    unmatched_metrics = _write_unmatched_dimensions_report(df)
    date_metrics = _write_date_anomalies_report(df)
    amount_metrics = _write_amount_anomalies_report(df, invalid_total_prime)

    df = df.sort_values(["contrat_key", "numero_avenant", "numero_mise_a_jour"], na_position="last").reset_index(drop=True)
    df.insert(0, "fact_contrat_sk", range(1, len(df) + 1))
    for col in FINAL_COLS:
        if col not in df.columns:
            df[col] = pd.NA
    df_final = df[FINAL_COLS].copy()

    for col in [c for c in FINAL_COLS if c.endswith("_sk")]:
        df_final[col] = pd.to_numeric(df_final[col], errors="coerce").fillna(0).astype("int64")
    df_final["duree_contrat"] = pd.to_numeric(df_final["duree_contrat"], errors="coerce").astype("Int64")
    df_final["nombre_contrat_mouvement"] = pd.to_numeric(df_final["nombre_contrat_mouvement"], errors="coerce").fillna(1).astype("int64")
    df_final["total_prime"] = pd.to_numeric(df_final["total_prime"], errors="coerce").astype("Float64")

    metrics = {
        "source_rows": n_source,
        "final_fact_rows": len(df_final),
        "duplicate_grain_rows_detected": n_duplicate_report_rows,
        "duplicate_grain_rows_resolved": n_duplicate_resolved,
        "fact_contrat_rows_loaded": len(df_final),
        "invalid_duree_cast": int(invalid_duree.sum()),
        **key_metrics,
        **unmatched_metrics,
        **date_metrics,
        **amount_metrics,
    }
    _write_load_summary(metrics)
    return df_final, metrics


def load_fact_contrat(run_id: str, engine, logger) -> int:
    logger.info(f"[RUN {run_id}] {SOURCE_TABLE} -> dwh.{TABLE_NAME}")
    dwh_utils.create_dwh_schema(engine, logger)
    with engine.connect() as conn:
        source_exists = conn.execute(text("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'staging' AND table_name = 'stg_production'
        """)).fetchone()
    if not source_exists:
        raise RuntimeError("Table source staging.stg_production introuvable. Run staging load first.")

    df_raw = _read_staging(engine, logger)
    dims = _dimension_maps(engine, logger)
    df_final, metrics = transform_fact_contrat(df_raw, dims, logger)
    n_rows, elapsed = dwh_utils.write_to_dwh(df_final, engine, TABLE_NAME, logger, chunksize=1000)

    logger.info("=" * 72)
    logger.info(f"  source rows                         : {metrics['source_rows']}")
    logger.info(f"  final fact rows                     : {metrics['final_fact_rows']}")
    logger.info(f"  duplicate grain rows detected       : {metrics['duplicate_grain_rows_detected']}")
    logger.info(f"  duplicate grain rows resolved       : {metrics['duplicate_grain_rows_resolved']}")
    logger.info(f"  missing contrat_sk                  : {metrics['missing_contrat_sk']}")
    logger.info(f"  missing client_sk                   : {metrics['missing_client_sk']}")
    logger.info(f"  missing produit_sk                  : {metrics['missing_produit_sk']}")
    logger.info(f"  missing intermediaire_sk            : {metrics['missing_intermediaire_sk']}")
    logger.info(f"  invalid contract key rows           : {metrics['invalid_contract_key_rows']}")
    logger.info(f"  missing important dates             : {metrics['missing_date_debut_contrat'] + metrics['missing_date_fin_contrat'] + metrics['missing_date_debut_effet'] + metrics['missing_date_fin_effet']}")
    logger.info(f"  negative duration count             : {metrics['negative_duree']}")
    logger.info(f"  negative total_prime count          : {metrics['negative_total_prime']}")
    logger.info(f"  amount anomaly rows                 : {metrics['amount_anomaly_rows']}")
    logger.info(f"  fact_contrat rows loaded            : {n_rows}")
    logger.info(f"  unmatched dimensions report         : {UNMATCHED_DIMS_PATH}")
    logger.info(f"  duplicate grain report              : {DUPLICATE_GRAIN_PATH}")
    logger.info(f"  date anomalies report               : {DATE_ANOMALIES_PATH}")
    logger.info(f"  amount anomalies report             : {AMOUNT_ANOMALIES_PATH}")
    logger.info(f"  invalid contract keys report        : {INVALID_KEYS_PATH}")
    logger.info(f"  load summary report                 : {LOAD_SUMMARY_PATH}")
    logger.info(f"  load duration                       : {elapsed:.1f}s")
    logger.info("=" * 72)
    logger.info("Validation SQL queries:")
    logger.info("""
SELECT COUNT(*) AS total_rows
FROM dwh.fact_contrat;

SELECT contrat_mouvement_key, COUNT(*) AS nb
FROM dwh.fact_contrat
GROUP BY contrat_mouvement_key
HAVING COUNT(*) > 1;

SELECT
    COUNT(*) FILTER (WHERE contrat_sk = 0) AS missing_contrat,
    COUNT(*) FILTER (WHERE client_sk = 0) AS missing_client,
    COUNT(*) FILTER (WHERE produit_sk = 0) AS missing_produit,
    COUNT(*) FILTER (WHERE intermediaire_sk = 0) AS missing_intermediaire
FROM dwh.fact_contrat;

SELECT
    COUNT(*) FILTER (WHERE date_debut_contrat_sk = 0) AS missing_date_debut_contrat,
    COUNT(*) FILTER (WHERE date_fin_contrat_sk = 0) AS missing_date_fin_contrat,
    COUNT(*) FILTER (WHERE date_debut_effet_sk = 0) AS missing_date_debut_effet,
    COUNT(*) FILTER (WHERE date_fin_effet_sk = 0) AS missing_date_fin_effet,
    COUNT(*) FILTER (WHERE date_derniere_operation_sk = 0) AS missing_date_derniere_operation
FROM dwh.fact_contrat;

SELECT
    COUNT(*) FILTER (WHERE duree_contrat < 0) AS negative_duree,
    COUNT(*) FILTER (WHERE total_prime < 0) AS negative_prime
FROM dwh.fact_contrat;

SELECT est_auto_scope, COUNT(*) AS nb
FROM dwh.fact_contrat
GROUP BY est_auto_scope
ORDER BY nb DESC;

SELECT est_contrat_resilie, COUNT(*) AS nb
FROM dwh.fact_contrat
GROUP BY est_contrat_resilie
ORDER BY nb DESC;
""")
    return n_rows


if __name__ == "__main__":
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logger = dwh_utils.setup_logging(run_id, log_name="load_fact_contrat")
    engine = dwh_utils.build_engine(logger)
    n = load_fact_contrat(run_id, engine, logger)
    logger.info(f"Done: {n} rows -> dwh.{TABLE_NAME}")

