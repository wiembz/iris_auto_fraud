"""
etl/dwh/load_fact_inspection_vehicule.py
=========================================
Build dwh.fact_inspection_vehicule from staging.stg_inspection.

Grain: one row per STAFIM vehicle inspection.
Business key: inspection_key = immatriculation_norm || '|' || date_inspection_sk || '|' || inspection_source_id.

Checklist anomaly counting
--------------------------
STAFIM inspection records contain raw checklist columns produced by
sa_utils.normalize_column_name from the Excel headers:
  "TOUR DU VEHICULE [...]"       -> tour_du_vehicule_*
  "DANS LE VEHICULE [...]"       -> dans_le_vehicule_*
  "SOUS LE CAPOT [...]"          -> sous_le_capot_*
  "SOUS LE VEHICULE [...]"       -> sous_le_vehicule_*
  "AUTRES PRESTATIONS [...]"     -> autres_prestations_*

Each checklist cell is classified: OK / anomaly / unknown.
Anomalies are counted per section and across all sections (nb_anomalies_total).
Safety-critical anomalies are counted separately (nb_anomalies_critiques).

VHS note -- columns intentionally absent
-----------------------------------------
score_etat_vehicule, niveau_etat_vehicule, grade_vhs, and score_vhs are NOT
loaded in fact_inspection_vehicule. They will be produced by a dedicated Vehicle
Health Score (VHS) layer built on top of this fact table.
fact_inspection_vehicule only stores observed STAFIM inspection measures and
anomaly counts. It does not score, grade, or classify vehicles.

This loader is purely descriptive and observational. It does not classify fraud.
"""
from __future__ import annotations

import datetime as dt_module
import math
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

DWH_DIR = Path(__file__).resolve().parent
BASE_DIR = DWH_DIR.parent.parent
sys.path.insert(0, str(DWH_DIR))
sys.path.insert(0, str(BASE_DIR))
import dwh_utils
from etl.utils.vehicle_normalization import normalize_immatriculation as _normalize_primary_immatriculation

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent
TABLE_NAME = "fact_inspection_vehicule"
SOURCE_TABLE = "staging.stg_inspection"
SOURCE_SYSTEM = "STAFIM"
TODAY = datetime.now(timezone.utc).replace(tzinfo=None)

REPORT_DIR = BASE_DIR / "data" / "quality_reports" / "fact_inspection_vehicule"
UNMATCHED_VEHICULES_PATH = REPORT_DIR / "fact_inspection_unmatched_vehicules.csv"
DUPLICATE_GRAIN_PATH      = REPORT_DIR / "fact_inspection_duplicate_grain.csv"
DATE_ANOMALIES_PATH       = REPORT_DIR / "fact_inspection_date_anomalies.csv"
MEASURE_ANOMALIES_PATH    = REPORT_DIR / "fact_inspection_measure_anomalies.csv"
CHECKLIST_MAPPING_PATH    = REPORT_DIR / "fact_inspection_checklist_mapping_report.csv"
LOAD_SUMMARY_PATH         = REPORT_DIR / "fact_inspection_load_summary.csv"

# score_etat_vehicule, niveau_etat_vehicule, and indicateur_mauvais_etat are
# intentionally excluded -- they belong to the VHS layer, not the base fact.
FINAL_COLS = [
    "fact_inspection_vehicule_sk",
    "inspection_key",
    "immatriculation_norm",
    "vehicule_sk",
    "date_inspection_sk",
    "kilometrage",
    "nb_anomalies_tour_vehicule",
    "nb_anomalies_interieur",
    "nb_anomalies_sous_capot",
    "nb_anomalies_sous_vehicule",
    "nb_anomalies_entretien",
    "nb_anomalies_total",
    "nb_anomalies_critiques",
    "indicateur_anomalie_critique",
    "indicateur_inspection_complete",
    "agent_controle",
    "source_system",
    "created_at",
]

# Staging columns needed (canonical -> candidates)
STAGING_CANDIDATES: dict[str, list[str]] = {
    "inspection_source_id":       ["inspection_source_id"],
    "date_inspection":            ["date_inspection", "date", "DATE_VISITE", "DATE_INSPECTION"],
    "immatriculation":            ["immatriculation", "N° D'IMMATRICULATION", "IMMATRICULATION", "IMMAT"],
    "kilometrage":                ["kilometrage", "KILOMETRAGE", "KILOMETRAGE_COMPTEUR", "KM"],
    "nb_anomalies_tour_vehicule": ["nb_anomalies_tour_vehicule"],
    "nb_anomalies_interieur":     ["nb_anomalies_interieur"],
    "nb_anomalies_sous_capot":    ["nb_anomalies_sous_capot"],
    "nb_anomalies_sous_vehicule": ["nb_anomalies_sous_vehicule"],
    "nb_anomalies_entretien":     ["nb_anomalies_entretien"],
    "nb_anomalies_total":         ["nb_anomalies_total"],
    "nom_agent_inspection":       ["nom_agent_inspection", "NOM DE L'AGENT", "AGENT", "NOM_AGENT"],
    "is_valid_for_join":          ["is_valid_for_join"],
}

