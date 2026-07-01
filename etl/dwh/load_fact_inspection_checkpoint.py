"""
etl/dwh/load_fact_inspection_checkpoint.py
==========================================
Build dwh.fact_inspection_checkpoint from staging.stg_inspection.

Grain: one row per STAFIM vehicle inspection x checkpoint column.
Business key: inspection_checkpoint_key = inspection_key || '|' || checkpoint_code.

Source:  staging.stg_inspection        (wide checklist columns -> normalised rows)
Joined:  dwh.fact_inspection_vehicule  (inspection_key, vehicule_sk, date_inspection_sk,
                                        immatriculation_norm)

The wide-to-long transformation produces one row per inspection x checkpoint.
Expected output: ~284 inspections x 43 checkpoints = ~12,212 rows.

VHS note -- columns intentionally absent
-----------------------------------------
score_vhs, grade_vhs, score_etat_vehicule, niveau_etat_vehicule are NOT included.
fact_inspection_checkpoint stores only observed STAFIM checkpoint results.
Scoring and grading will be produced by the dedicated VHS layer built on top
of fact_inspection_vehicule and this table.

This loader is purely descriptive and observational. It does not classify fraud.
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

# Reuse shared helpers and constants to stay consistent with
# load_fact_inspection_vehicule (same normalisation rules, same keyword lists).
from load_fact_inspection_vehicule import (
    ANOMALY_SUBSTRINGS,
    ANOMALY_VALUES,
    CHECKLIST_PREFIXES,
    CRITICAL_COL_SUBSTRINGS,
    CRITICAL_VALUE_SUBSTRINGS,
    INVALID_TEXT,
    OK_VALUES,
    SOURCE_SYSTEM,
    _detect_checklist_columns,
    _is_critical_col,
    _is_critical_value,
    _is_missing,
    _normalize_checklist_value,
    _strip_accents,
    _to_date_sk_detail,
    normalize_immatriculation,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent
TABLE_NAME    = "fact_inspection_checkpoint"
SOURCE_TABLE  = "staging.stg_inspection"
FACT_VEH_TABLE = "dwh.fact_inspection_vehicule"
TODAY = datetime.now(timezone.utc).replace(tzinfo=None)

REPORT_DIR           = BASE_DIR / "data" / "quality_reports" / "fact_inspection_checkpoint"
DUPLICATE_GRAIN_PATH = REPORT_DIR / "fact_inspection_checkpoint_duplicate_grain.csv"
UNMATCHED_PATH       = REPORT_DIR / "fact_inspection_checkpoint_unmatched_inspections.csv"
MAPPING_REPORT_PATH  = REPORT_DIR / "fact_inspection_checkpoint_mapping_report.csv"
VALUE_DIST_PATH      = REPORT_DIR / "fact_inspection_checkpoint_value_distribution.csv"
LOAD_SUMMARY_PATH    = REPORT_DIR / "fact_inspection_checkpoint_load_summary.csv"

FINAL_COLS = [
    "fact_inspection_checkpoint_sk",
    "inspection_checkpoint_key",
    "inspection_key",
    "vehicule_sk",
    "date_inspection_sk",
    "immatriculation_norm",
    "zone_controle",
    "checkpoint_code",
    "checkpoint_libelle",
    "valeur_controle",
    "commentaire_zone",
    "est_anomalie",
    "est_anomalie_critique",
    "est_controle_renseigne",
    "source_system",
    "created_at",
]

# Column prefix -> zone label
ZONE_MAP: dict[str, str] = {
    "tour_du_vehicule_":   "TOUR_DU_VEHICULE",
    "dans_le_vehicule_":   "INTERIEUR",
    "sous_le_capot_":      "SOUS_CAPOT",
    "sous_le_vehicule_":   "SOUS_VEHICULE",
    "autres_prestations_": "ENTRETIEN",
}

# Zone label -> canonical comment column name used in the final DataFrame.
# prepare_inspection_sa renames Excel "Commentaire.*" to the new names below.
ZONE_TO_COMMENT: dict[str, str] = {
    "TOUR_DU_VEHICULE": "commentaire_tour_vehicule",
    "INTERIEUR":        "commentaire_interieur",
    "SOUS_CAPOT":       "commentaire_sous_capot",
    "SOUS_VEHICULE":    "commentaire_sous_vehicule",
    "ENTRETIEN":        "commentaire_entretien",
}
ALL_COMMENT_COLS: list[str] = list(ZONE_TO_COMMENT.values())

# Fallback candidates per zone (new naming first, then legacy pandas-deduplicated names).
# Used in _read_staging to detect whichever convention is present in staging.
_ZONE_COMMENT_CANDIDATES: dict[str, list[str]] = {
    "TOUR_DU_VEHICULE": ["commentaire_tour_vehicule", "commentaire"],
    "INTERIEUR":        ["commentaire_interieur",     "commentaire_1"],
    "SOUS_CAPOT":       ["commentaire_sous_capot",    "commentaire_2"],
    "SOUS_VEHICULE":    ["commentaire_sous_vehicule",  "commentaire_3"],
    "ENTRETIEN":        ["commentaire_entretien",      "commentaire_4"],
}

# Metadata columns needed to reconstruct the inspection key
METADATA_CANDIDATES: dict[str, list[str]] = {
    "inspection_source_id": ["inspection_source_id"],
    "date_inspection":      ["date_inspection", "DATE_VISITE", "DATE_INSPECTION"],
    "immatriculation":      ["immatriculation", "IMMATRICULATION", "IMMAT"],
}


# ---------------------------------------------------------------------------
# Checkpoint-specific helpers
# ---------------------------------------------------------------------------

def _zone_for_col(col_name: str) -> str | None:
    """Return zone label for a checkpoint column name, or None."""
    cl = col_name.lower()
    for prefix, zone in ZONE_MAP.items():
        if cl.startswith(prefix):
            return zone
    return None


def _make_libelle(col_name: str) -> str:
    """Strip zone prefix and produce a readable French label."""
    cl = col_name.lower()
    for prefix in ZONE_MAP:
        if cl.startswith(prefix):
            raw = col_name[len(prefix):]
            label = re.sub(r"\s+", " ", raw.replace("_", " ")).strip()
            return label[0].upper() + label[1:] if label else label
    label = re.sub(r"\s+", " ", col_name.replace("_", " ")).strip()
    return label[0].upper() + label[1:] if label else label


def _clean_valeur(value: object) -> str | None:
    """Clean a checkpoint cell value; preserve original French wording."""
    if _is_missing(value):
        return None
    s = re.sub(r"\s+", " ", str(value).strip())
    return None if not s or s.upper() in INVALID_TEXT else s


def _clean_comment(value: object) -> str | None:
    """Clean a zone comment; preserve original wording."""
    if _is_missing(value):
        return None
    s = re.sub(r"\s+", " ", str(value).strip())
    return None if not s or s.upper() in INVALID_TEXT else s


def _classify_anomalie(valeur: str | None) -> bool | None:
    """True=anomaly, False=OK, None=unknown/null."""
    if valeur is None:
        return None
    norm = _normalize_checklist_value(valeur)
    if norm is None:
        return None
    if norm in OK_VALUES:
        return False
    if norm in ANOMALY_VALUES or any(sub in norm for sub in ANOMALY_SUBSTRINGS):
        return True
    return None


# ---------------------------------------------------------------------------
# Data reading
# ---------------------------------------------------------------------------

def _read_staging(engine, logger) -> tuple[pd.DataFrame, list[str], list[str]]:
    """
    Read staging.stg_inspection.
    Returns (df, checklist_cols, present_comment_cols).
    """
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'staging' AND table_name = 'stg_inspection'
            ORDER BY ordinal_position
        """)).fetchall()
    all_cols = [r[0] for r in rows]
    lower_to_actual = {c.lower(): c for c in all_cols}

    select_parts: list[str] = []

    # Metadata
    for canonical, candidates in METADATA_CANDIDATES.items():
        actual = next(
            (lower_to_actual[c.lower()] for c in candidates if c.lower() in lower_to_actual),
            None,
        )
        if actual:
            alias = f'"{actual}" AS "{canonical}"' if actual != canonical else f'"{actual}"'
            select_parts.append(alias)
            logger.info(f"  staging meta   {canonical:<24} <- {actual}")
        else:
            logger.warning(f"  staging meta missing: {canonical}")

    # Comment columns — try new naming convention first, then legacy fallback
    present_comment_cols: list[str] = []
    for zone, candidates in _ZONE_COMMENT_CANDIDATES.items():
        canonical = ZONE_TO_COMMENT[zone]
        for candidate in candidates:
            actual = lower_to_actual.get(candidate.lower())
            if actual:
                alias = (
                    f'"{actual}" AS "{canonical}"'
                    if actual.lower() != canonical.lower()
                    else f'"{actual}"'
                )
                select_parts.append(alias)
                present_comment_cols.append(canonical)
                if actual.lower() != canonical.lower():
                    logger.info(f"  comment col {canonical:<28} <- {actual} (legacy name)")
                break
    if present_comment_cols:
        logger.info(f"  comment columns resolved: {present_comment_cols}")
    else:
        logger.warning("  no comment columns found in staging.stg_inspection")

    # Log all sous_le_vehicule_ staging columns BEFORE checkpoint detection
    sv_before = [c for c in all_cols if c.lower().startswith("sous_le_vehicule_")]
    logger.info(
        f"  sous_le_vehicule_ cols in staging before detection ({len(sv_before)}): "
        f"{sv_before}"
    )

    # Checklist columns (dynamic detection)
    checklist_cols = _detect_checklist_columns(all_cols)
    n_critical = sum(1 for c in checklist_cols if _is_critical_col(c))

    # Guard: sous_le_vehicule_ cols present in staging but not in detected list
    sv_detected = [c for c in checklist_cols if c.lower().startswith("sous_le_vehicule_")]
    logger.info(
        f"  sous_le_vehicule_ cols after detection: {len(sv_detected)} "
        f"(expected {len(sv_before)} from staging)"
    )
    if sv_before and not sv_detected:
        raise RuntimeError(
            f"SOUS_VEHICULE checkpoint columns exist in staging "
            f"({sv_before[:3]}...) but were not included in checkpoint_columns. "
            "Check _detect_checklist_columns and _EXCLUDE_CHECKLIST_COL."
        )

    for col in checklist_cols:
        select_parts.append(f'"{col}"')
    logger.info(
        f"  checklist columns: {len(checklist_cols)} detected "
        f"({n_critical} safety-critical)"
    )
    if not checklist_cols:
        logger.warning("  NO checklist columns detected")

    if not select_parts:
        raise RuntimeError("No expected columns found in staging.stg_inspection.")

    with engine.connect() as conn:
        df = pd.read_sql(
            text(f"SELECT {', '.join(select_parts)} FROM {SOURCE_TABLE}"),
            conn,
        )

    # Ensure metadata columns exist even when absent in staging
    for col in METADATA_CANDIDATES:
        if col not in df.columns:
            df[col] = pd.NA
    for col in ALL_COMMENT_COLS:
        if col not in df.columns:
            df[col] = pd.NA

    logger.info(f"  source rows read: {len(df)}")
    return df, checklist_cols, present_comment_cols