# Checklist section prefix -> fact column name
CHECKLIST_PREFIXES: dict[str, str] = {
    "tour_du_vehicule_":   "nb_anomalies_tour_vehicule",
    "dans_le_vehicule_":   "nb_anomalies_interieur",
    "sous_le_capot_":      "nb_anomalies_sous_capot",
    "sous_le_vehicule_":   "nb_anomalies_sous_vehicule",
    "autres_prestations_": "nb_anomalies_entretien",
}

_ANOMALY_SECTION_COLS = [
    "nb_anomalies_tour_vehicule",
    "nb_anomalies_interieur",
    "nb_anomalies_sous_capot",
    "nb_anomalies_sous_vehicule",
    "nb_anomalies_entretien",
]

# Columns to never treat as checklist even if prefix matches
_EXCLUDE_CHECKLIST_COL = re.compile(
    r"commentaire|image\d*$",
    re.IGNORECASE,
)

# Checklist value classification (after _strip_accents + uppercase)
OK_VALUES: frozenset[str] = frozenset({
    "BON", "CONTROLE OK", "OUI", "RAS", "NORMAL", "CONFORME", "OK",
})

ANOMALY_VALUES: frozenset[str] = frozenset({
    "DEFECTUEUX", "CONTROLE NON OK",
    "INTERVENTION CONSEILLEE", "PROPOSITION FAITE",
    "NON",
    "A REMPLACER", "CASSE",
    "FUITE", "CORROSION", "NIVEAU MIN",
    "NE FONCTIONNE PAS", "HS", "JEU",
    "NON CONFORME", "ENDOMMAGE",
})

# Substrings to match in free-text checklist values (catch comments like "Fuite d'huile")
ANOMALY_SUBSTRINGS: tuple[str, ...] = (
    "FUITE", "CORROSION", "CASSE", "DEFECTUEUX",
    "REMPLACER", "INTERVENTION", "NE FONCTIONNE",
    "NIVEAU MIN", "NON OK", "NON CONFORME", "ENDOMMAGE",
)

# Safety-critical keywords detected in column names (snake_case, no accents).
# Narrowed to items whose failure directly endangers road safety or causes
# structural damage. Lighting, battery, filters, wipers, AC excluded -- they
# remain normal anomalies but not critical ones.
CRITICAL_COL_SUBSTRINGS: tuple[str, ...] = (
    "frein", "plaquette", "disque", "etrier",
    "pneu", "pneumatique", "amortisseur",
    "transmission", "rotule", "cremaillere",
    "direction",
    "liquide_de_frein",
    "courroie_de_distribution", "courroie_distribution",
    "chassis", "sous_caisse",
)

# Critical keywords detected in cell values (after normalization, uppercase).
# Requires specific phrasing to avoid false positives on minor leaks or
# generic "HS" comments unrelated to safety-critical systems.
CRITICAL_VALUE_SUBSTRINGS: tuple[str, ...] = (
    "FUITE HUILE", "FUITE EAU",
    "CORROSION",
    "CHASSIS",
)

INVALID_TEXT = frozenset({
    "", "NULL", "NAN", "NONE", "UNKNOWN", "INCONNU", "INCONNUE",
    "NON RENSEIGNE", "NON RENSEIGNEE", "N/A", "NA", "#N/A",
    "ND", "NR", "/", "-", "--", "---", ".", "..",
    "SANS", "RAS",
})


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def normalize_immatriculation(value: object) -> str | None:
    """Backward-compatible wrapper around shared DWH vehicle normalization."""
    return _normalize_primary_immatriculation(value)


def _clean_text(value: object) -> str | None:
    if _is_missing(value):
        return None
    s = re.sub(r"\s+", " ", str(value).strip()).upper()
    return None if s in INVALID_TEXT else s


def _clean_agent(value: object) -> str | None:
    s = _clean_text(value)
    discard = INVALID_TEXT | frozenset({"TEST", "AGENT", "INCONNU", "INCONNUE"})
    return None if s is None or s in discard else s


def _to_date_sk_detail(value: object, dim_date_keys: set[int]) -> dict:
    """Convert source date to YYYYMMDD dim_date key with status dict."""
    if _is_missing(value):
        return {
            "date_sk": 0, "parsed_date": pd.NaT,
            "date_status": "SOURCE_DATE_MISSING",
            "reason": "source date is null, empty, or placeholder",
        }
    if isinstance(value, (dt_module.date, dt_module.datetime)):
        ts = pd.Timestamp(value)
        key = int(ts.strftime("%Y%m%d"))
        if key in dim_date_keys:
            return {"date_sk": key, "parsed_date": ts, "date_status": "DATE_JOIN_OK", "reason": "Python date matched"}
        return {"date_sk": 0, "parsed_date": ts, "date_status": "DATE_OUTSIDE_DIM_DATE", "reason": f"{key} not in dim_date"}
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return {"date_sk": 0, "parsed_date": pd.NaT, "date_status": "SOURCE_DATE_MISSING", "reason": "NaT"}
        key = int(value.strftime("%Y%m%d"))
        if key in dim_date_keys:
            return {"date_sk": key, "parsed_date": value, "date_status": "DATE_JOIN_OK", "reason": "Timestamp matched"}
        return {"date_sk": 0, "parsed_date": value, "date_status": "DATE_OUTSIDE_DIM_DATE", "reason": f"{key} not in dim_date"}
    raw = str(value).strip()
    if raw.upper() in INVALID_TEXT or raw in {"0", "0.0", "00000000", "0000-00-00"}:
        return {"date_sk": 0, "parsed_date": pd.NaT, "date_status": "SOURCE_DATE_MISSING", "reason": f"placeholder: {value!r}"}
    m = re.fullmatch(r"(\d{8})(?:\.0+)?", raw)
    if m:
        key = int(m.group(1))
        ts = pd.to_datetime(str(key), format="%Y%m%d", errors="coerce")
        if pd.isna(ts):
            return {"date_sk": 0, "parsed_date": pd.NaT, "date_status": "SOURCE_DATE_INVALID", "reason": f"invalid YYYYMMDD: {value!r}"}
        return ({"date_sk": key, "parsed_date": ts, "date_status": "DATE_JOIN_OK", "reason": "YYYYMMDD matched"}
                if key in dim_date_keys else
                {"date_sk": 0, "parsed_date": ts, "date_status": "DATE_OUTSIDE_DIM_DATE", "reason": f"{key} not in dim_date"})
    m_s = re.fullmatch(r"(\d{4,5})(?:\.0*)?", raw)
    if m_s:
        try:
            serial = int(m_s.group(1))
            if 1 <= serial <= 60000:
                ts = pd.Timestamp("1899-12-30") + pd.Timedelta(days=serial)
                key = int(ts.strftime("%Y%m%d"))
                return ({"date_sk": key, "parsed_date": ts, "date_status": "DATE_JOIN_OK", "reason": f"Excel serial {serial}"}
                        if key in dim_date_keys else
                        {"date_sk": 0, "parsed_date": ts, "date_status": "DATE_OUTSIDE_DIM_DATE", "reason": f"serial {serial}->{key} not in dim_date"})
        except (ValueError, OverflowError):
            pass
    ts = (pd.to_datetime(raw, errors="coerce", dayfirst=False)
          if re.match(r"^\d{4}[-/]", raw)
          else pd.to_datetime(raw, errors="coerce", dayfirst=True))
    if pd.isna(ts):
        return {"date_sk": 0, "parsed_date": pd.NaT, "date_status": "SOURCE_DATE_INVALID", "reason": f"unable to parse: {value!r}"}
    key = int(ts.strftime("%Y%m%d"))
    return ({"date_sk": key, "parsed_date": ts, "date_status": "DATE_JOIN_OK", "reason": "string parsed and matched"}
            if key in dim_date_keys else
            {"date_sk": 0, "parsed_date": ts, "date_status": "DATE_OUTSIDE_DIM_DATE", "reason": f"{key} not in dim_date"})