def _load_fact_vehicule(engine, logger) -> pd.DataFrame:
    """Load inspection_key and FK columns from dwh.fact_inspection_vehicule."""
    sql = text("""
        SELECT inspection_key, vehicule_sk, date_inspection_sk, immatriculation_norm
        FROM dwh.fact_inspection_vehicule
    """)
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    logger.info(f"  fact_inspection_vehicule: {len(df)} rows loaded")
    return df


def _load_dim_date_keys(engine) -> set[int]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT date_sk FROM dwh.dim_date")).fetchall()
    return {int(r[0]) for r in rows}


# ---------------------------------------------------------------------------
# Quality report writers
# ---------------------------------------------------------------------------

def _write_duplicate_report(df: pd.DataFrame) -> int:
    dup = df[df["inspection_checkpoint_key"].duplicated(keep=False)].copy()
    cols = ["inspection_checkpoint_key", "inspection_key", "checkpoint_code"]
    if dup.empty:
        pd.DataFrame(columns=cols + ["duplicate_count"]).to_csv(
            DUPLICATE_GRAIN_PATH, index=False, encoding="utf-8-sig"
        )
        return 0
    counts = (
        dup.groupby("inspection_checkpoint_key").size()
        .rename("duplicate_count").reset_index()
    )
    report = dup[[c for c in cols if c in dup.columns]].merge(
        counts, on="inspection_checkpoint_key", how="left"
    )
    report.to_csv(DUPLICATE_GRAIN_PATH, index=False, encoding="utf-8-sig")
    return len(report)


def _deduplicate_checkpoint(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if not df["inspection_checkpoint_key"].duplicated().any():
        return df, 0
    ranked = df.copy()
    ranked["_r_val"]  = ranked["valeur_controle"].notna().astype(int)
    ranked["_r_anom"] = ranked["est_anomalie"].eq(True).astype(int)
    ranked["_r_com"]  = ranked["commentaire_zone"].notna().astype(int)
    ranked = ranked.sort_values(
        ["inspection_checkpoint_key", "_r_val", "_r_anom", "_r_com"],
        ascending=[True, False, False, False],
    )
    deduped = ranked.drop_duplicates("inspection_checkpoint_key", keep="first").drop(
        columns=["_r_val", "_r_anom", "_r_com"]
    )
    return deduped, len(df) - len(deduped)


def _write_unmatched_report(unmatched: pd.DataFrame) -> int:
    cols = ["source_immatriculation", "source_date_inspection", "inspection_key", "reason"]
    if unmatched.empty:
        pd.DataFrame(columns=cols).to_csv(UNMATCHED_PATH, index=False, encoding="utf-8-sig")
        return 0
    unmatched[[c for c in cols if c in unmatched.columns]].to_csv(
        UNMATCHED_PATH, index=False, encoding="utf-8-sig"
    )
    return len(unmatched)


def _write_mapping_report(
    df: pd.DataFrame,
    source_info: dict[str, dict],
) -> None:
    """Write per-checkpoint mapping report.

    source_info keys are staging column names (= checkpoint_code after melt).
    Each value is a dict with 'non_null_count' (int) and 'sample_values' (str).
    """
    rows = []
    for code, sub in df.groupby("checkpoint_code", sort=True):
        src = source_info.get(code, {})
        rows.append({
            "source_column_name":             code,
            "checkpoint_code":                code,
            "checkpoint_libelle":             sub["checkpoint_libelle"].iloc[0],
            "zone_controle":                  sub["zone_controle"].iloc[0],
            "source_non_null_count_before_melt": src.get("non_null_count", pd.NA),
            "total_rows":                     len(sub),
            "final_renseigne_count":          int(sub["est_controle_renseigne"].eq(True).sum()),
            "missing_count":                  int(sub["est_controle_renseigne"].eq(False).sum()),
            "anomaly_count":                  int(sub["est_anomalie"].eq(True).sum()),
            "critical_anomaly_count":         int(sub["est_anomalie_critique"].eq(True).sum()),
            "unknown_value_count":            int(sub["est_anomalie"].isna().sum()),
            "sample_values":                  src.get("sample_values", ""),
        })
    pd.DataFrame(rows).to_csv(MAPPING_REPORT_PATH, index=False, encoding="utf-8-sig")


def _write_value_distribution_report(df: pd.DataFrame) -> None:
    dist = (
        df.groupby(
            ["checkpoint_code", "valeur_controle", "est_anomalie", "est_anomalie_critique"],
            dropna=False,
        )
        .size()
        .rename("count_rows")
        .reset_index()
        .sort_values(["checkpoint_code", "count_rows"], ascending=[True, False])
    )
    dist.to_csv(VALUE_DIST_PATH, index=False, encoding="utf-8-sig")


def _write_load_summary(metrics: dict) -> None:
    pd.DataFrame(
        [{"metric": k, "value": v} for k, v in sorted(metrics.items())]
    ).to_csv(LOAD_SUMMARY_PATH, index=False, encoding="utf-8-sig")


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def transform_fact_inspection_checkpoint(
    df_staging: pd.DataFrame,
    checklist_cols: list[str],
    present_comment_cols: list[str],
    df_fact_vehicule: pd.DataFrame,
    dim_date_keys: set[int],
    logger,
) -> tuple[pd.DataFrame, dict]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    n_source = len(df_staging)

    # ── 1. Compute staging inspection key (same logic as load_fact_inspection_vehicule) ──
    immat_norm = df_staging["immatriculation"].map(normalize_immatriculation)
    date_sk_series = (
        df_staging["date_inspection"]
        .map(lambda v: _to_date_sk_detail(v, dim_date_keys)["date_sk"])
        .astype("int64")
    )
    staging_keys = (
        immat_norm.fillna("UNKNOWN").astype(str)
        + "|"
        + date_sk_series.astype(str)
        + "|"
        + df_staging["inspection_source_id"].fillna("0").astype(str).str.strip()
    )
    df_staging = df_staging.copy()
    df_staging["_key"] = staging_keys

    # ── 2. Join to fact_inspection_vehicule ──────────────────────────────────
    fact_lookup = (
        df_fact_vehicule[["inspection_key", "vehicule_sk", "date_inspection_sk", "immatriculation_norm"]]
        .drop_duplicates("inspection_key")
    )
    fact_key_set = set(fact_lookup["inspection_key"])

    matched_mask  = df_staging["_key"].isin(fact_key_set)
    df_unmatched  = df_staging[~matched_mask].copy()
    df_matched    = df_staging[matched_mask].copy()

    # Build unmatched report
    unmatched_report = pd.DataFrame({
        "source_immatriculation": df_unmatched["immatriculation"],
        "source_date_inspection": df_unmatched["date_inspection"].astype(str),
        "inspection_key":         df_unmatched["_key"],
        "reason":                 "No matching inspection_key in dwh.fact_inspection_vehicule",
    })
    n_unmatched = _write_unmatched_report(unmatched_report)
    if n_unmatched:
        logger.warning(f"  {n_unmatched} staging rows not matched in fact_inspection_vehicule")

    # Merge to get vehicule_sk, date_inspection_sk, immatriculation_norm
    df_matched = df_matched.merge(
        fact_lookup,
        left_on="_key",
        right_on="inspection_key",
        how="left",
    ).drop(columns=["_key"])

    n_matched = len(df_matched)
    logger.info(f"  join: {n_matched} matched / {n_unmatched} unmatched of {n_source} staging rows")

    if not checklist_cols or df_matched.empty:
        logger.warning("  No matched rows or no checklist columns — empty checkpoint table")
        df_empty = pd.DataFrame(columns=FINAL_COLS)
        empty_metrics = {
            "source_inspection_rows":             n_source,
            "checkpoint_columns_detected":        len(checklist_cols),
            "expected_checkpoint_rows":           0,
            "final_checkpoint_rows":              0,
            "duplicate_checkpoint_keys_detected": 0,
            "duplicate_checkpoint_keys_resolved": 0,
            "unmatched_inspection_rows":          n_unmatched,
            "rows_with_value":                    0,
            "rows_missing_value":                 0,
            "anomaly_rows":                       0,
            "critical_anomaly_rows":              0,
        }
        _write_load_summary(empty_metrics)
        return df_empty, empty_metrics

    n_expected = n_matched * len(checklist_cols)
    logger.info(f"  expected checkpoint rows: {n_matched} x {len(checklist_cols)} = {n_expected}")

    # ── 3. Precompute per-column metadata (zone, libelle, is_critical) ───────
    col_zone     = {col: _zone_for_col(col)  for col in checklist_cols}
    col_libelle  = {col: _make_libelle(col)  for col in checklist_cols}
    col_critical = {col: _is_critical_col(col) for col in checklist_cols}

    # ── 3b. Pre-melt source diagnostics ──────────────────────────────────────
    # Compute non-null count and sample values per staging checkpoint column
    # BEFORE the melt.  Used for the mapping report and zone validation guard.
    id_cols    = ["inspection_key", "vehicule_sk", "date_inspection_sk", "immatriculation_norm"] + ALL_COMMENT_COLS
    id_present = [c for c in id_cols if c in df_matched.columns]
    val_vars   = [c for c in checklist_cols if c in df_matched.columns]

    source_info: dict[str, dict] = {}
    zone_src_nonnull: dict[str, int] = {z: 0 for z in ZONE_MAP.values()}

    logger.info(f"  --- pre-melt source column diagnostics ({len(val_vars)} cols) ---")
    for col in val_vars:
        non_null = int(df_matched[col].notna().sum())
        raw_samples = df_matched[col].dropna().map(str).value_counts().head(5)
        sample_str  = "; ".join(f"{v}={n}" for v, n in raw_samples.items())
        source_info[col] = {"non_null_count": non_null, "sample_values": sample_str}
        zone = col_zone.get(col)
        if zone:
            zone_src_nonnull[zone] = zone_src_nonnull.get(zone, 0) + non_null
        if non_null == 0:
            logger.debug(f"    {col}: ALL NULL in source")
        else:
            logger.debug(f"    {col}: {non_null} non-null | zone={zone} | {sample_str[:80]}")
    logger.info(
        f"  source non-null totals by zone: "
        + ", ".join(f"{z}={v}" for z, v in sorted(zone_src_nonnull.items()))
    )

    # Guard: SOUS_VEHICULE cols reachable from df_matched but absent from val_vars
    expected_sv_in_df = [
        c for c in df_matched.columns
        if c.lower().startswith("sous_le_vehicule_") and "commentaire" not in c.lower()
    ]
    detected_sv_in_vars = [
        c for c in val_vars if c.lower().startswith("sous_le_vehicule_")
    ]
    logger.info(
        f"  SOUS_VEHICULE guard: {len(expected_sv_in_df)} cols in df_matched, "
        f"{len(detected_sv_in_vars)} cols in val_vars for melt"
    )
    if expected_sv_in_df and not detected_sv_in_vars:
        raise RuntimeError(
            f"SOUS_VEHICULE checkpoint columns exist in df_matched "
            f"({expected_sv_in_df[:3]}) but were not included in val_vars for melt. "
            "Check checklist_cols detection vs df_matched column names."
        )

    # ── 4. Melt wide -> long ─────────────────────────────────────────────────
    df_long = df_matched[id_present + val_vars].melt(
        id_vars=id_present,
        value_vars=val_vars,
        var_name="checkpoint_code",
        value_name="_raw_value",
    )
    logger.info(f"  after melt: {len(df_long)} rows")

    # ── 5. Zone, libelle, cleaned value ─────────────────────────────────────
    df_long["zone_controle"]      = df_long["checkpoint_code"].map(col_zone)
    df_long["checkpoint_libelle"] = df_long["checkpoint_code"].map(col_libelle)
    df_long["valeur_controle"]    = df_long["_raw_value"].map(_clean_valeur)
    df_long.drop(columns=["_raw_value"], inplace=True)

    # ── 6. commentaire_zone (pick the matching zone comment per row) ──────────
    df_long["commentaire_zone"] = pd.NA
    for zone, comment_col in ZONE_TO_COMMENT.items():
        if comment_col in df_long.columns:
            mask = df_long["zone_controle"] == zone
            df_long.loc[mask, "commentaire_zone"] = (
                df_long.loc[mask, comment_col].map(_clean_comment)
            )
    for c in ALL_COMMENT_COLS:
        if c in df_long.columns:
            df_long.drop(columns=[c], inplace=True)

    # ── 7. est_anomalie ──────────────────────────────────────────────────────
    df_long["est_anomalie"] = df_long["valeur_controle"].map(_classify_anomalie).astype("boolean")

    # ── 8. est_anomalie_critique (vectorized) ────────────────────────────────
    is_anomaly_mask = df_long["est_anomalie"].eq(True)

    # Critical from column name (precomputed)
    col_is_crit = df_long["checkpoint_code"].map(col_critical).fillna(False)

    # Critical from valeur_controle
    val_norms   = df_long["valeur_controle"].map(_normalize_checklist_value)
    val_is_crit = val_norms.map(
        lambda n: any(kw in n for kw in CRITICAL_VALUE_SUBSTRINGS) if isinstance(n, str) else False
    )

    # Critical from commentaire_zone
    com_norms   = df_long["commentaire_zone"].map(_normalize_checklist_value)
    com_is_crit = com_norms.map(
        lambda n: any(kw in n for kw in CRITICAL_VALUE_SUBSTRINGS) if isinstance(n, str) else False
    )

    any_crit = col_is_crit | val_is_crit | com_is_crit

    df_long["est_anomalie_critique"] = pd.Series(pd.NA, index=df_long.index, dtype="boolean")
    df_long.loc[is_anomaly_mask & any_crit,  "est_anomalie_critique"] = True
    df_long.loc[is_anomaly_mask & ~any_crit, "est_anomalie_critique"] = False

    # ── 9. est_controle_renseigne ────────────────────────────────────────────
    df_long["est_controle_renseigne"] = df_long["valeur_controle"].notna().astype("boolean")

    # ── 9b. Zone validation guard ────────────────────────────────────────────
    # If a zone had non-null values in source but has 0 renseigne rows after
    # melt, that indicates a silent value-loss bug (e.g. wrong column names).
    zone_out_renseigne = (
        df_long[df_long["est_controle_renseigne"].eq(True)]
        .groupby("zone_controle")
        .size()
        .to_dict()
    )
    for zone in ZONE_MAP.values():
        src_count = zone_src_nonnull.get(zone, 0)
        out_count = zone_out_renseigne.get(zone, 0)
        if src_count > 0 and out_count == 0:
            logger.warning(
                f"  DATA LOSS in zone {zone}: "
                f"{src_count} non-null values in source → 0 renseigne rows after melt. "
                "Check staging column names vs ZONE_MAP prefixes."
            )
        else:
            logger.info(
                f"  zone {zone}: source_nonnull={src_count}, "
                f"renseigne_after_melt={out_count}"
            )

    # ── 10. inspection_checkpoint_key ────────────────────────────────────────
    df_long["inspection_checkpoint_key"] = (
        df_long["inspection_key"].astype(str)
        + "|"
        + df_long["checkpoint_code"].astype(str)
    )

    # ── 11. Duplicate detection and deduplication ────────────────────────────
    n_dup_report  = _write_duplicate_report(df_long)
    df_long, n_dup_resolved = _deduplicate_checkpoint(df_long)

    # ── 12. Metadata ─────────────────────────────────────────────────────────
    df_long["source_system"] = SOURCE_SYSTEM
    df_long["created_at"]    = TODAY

    # ── 13. Quality reports ──────────────────────────────────────────────────
    _write_mapping_report(df_long, source_info)
    _write_value_distribution_report(df_long)

    # ── 14. Sort and assign surrogate key ────────────────────────────────────
    df_long = df_long.sort_values(
        ["immatriculation_norm", "date_inspection_sk", "checkpoint_code"],
        na_position="last",
    ).reset_index(drop=True)
    df_long.insert(0, "fact_inspection_checkpoint_sk", range(1, len(df_long) + 1))

    # ── 15. Select and enforce types ─────────────────────────────────────────
    for col in FINAL_COLS:
        if col not in df_long.columns:
            df_long[col] = pd.NA
    df_final = df_long[FINAL_COLS].copy()

    for col in [c for c in FINAL_COLS if c.endswith("_sk")]:
        df_final[col] = pd.to_numeric(df_final[col], errors="coerce").fillna(0).astype("int64")

    for col in ["est_anomalie", "est_anomalie_critique", "est_controle_renseigne"]:
        df_final[col] = df_final[col].astype("boolean")

    # ── 15b. Final zone guard ────────────────────────────────────────────────
    # If SOUS_VEHICULE had staging cols but is absent from the output, raise.
    zones_in_output = set(df_final["zone_controle"].dropna())
    if detected_sv_in_vars and "SOUS_VEHICULE" not in zones_in_output:
        raise RuntimeError(
            f"SOUS_VEHICULE zone missing from fact_inspection_checkpoint output "
            f"despite {len(detected_sv_in_vars)} sous_le_vehicule_* cols being melted. "
            "Check _zone_for_col() and ZONE_MAP."
        )
    logger.info(f"  zones in output: {sorted(zones_in_output)}")

    metrics = {
        "source_inspection_rows":             n_source,
        "checkpoint_columns_detected":        len(checklist_cols),
        "expected_checkpoint_rows":           n_expected,
        "final_checkpoint_rows":              len(df_final),
        "duplicate_checkpoint_keys_detected": n_dup_report,
        "duplicate_checkpoint_keys_resolved": n_dup_resolved,
        "unmatched_inspection_rows":          n_unmatched,
        "rows_with_value":                    int(df_final["est_controle_renseigne"].eq(True).sum()),
        "rows_missing_value":                 int(df_final["est_controle_renseigne"].eq(False).sum()),
        "anomaly_rows":                       int(df_final["est_anomalie"].eq(True).sum()),
        "critical_anomaly_rows":              int(df_final["est_anomalie_critique"].eq(True).sum()),
    }
    _write_load_summary(metrics)
    return df_final, metrics


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def load_fact_inspection_checkpoint(run_id: str, engine, logger) -> int:
    logger.info(f"[RUN {run_id}] {SOURCE_TABLE} + {FACT_VEH_TABLE} -> dwh.{TABLE_NAME}")
    dwh_utils.create_dwh_schema(engine, logger)

    # Verify prerequisites
    with engine.connect() as conn:
        for schema, table, prereq in [
            ("staging", "stg_inspection",       "prepare_inspection_sa"),
            ("dwh",     "fact_inspection_vehicule", "load_fact_inspection_vehicule"),
        ]:
            exists = conn.execute(text(f"""
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = '{schema}' AND table_name = '{table}'
            """)).fetchone()
            if not exists:
                raise RuntimeError(
                    f"Table {schema}.{table} not found. Run {prereq} first."
                )

    df_staging, checklist_cols, present_comment_cols = _read_staging(engine, logger)
    df_fact_vehicule = _load_fact_vehicule(engine, logger)
    dim_date_keys    = _load_dim_date_keys(engine)

    df_final, metrics = transform_fact_inspection_checkpoint(
        df_staging, checklist_cols, present_comment_cols,
        df_fact_vehicule, dim_date_keys, logger,
    )
    n_rows, elapsed = dwh_utils.write_to_dwh(
        df_final, engine, TABLE_NAME, logger, chunksize=5000
    )

    logger.info("=" * 72)
    logger.info(f"  source inspection rows              : {metrics['source_inspection_rows']}")
    logger.info(f"  checkpoint columns detected         : {metrics['checkpoint_columns_detected']}")
    logger.info(f"  expected checkpoint rows            : {metrics['expected_checkpoint_rows']}")
    logger.info(f"  final checkpoint rows loaded        : {n_rows}")
    logger.info(f"  duplicate checkpoint keys detected  : {metrics['duplicate_checkpoint_keys_detected']}")
    logger.info(f"  duplicate checkpoint keys resolved  : {metrics['duplicate_checkpoint_keys_resolved']}")
    logger.info(f"  unmatched inspection rows           : {metrics['unmatched_inspection_rows']}")
    logger.info(f"  rows with value                     : {metrics['rows_with_value']}")
    logger.info(f"  rows missing value                  : {metrics['rows_missing_value']}")
    logger.info(f"  anomaly rows                        : {metrics['anomaly_rows']}")
    logger.info(f"  critical anomaly rows               : {metrics['critical_anomaly_rows']}")
    logger.info(f"  duplicate grain report              : {DUPLICATE_GRAIN_PATH}")
    logger.info(f"  unmatched inspections report        : {UNMATCHED_PATH}")
    logger.info(f"  checkpoint mapping report           : {MAPPING_REPORT_PATH}")
    logger.info(f"  value distribution report           : {VALUE_DIST_PATH}")
    logger.info(f"  load summary report                 : {LOAD_SUMMARY_PATH}")
    logger.info(f"  load duration                       : {elapsed:.1f}s")
    logger.info("=" * 72)
    logger.info("Validation SQL queries:")
    logger.info("""
SELECT COUNT(*) AS total_rows
FROM dwh.fact_inspection_checkpoint;

SELECT inspection_checkpoint_key, COUNT(*) AS nb
FROM dwh.fact_inspection_checkpoint
GROUP BY inspection_checkpoint_key
HAVING COUNT(*) > 1;

SELECT
    COUNT(DISTINCT inspection_key) AS inspections_with_checkpoints,
    COUNT(DISTINCT checkpoint_code) AS checkpoint_count
FROM dwh.fact_inspection_checkpoint;

SELECT
    zone_controle,
    COUNT(*) AS total_rows,
    COUNT(*) FILTER (WHERE est_controle_renseigne = true) AS renseigne_rows,
    COUNT(*) FILTER (WHERE est_anomalie = true) AS anomaly_rows,
    COUNT(*) FILTER (WHERE est_anomalie_critique = true) AS critical_rows
FROM dwh.fact_inspection_checkpoint
GROUP BY zone_controle
ORDER BY zone_controle;

SELECT
    checkpoint_code,
    checkpoint_libelle,
    COUNT(*) FILTER (WHERE est_anomalie = true) AS anomaly_rows,
    COUNT(*) FILTER (WHERE est_anomalie_critique = true) AS critical_rows
FROM dwh.fact_inspection_checkpoint
GROUP BY checkpoint_code, checkpoint_libelle
ORDER BY anomaly_rows DESC, critical_rows DESC
LIMIT 20;

SELECT
    est_anomalie,
    est_anomalie_critique,
    COUNT(*) AS nb
FROM dwh.fact_inspection_checkpoint
GROUP BY est_anomalie, est_anomalie_critique
ORDER BY nb DESC;
""")
    return n_rows


if __name__ == "__main__":
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logger = dwh_utils.setup_logging(run_id, log_name="load_fact_inspection_checkpoint")
    engine = dwh_utils.build_engine(logger)
    n = load_fact_inspection_checkpoint(run_id, engine, logger)
    logger.info(f"Done: {n} rows -> dwh.{TABLE_NAME}")