def _to_numeric_series(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    raw = (
        series.astype(str).str.strip()
        .str.replace(r"\s+", "", regex=True)
        .str.replace(",", ".", regex=False)
        .str.upper()
        .str.replace(r"KM$", "", regex=True)
        .str.strip()
    )
    raw = raw.mask(raw.isin(INVALID_TEXT) | raw.isin({"0.0", "NAN"}), pd.NA)
    numeric = pd.to_numeric(raw, errors="coerce").astype("Float64")
    invalid = series.notna() & numeric.isna()
    return numeric, invalid


# ---------------------------------------------------------------------------
# Checklist helpers
# ---------------------------------------------------------------------------

def _strip_accents(s: str) -> str:
    """Remove diacritical marks. 'Defectueux' <- 'Défectueux'."""
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode("ascii")


def _normalize_checklist_value(value: object) -> str | None:
    """Normalize a checklist cell value for classification.

    Returns None for null/empty values.
    Applies: accent removal, uppercase, whitespace collapse.
    """
    if _is_missing(value):
        return None
    s = str(value).strip()
    if not s:
        return None
    s = _strip_accents(s)
    s = re.sub(r"\s+", " ", s).upper().strip()
    return s if s else None


def _is_ok_value(norm: str | None) -> bool:
    if not norm:
        return False
    return norm in OK_VALUES


def _is_anomaly_value(norm: str | None) -> bool:
    """True for exact anomaly values or free-text containing anomaly keywords."""
    if not norm:
        return False
    if norm in ANOMALY_VALUES:
        return True
    return any(sub in norm for sub in ANOMALY_SUBSTRINGS)


def _is_critical_col(col_name: str) -> bool:
    """True if snake_case column name refers to a safety-critical inspection item."""
    norm = _strip_accents(col_name.lower())
    return any(kw in norm for kw in CRITICAL_COL_SUBSTRINGS)


def _is_critical_value(norm: str | None) -> bool:
    """True if the normalized cell value contains a safety-critical keyword."""
    if not norm:
        return False
    return any(kw in norm for kw in CRITICAL_VALUE_SUBSTRINGS)


def _detect_checklist_columns(all_cols: list[str]) -> list[str]:
    """Return columns that belong to a known checklist section, excluding commentary."""
    result = []
    for col in all_cols:
        cl = col.lower()
        if any(cl.startswith(prefix) for prefix in CHECKLIST_PREFIXES):
            if not _EXCLUDE_CHECKLIST_COL.search(cl):
                result.append(col)
    return result


def _count_checklist_anomalies(
    df: pd.DataFrame,
    checklist_cols: list[str],
    logger,
) -> tuple[dict[str, pd.Series], pd.Series, list[dict]]:
    """Count anomalies per section from raw checklist columns.

    Returns:
      section_counts  -- {fact_col: Int64 Series}
      nb_critiques    -- Int64 Series (per-row count of critical anomalies)
      mapping_rows    -- list of dicts for the checklist mapping report
    """
    col_to_section: dict[str, str] = {}
    for col in checklist_cols:
        for prefix, fact_col in CHECKLIST_PREFIXES.items():
            if col.lower().startswith(prefix):
                col_to_section[col] = fact_col
                break

    section_anomaly_lists: dict[str, list[pd.Series]] = {v: [] for v in CHECKLIST_PREFIXES.values()}
    nb_critiques    = pd.Series(0, index=df.index, dtype="int64")
    mapping_rows: list[dict] = []
    total_classified = pd.Series(0, index=df.index, dtype="int64")

    for col in checklist_cols:
        fact_col = col_to_section.get(col)
        if fact_col is None:
            continue

        col_is_critical = _is_critical_col(col)
        raw_series = df[col]

        norm = raw_series.map(_normalize_checklist_value)

        is_ok      = norm.map(_is_ok_value)
        is_anomaly = norm.map(_is_anomaly_value)
        has_data   = norm.notna()

        # Critical anomaly: anomaly in critical column OR value contains critical keyword
        is_critical_anomaly = is_anomaly & (col_is_critical | norm.map(_is_critical_value))

        ok_count            = int(is_ok.sum())
        anomaly_count       = int(is_anomaly.sum())
        unknown_count       = int((has_data & ~is_ok & ~is_anomaly).sum())
        critical_anom_count = int(is_critical_anomaly.sum())

        top_values = norm.dropna().value_counts().head(10).to_dict()

        mapping_rows.append({
            "column_name":            col,
            "assigned_category":      fact_col,
            "is_critical_column":     col_is_critical,
            "detected_values":        "; ".join(f"{v}={n}" for v, n in list(top_values.items())[:5]),
            "ok_count":               ok_count,
            "anomaly_count":          anomaly_count,
            "unknown_count":          unknown_count,
            "null_count":             int((~has_data).sum()),
            "critical_anomaly_count": critical_anom_count,
        })

        section_anomaly_lists[fact_col].append(is_anomaly.astype("int64"))
        nb_critiques    += is_critical_anomaly.astype("int64")
        total_classified += has_data.astype("int64")

    # Aggregate per section: sum of per-column anomaly flags
    section_counts: dict[str, pd.Series] = {}
    for fact_col, series_list in section_anomaly_lists.items():
        if not series_list:
            section_counts[fact_col] = pd.Series(pd.NA, index=df.index, dtype="Int64")
        else:
            agg = pd.Series(0, index=df.index, dtype="Int64")
            for s in series_list:
                agg = agg + s.astype("Int64")
            section_counts[fact_col] = agg

    n_critical_cols = sum(1 for col in checklist_cols if _is_critical_col(col))
    logger.info(
        f"  checklist: {len(checklist_cols)} cols processed, "
        f"{n_critical_cols} safety-critical cols, "
        f"total critical anomaly values found: {int(nb_critiques.sum())}"
    )
    return section_counts, nb_critiques.astype("Int64"), mapping_rows


# ---------------------------------------------------------------------------
# Data reading
# ---------------------------------------------------------------------------

def _read_staging(engine, logger) -> tuple[pd.DataFrame, list[str]]:
    """Read staging.stg_inspection. Returns (df, checklist_cols)."""
    with engine.connect() as conn:
        available_rows = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'staging' AND table_name = 'stg_inspection'
            ORDER BY ordinal_position
        """)).fetchall()
    all_cols = [row[0] for row in available_rows]
    lower_to_actual: dict[str, str] = {c.lower(): c for c in all_cols}

    # Build SELECT for STAGING_CANDIDATES
    select_parts: list[str] = []
    for canonical, candidates in STAGING_CANDIDATES.items():
        actual_col: str | None = None
        for cand in candidates:
            actual_col = lower_to_actual.get(cand.lower())
            if actual_col:
                break
        if actual_col:
            alias = f'"{actual_col}" AS "{canonical}"' if actual_col != canonical else f'"{actual_col}"'
            select_parts.append(alias)
            logger.info(f"  staging col {canonical:<28} <- {actual_col}")
        else:
            logger.warning(f"  staging col missing: {canonical}; will be NULL")

    # Detect checklist columns
    checklist_cols = _detect_checklist_columns(all_cols)
    for col in checklist_cols:
        select_parts.append(f'"{col}"')

    n_critical_checklist = sum(1 for c in checklist_cols if _is_critical_col(c))
    logger.info(
        f"  detected {len(checklist_cols)} checklist columns "
        f"({n_critical_checklist} safety-critical)"
    )
    if not checklist_cols:
        logger.warning("  NO checklist columns detected -- anomaly counts will fall back to staging aggregates")

    if not select_parts:
        raise RuntimeError("No expected columns found in staging.stg_inspection.")

    with engine.connect() as conn:
        df = pd.read_sql(
            text(f"SELECT {', '.join(select_parts)} FROM {SOURCE_TABLE}"), conn
        )

    for canonical in STAGING_CANDIDATES:
        if canonical not in df.columns:
            df[canonical] = pd.NA

    logger.info(f"  source rows read: {len(df)}")
    return df, checklist_cols


def _read_table(engine, table_name: str, columns: list[str]) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text(f"SELECT {', '.join(columns)} FROM dwh.{table_name}"), conn)


def _dimension_maps(engine, logger) -> dict:
    dims: dict = {}

    dim_v = _read_table(engine, "dim_vehicule", ["vehicule_sk", "immatriculation"])
    dim_v["_key"] = dim_v["immatriculation"].map(normalize_immatriculation)
    dims["vehicule"] = (
        dim_v.dropna(subset=["_key"])
        .drop_duplicates("_key")
        .set_index("_key")["vehicule_sk"]
        .to_dict()
    )
    logger.info(f"  dim_vehicule: {len(dims['vehicule'])} keys")

    dim_d = _read_table(engine, "dim_date", ["date_sk"])
    dims["date_keys"] = set(pd.to_numeric(dim_d["date_sk"], errors="coerce").dropna().astype(int))
    logger.info(f"  dim_date: {len(dims['date_keys'])} keys")

    return dims


# ---------------------------------------------------------------------------
# Quality report writers
# ---------------------------------------------------------------------------

def _write_duplicate_report(df: pd.DataFrame) -> int:
    cols = ["inspection_key", "immatriculation_norm", "date_inspection_sk", "inspection_source_id"]
    dup = df[df["inspection_key"].duplicated(keep=False)].copy()
    if dup.empty:
        pd.DataFrame(columns=cols + ["duplicate_count"]).to_csv(DUPLICATE_GRAIN_PATH, index=False, encoding="utf-8-sig")
        return 0
    counts = dup.groupby("inspection_key").size().rename("duplicate_count").reset_index()
    report = dup[[c for c in cols if c in dup.columns]].merge(counts, on="inspection_key", how="left")
    report.to_csv(DUPLICATE_GRAIN_PATH, index=False, encoding="utf-8-sig")
    return len(report)


def _deduplicate_grain(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if not df["inspection_key"].duplicated().any():
        return df, 0
    ranked = df.copy()
    ranked["_r_immat"] = ranked["immatriculation_norm"].notna().astype(int)
    ranked["_r_date"]  = (ranked["date_inspection_sk"] != 0).astype(int)
    ranked["_r_km"]    = pd.to_numeric(ranked["kilometrage"], errors="coerce").notna().astype(int)
    ranked["_r_check"] = sum(
        pd.to_numeric(ranked.get(col, pd.Series(0, index=ranked.index)), errors="coerce").notna().astype(int)
        for col in _ANOMALY_SECTION_COLS
    )
    ranked = ranked.sort_values(
        ["inspection_key", "_r_immat", "_r_date", "_r_km", "_r_check", "inspection_source_id"],
        ascending=[True, False, False, False, False, True],
    )
    deduped = ranked.drop_duplicates("inspection_key", keep="first").drop(
        columns=["_r_immat", "_r_date", "_r_km", "_r_check"]
    )
    return deduped, len(df) - len(deduped)


def _write_unmatched_vehicules_report(df: pd.DataFrame) -> dict[str, int]:
    report = df[["inspection_key", "immatriculation_norm", "date_inspection_sk", "vehicule_sk"]].copy()
    report["source_immatriculation"] = df["immatriculation"] if "immatriculation" in df.columns else ""
    report["missing_vehicule_sk"] = report["vehicule_sk"].eq(0)
    report[report["missing_vehicule_sk"]].to_csv(UNMATCHED_VEHICULES_PATH, index=False, encoding="utf-8-sig")
    return {"missing_vehicule_sk": int(report["missing_vehicule_sk"].sum())}


def _write_date_anomalies_report(df: pd.DataFrame) -> dict[str, int]:
    issue_mask = df["_date_status"].ne("DATE_JOIN_OK")
    report = df.loc[issue_mask, [
        "inspection_key", "immatriculation_norm",
        "_source_date_inspection", "_parsed_date", "date_inspection_sk",
        "_date_status", "_date_reason",
    ]].rename(columns={
        "_source_date_inspection": "source_date_inspection",
        "_parsed_date": "parsed_date",
        "_date_status": "date_status",
        "_date_reason": "reason",
    })
    report.to_csv(DATE_ANOMALIES_PATH, index=False, encoding="utf-8-sig")
    counts = df["_date_status"].value_counts(dropna=False)
    return {
        "date_join_ok":           int(counts.get("DATE_JOIN_OK", 0)),
        "date_missing":           int(counts.get("SOURCE_DATE_MISSING", 0)),
        "date_invalid":           int(counts.get("SOURCE_DATE_INVALID", 0)),
        "date_outside_dim_date":  int(counts.get("DATE_OUTSIDE_DIM_DATE", 0)),
    }


def _write_measure_anomalies_report(
    df: pd.DataFrame,
    km_invalid: pd.Series,
    extra_metrics: dict | None = None,
) -> dict[str, int]:
    km = pd.to_numeric(df["kilometrage"], errors="coerce")
    nb = pd.to_numeric(df.get("nb_anomalies_total", pd.Series(dtype=object)), errors="coerce")

    pos_km = km[km > 0].dropna()
    km_p99 = float(pos_km.quantile(0.99)) if not pos_km.empty else None

    report = df[["inspection_key", "immatriculation_norm", "date_inspection_sk"]].copy()
    report["kilometrage"]        = km
    report["nb_anomalies_total"] = nb

    flags: list[str] = []
    report["invalid_km_cast"] = km_invalid.reindex(report.index).fillna(False).astype(bool); flags.append("invalid_km_cast")
    report["negative_km"]     = km.fillna(0) < 0;  flags.append("negative_km")
    report["extreme_km"]      = False if km_p99 is None else km.fillna(0) > km_p99; flags.append("extreme_km")

    for col in _ANOMALY_SECTION_COLS + ["nb_anomalies_total", "nb_anomalies_critiques"]:
        flag = f"negative_{col}"
        report[flag] = pd.to_numeric(df.get(col, pd.Series(0, index=df.index)), errors="coerce").fillna(0) < 0
        flags.append(flag)

    metrics: dict[str, int] = {flag: int(report[flag].sum()) for flag in flags}
    if km_p99 is not None:
        metrics["km_extreme_threshold_p99"] = int(km_p99)
    if extra_metrics:
        metrics.update(extra_metrics)
    report = report.loc[report[flags].any(axis=1)]
    metrics["measure_anomaly_rows"] = len(report)
    report.to_csv(MEASURE_ANOMALIES_PATH, index=False, encoding="utf-8-sig")
    return metrics


def _write_checklist_mapping_report(mapping_rows: list[dict]) -> None:
    """Write per-column checklist mapping report with value classification stats."""
    if mapping_rows:
        pd.DataFrame(mapping_rows).to_csv(CHECKLIST_MAPPING_PATH, index=False, encoding="utf-8-sig")
        return

    # No checklist columns: write a documentation stub
    stub = [{
        "column_name": "N/A",
        "assigned_category": "N/A",
        "is_critical_column": False,
        "detected_values": "No checklist columns found in staging.stg_inspection",
        "ok_count": 0,
        "anomaly_count": 0,
        "unknown_count": 0,
        "null_count": 0,
        "critical_anomaly_count": 0,
        "note": (
            "Expected prefixes: tour_du_vehicule_*, dans_le_vehicule_*, "
            "sous_le_capot_*, sous_le_vehicule_*, autres_prestations_*. "
            "These are produced by sa_utils.normalize_column_name from the "
            "STAFIM Excel checklist headers. Run prepare_inspection_sa first."
        ),
    }]
    pd.DataFrame(stub).to_csv(CHECKLIST_MAPPING_PATH, index=False, encoding="utf-8-sig")


def _write_load_summary(metrics: dict) -> None:
    pd.DataFrame([{"metric": k, "value": v} for k, v in sorted(metrics.items())]).to_csv(
        LOAD_SUMMARY_PATH, index=False, encoding="utf-8-sig"
    )


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def transform_fact_inspection_vehicule(
    df_raw: pd.DataFrame,
    checklist_cols: list[str],
    dims: dict,
    logger,
) -> tuple[pd.DataFrame, dict]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    df = df_raw.copy()
    n_source = len(df)
    has_checklist = len(checklist_cols) > 0

    # -- 1. immatriculation_norm ----------------------------------------------
    df["immatriculation_norm"] = df["immatriculation"].map(normalize_immatriculation)

    # -- 2. Date inspection SK ------------------------------------------------
    df["_source_date_inspection"] = df["date_inspection"].astype(str)
    date_results = df["date_inspection"].map(lambda v: _to_date_sk_detail(v, dims["date_keys"]))
    df["date_inspection_sk"] = date_results.map(lambda r: r["date_sk"]).astype("int64")
    df["_parsed_date"]       = pd.to_datetime(date_results.map(lambda r: r["parsed_date"]), errors="coerce")
    df["_date_status"]       = date_results.map(lambda r: r["date_status"])
    df["_date_reason"]       = date_results.map(lambda r: r["reason"])

    # -- 3. Inspection key ----------------------------------------------------
    df["inspection_key"] = (
        df["immatriculation_norm"].fillna("UNKNOWN").astype(str)
        + "|"
        + df["date_inspection_sk"].astype(str)
        + "|"
        + df["inspection_source_id"].fillna("0").astype(str).str.strip()
    )

    # -- 4. Duplicate detection and deduplication -----------------------------
    n_dup_report = _write_duplicate_report(df)
    df, n_dup_resolved = _deduplicate_grain(df)

    # -- 5. vehicule_sk -------------------------------------------------------
    df["vehicule_sk"] = df["immatriculation_norm"].map(dims["vehicule"]).fillna(0).astype("int64")

    # -- 6. Mileage -----------------------------------------------------------
    if df["kilometrage"].dtype == object or str(df["kilometrage"].dtype) in ("string", "object"):
        df["kilometrage"], _km_invalid = _to_numeric_series(df["kilometrage"])
    else:
        df["kilometrage"] = pd.to_numeric(df["kilometrage"], errors="coerce").astype("Float64")
        _km_invalid = pd.Series(False, index=df.index)

    # -- 7. Anomaly counts from checklist -------------------------------------
    mapping_rows: list[dict] = []
    n_no_checklist = 0

    if has_checklist:
        section_counts, nb_critiques_series, mapping_rows = _count_checklist_anomalies(df, checklist_cols, logger)
        for fact_col, series in section_counts.items():
            df[fact_col] = series
        df["nb_anomalies_total"] = (
            sum(df[col].fillna(0) for col in _ANOMALY_SECTION_COLS)
        ).astype("Int64")
        df["nb_anomalies_critiques"] = nb_critiques_series

        # indicateur_anomalie_critique: True if nb_anomalies_critiques > 0
        crit_num = pd.to_numeric(df["nb_anomalies_critiques"], errors="coerce")
        df["indicateur_anomalie_critique"] = (
            crit_num.map(lambda v: True if (not _is_missing(v) and v > 0)
                         else (False if not _is_missing(v) else pd.NA))
            .astype("boolean")
        )

    else:
        n_no_checklist = 1
        logger.warning("  no checklist columns found -- anomaly counts from staging; anomalie_critique will be NULL")

        # Fall back to staging nb_anomalies values
        for col in _ANOMALY_SECTION_COLS:
            df[col] = pd.to_numeric(df.get(col, pd.Series(pd.NA, index=df.index)), errors="coerce").astype("Int64")
        df["nb_anomalies_total"] = pd.to_numeric(
            df.get("nb_anomalies_total", pd.Series(pd.NA, index=df.index)), errors="coerce"
        ).astype("Int64")
        df["nb_anomalies_critiques"] = pd.Series(pd.NA, index=df.index, dtype="Int64")
        df["indicateur_anomalie_critique"] = pd.Series(pd.NA, index=df.index, dtype="boolean")

    # -- 8. indicateur_inspection_complete ------------------------------------
    has_immat   = df["immatriculation_norm"].notna()
    has_date    = df["date_inspection_sk"] != 0
    has_measure = (
        df["kilometrage"].notna()
        | df["nb_anomalies_total"].notna()
    )
    df["indicateur_inspection_complete"] = (has_immat & has_date & has_measure).astype("boolean")

    # -- 9. agent_controle ----------------------------------------------------
    df["agent_controle"] = df["nom_agent_inspection"].map(_clean_agent)

    # -- 10. Metadata ----------------------------------------------------------
    df["source_system"] = SOURCE_SYSTEM
    df["created_at"]    = TODAY

    # -- 11. Quality reports ---------------------------------------------------
    extra_measure = {
        "no_checklist_cols_detected": n_no_checklist,
        "checklist_cols_count":       len(checklist_cols),
    }
    unmatched_metrics = _write_unmatched_vehicules_report(df)
    date_metrics      = _write_date_anomalies_report(df)
    measure_metrics   = _write_measure_anomalies_report(df, _km_invalid, extra_measure)
    _write_checklist_mapping_report(mapping_rows)

    # -- 12. Sort and assign surrogate key -------------------------------------
    df = df.sort_values(
        ["immatriculation_norm", "date_inspection_sk", "inspection_source_id"],
        na_position="last",
    ).reset_index(drop=True)
    df.insert(0, "fact_inspection_vehicule_sk", range(1, len(df) + 1))

    # -- 13. Select and enforce types ------------------------------------------
    for col in FINAL_COLS:
        if col not in df.columns:
            df[col] = pd.NA
    df_final = df[FINAL_COLS].copy()

    for col in [c for c in FINAL_COLS if c.endswith("_sk")]:
        df_final[col] = pd.to_numeric(df_final[col], errors="coerce").fillna(0).astype("int64")

    for col in _ANOMALY_SECTION_COLS + ["nb_anomalies_total", "nb_anomalies_critiques"]:
        df_final[col] = pd.to_numeric(df_final[col], errors="coerce").astype("Int64")

    df_final["kilometrage"] = pd.to_numeric(df_final["kilometrage"], errors="coerce").astype("Float64")

    for col in ["indicateur_inspection_complete", "indicateur_anomalie_critique"]:
        df_final[col] = df_final[col].astype("boolean")

    n_rows_with_anomalies = int(
        (pd.to_numeric(df_final["nb_anomalies_total"], errors="coerce").fillna(0) > 0).sum()
    )
    n_rows_with_critical    = int((df_final["indicateur_anomalie_critique"] == True).sum())
    n_critical_checklist_cols = sum(1 for c in checklist_cols if _is_critical_col(c))

    metrics = {
        "source_rows":                        n_source,
        "final_fact_rows":                    len(df_final),
        "checklist_cols_detected":            len(checklist_cols),
        "critical_checklist_cols_detected":   n_critical_checklist_cols,
        "duplicate_inspection_keys_detected": n_dup_report,
        "duplicate_inspection_keys_resolved": n_dup_resolved,
        "missing_vehicule_sk":                int((df_final["vehicule_sk"] == 0).sum()),
        "missing_date_inspection_sk":         int((df_final["date_inspection_sk"] == 0).sum()),
        "missing_kilometrage":                int(df_final["kilometrage"].isna().sum()),
        "negative_kilometrage":               int((df_final["kilometrage"].fillna(0) < 0).sum()),
        "total_anomaly_values_found":         int(pd.to_numeric(df_final["nb_anomalies_total"], errors="coerce").fillna(0).sum()),
        "critical_anomaly_values_found":      int(pd.to_numeric(df_final["nb_anomalies_critiques"], errors="coerce").fillna(0).sum()),
        "rows_with_anomalies":                n_rows_with_anomalies,
        "rows_with_critical_anomalies":       n_rows_with_critical,
        "inspection_complete_count":          int((df_final["indicateur_inspection_complete"] == True).sum()),
        **unmatched_metrics,
        **date_metrics,
        **measure_metrics,
    }
    _write_load_summary(metrics)
    return df_final, metrics


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def load_fact_inspection_vehicule(run_id: str, engine, logger) -> int:
    logger.info(f"[RUN {run_id}] {SOURCE_TABLE} -> dwh.{TABLE_NAME}")
    dwh_utils.create_dwh_schema(engine, logger)

    with engine.connect() as conn:
        source_exists = conn.execute(text("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'staging' AND table_name = 'stg_inspection'
        """)).fetchone()
    if not source_exists:
        raise RuntimeError(
            "Table staging.stg_inspection introuvable. Run prepare_inspection_sa first."
        )

    df_raw, checklist_cols = _read_staging(engine, logger)
    dims = _dimension_maps(engine, logger)
    df_final, metrics = transform_fact_inspection_vehicule(df_raw, checklist_cols, dims, logger)
    n_rows, elapsed   = dwh_utils.write_to_dwh(df_final, engine, TABLE_NAME, logger, chunksize=1000)

    logger.info("=" * 72)
    logger.info(f"  source rows                         : {metrics['source_rows']}")
    logger.info(f"  final fact rows                     : {metrics['final_fact_rows']}")
    logger.info(f"  checklist columns detected          : {metrics['checklist_cols_detected']}")
    logger.info(f"  critical checklist cols detected    : {metrics['critical_checklist_cols_detected']}")
    logger.info(f"  duplicate inspection keys detected  : {metrics['duplicate_inspection_keys_detected']}")
    logger.info(f"  duplicate inspection keys resolved  : {metrics['duplicate_inspection_keys_resolved']}")
    logger.info(f"  missing vehicule_sk                 : {metrics['missing_vehicule_sk']}")
    logger.info(f"  missing date_inspection_sk          : {metrics['missing_date_inspection_sk']}")
    logger.info(f"    DATE_JOIN_OK                      : {metrics.get('date_join_ok', 0)}")
    logger.info(f"    SOURCE_DATE_MISSING               : {metrics.get('date_missing', 0)}")
    logger.info(f"    DATE_OUTSIDE_DIM_DATE             : {metrics.get('date_outside_dim_date', 0)}")
    logger.info(f"  missing kilometrage                 : {metrics['missing_kilometrage']}")
    logger.info(f"  total anomaly values found          : {metrics['total_anomaly_values_found']}")
    logger.info(f"  critical anomaly values found       : {metrics['critical_anomaly_values_found']}")
    logger.info(f"  rows with anomalies                 : {metrics['rows_with_anomalies']}")
    logger.info(f"  rows with critical anomalies        : {metrics['rows_with_critical_anomalies']}")
    logger.info(f"  inspection complete count           : {metrics['inspection_complete_count']}")
    logger.info(f"  fact_inspection_vehicule rows loaded: {n_rows}")
    logger.info(f"  unmatched vehicules report          : {UNMATCHED_VEHICULES_PATH}")
    logger.info(f"  duplicate grain report              : {DUPLICATE_GRAIN_PATH}")
    logger.info(f"  date anomalies report               : {DATE_ANOMALIES_PATH}")
    logger.info(f"  measure anomalies report            : {MEASURE_ANOMALIES_PATH}")
    logger.info(f"  checklist mapping report            : {CHECKLIST_MAPPING_PATH}")
    logger.info(f"  load summary report                 : {LOAD_SUMMARY_PATH}")
    logger.info(f"  load duration                       : {elapsed:.1f}s")
    logger.info("=" * 72)
    logger.info("Validation SQL queries:")
    logger.info("""
SELECT COUNT(*) AS total_rows FROM dwh.fact_inspection_vehicule;

SELECT inspection_key, COUNT(*) AS nb
FROM dwh.fact_inspection_vehicule
GROUP BY inspection_key
HAVING COUNT(*) > 1;

SELECT
    COUNT(*) FILTER (WHERE vehicule_sk = 0) AS missing_vehicule,
    COUNT(*) FILTER (WHERE date_inspection_sk = 0) AS missing_date_inspection
FROM dwh.fact_inspection_vehicule;

SELECT
    COUNT(*) FILTER (WHERE kilometrage IS NULL) AS missing_kilometrage,
    COUNT(*) FILTER (WHERE kilometrage < 0) AS negative_kilometrage
FROM dwh.fact_inspection_vehicule;

SELECT
    MIN(nb_anomalies_total) AS min_anomalies,
    ROUND(AVG(nb_anomalies_total)::numeric, 2) AS avg_anomalies,
    MAX(nb_anomalies_total) AS max_anomalies
FROM dwh.fact_inspection_vehicule;

SELECT nb_anomalies_total, COUNT(*) AS nb
FROM dwh.fact_inspection_vehicule
GROUP BY nb_anomalies_total
ORDER BY nb_anomalies_total;

SELECT indicateur_anomalie_critique, COUNT(*) AS nb
FROM dwh.fact_inspection_vehicule
GROUP BY indicateur_anomalie_critique
ORDER BY nb DESC;

SELECT indicateur_inspection_complete, COUNT(*) AS nb
FROM dwh.fact_inspection_vehicule
GROUP BY indicateur_inspection_complete
ORDER BY nb DESC;
""")
    return n_rows


if __name__ == "__main__":
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logger = dwh_utils.setup_logging(run_id, log_name="load_fact_inspection_vehicule")
    engine = dwh_utils.build_engine(logger)
    n = load_fact_inspection_vehicule(run_id, engine, logger)
    logger.info(f"Done: {n} rows -> dwh.{TABLE_NAME}")
