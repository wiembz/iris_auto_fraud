"""
etl/mart/compute_vhs.py
========================
Computes the Vehicle Health Score V1 (VHS_BALANCED_V1).

Sources:
  dwh.fact_inspection_vehicule   — one row per inspection
  dwh.fact_inspection_checkpoint — observed checkpoint values
  mart.dim_checkpoint            — scoring reference (criticality, penalties)

Outputs:
  mart.fact_vhs_score            — one score row per inspection per run
  mart.fact_vhs_penalty_detail   — one row per scored anomaly per inspection per run
  data/quality_reports/vhs/vhs_business_rule_audit.csv

Design:
  - Fully explainable; no ML, no black box.
  - Historized by (profile_name, rule_version, run_id).
  - Idempotent: deletes existing rows for the same run_id before inserting.
  - UNKNOWN_REVIEW checkpoints (is_vhs_scored=false) are never scored.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dwh"))
import dwh_utils

BASE_DIR      = Path(__file__).resolve().parent.parent.parent
VHS_REPORT_DIR = BASE_DIR / "data" / "quality_reports" / "vhs"
VHS_AUDIT_PATH = VHS_REPORT_DIR / "vhs_business_rule_audit.csv"

PROFILE_NAME = "VHS_BALANCED_V1"
RULE_VERSION  = "VHS_BALANCED_V1"
TODAY = datetime.now(timezone.utc).replace(tzinfo=None)

# Repair phrase — two DB variants: straight apostrophe vs Unicode right-quote (U+2019)
_REPAIR_SUBSTRINGS = [
    "Réparation effectuée suite à l'accord client",       # ASCII apostrophe
    "Réparation effectuée suite à l’accord client",  # Unicode right single quote
]
_OK_VALUES = frozenset({"Contrôle OK", "Bon", "OUI"})

# Columns from mart.dim_checkpoint to merge (avoids column name conflicts)
_DIM_COLS = [
    "checkpoint_code",
    "tier",
    "is_vital",
    "is_important",
    "is_critical_functional",
    "is_immobilizing",
    "penalty_worn",
    "penalty_broken",
]

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

DDL_CREATE_SCHEMA = "CREATE SCHEMA IF NOT EXISTS mart;"

DDL_FACT_VHS_SCORE = """
CREATE TABLE IF NOT EXISTS mart.fact_vhs_score (
    vhs_score_sk           BIGSERIAL PRIMARY KEY,
    inspection_key         TEXT             NOT NULL,
    vehicule_sk            BIGINT,
    date_inspection_sk     BIGINT,
    immatriculation_norm   TEXT,
    kilometrage            DOUBLE PRECISION,
    vhs_raw_score          NUMERIC(6,2),
    kilometrage_penalty    NUMERIC(6,2),
    vhs_before_cap         NUMERIC(6,2),
    vhs_final_score        NUMERIC(6,2),
    safety_score           NUMERIC(6,2),
    functional_score       NUMERIC(6,2),
    cosmetic_score         NUMERIC(6,2),
    safety_grade           TEXT,
    decision               TEXT,
    is_drivable            BOOLEAN,
    hard_cap_applied       BOOLEAN,
    hard_cap_type          TEXT,
    nb_penalties_applied   INTEGER,
    nb_anomalies_total     BIGINT,
    nb_anomalies_critiques BIGINT,
    profile_name           TEXT             NOT NULL,
    rule_version           TEXT             NOT NULL,
    run_id                 TEXT             NOT NULL,
    calculated_at          TIMESTAMP        DEFAULT NOW(),
    source_system          TEXT             DEFAULT 'IRIS_VHS',
    created_at             TIMESTAMP        DEFAULT NOW(),
    CONSTRAINT uq_vhs_score UNIQUE (inspection_key, profile_name, rule_version, run_id)
);
"""

DDL_FACT_VHS_PENALTY_DETAIL = """
CREATE TABLE IF NOT EXISTS mart.fact_vhs_penalty_detail (
    penalty_detail_sk      BIGSERIAL PRIMARY KEY,
    inspection_key         TEXT             NOT NULL,
    vehicule_sk            BIGINT,
    date_inspection_sk     BIGINT,
    immatriculation_norm   TEXT,
    checkpoint_code        TEXT             NOT NULL,
    checkpoint_libelle     TEXT,
    zone_controle          TEXT,
    observed_value         TEXT,
    observed_status        TEXT,
    penalty_applied        NUMERIC(6,2)     NOT NULL DEFAULT 0,
    penalty_reason         TEXT,
    tier                   TEXT,
    is_vital               BOOLEAN,
    is_important           BOOLEAN,
    is_critical_functional BOOLEAN,
    is_immobilizing        BOOLEAN,
    is_hard_cap_trigger    BOOLEAN          DEFAULT FALSE,
    hard_cap_type          TEXT,
    profile_name           TEXT             NOT NULL,
    rule_version           TEXT             NOT NULL,
    run_id                 TEXT             NOT NULL,
    created_at             TIMESTAMP        DEFAULT NOW(),
    CONSTRAINT uq_penalty_detail UNIQUE (inspection_key, checkpoint_code, profile_name, rule_version, run_id)
);
"""

VALIDATION_SQL = """
SELECT COUNT(*) FROM mart.fact_vhs_score
WHERE profile_name = 'VHS_BALANCED_V1'
  AND rule_version = 'VHS_BALANCED_V1';

SELECT decision, COUNT(*)
FROM mart.fact_vhs_score
WHERE profile_name = 'VHS_BALANCED_V1'
  AND rule_version = 'VHS_BALANCED_V1'
GROUP BY decision
ORDER BY decision;

SELECT safety_grade, COUNT(*)
FROM mart.fact_vhs_score
WHERE profile_name = 'VHS_BALANCED_V1'
  AND rule_version = 'VHS_BALANCED_V1'
GROUP BY safety_grade
ORDER BY safety_grade;

SELECT hard_cap_type, COUNT(*)
FROM mart.fact_vhs_score
WHERE profile_name = 'VHS_BALANCED_V1'
  AND rule_version = 'VHS_BALANCED_V1'
  AND hard_cap_applied = true
GROUP BY hard_cap_type
ORDER BY hard_cap_type;

SELECT checkpoint_code, checkpoint_libelle, SUM(penalty_applied) AS total_penalty, COUNT(*) AS nb
FROM mart.fact_vhs_penalty_detail
WHERE profile_name = 'VHS_BALANCED_V1'
  AND rule_version = 'VHS_BALANCED_V1'
GROUP BY checkpoint_code, checkpoint_libelle
ORDER BY total_penalty DESC
LIMIT 20;

SELECT *
FROM mart.fact_vhs_score
WHERE decision IN ('CRITIQUE', 'IMMOBILISE')
ORDER BY vhs_final_score ASC
LIMIT 20;
"""

# ---------------------------------------------------------------------------
# Pure functions — scoring rules
# ---------------------------------------------------------------------------

def _normalize_status_vectorized(df: pd.DataFrame) -> pd.Series:
    """
    Vectorized observed_status normalization.
    Priority (highest overrides lower):
      1. est_controle_renseigne = false → UNKNOWN
      2. valeur_controle contains repair substring → REPAIRED
      3. est_anomalie_critique = true → BROKEN
      4. est_anomalie = true → WORN
      5. valeur_controle in OK_VALUES → OK
      6. default → UNKNOWN
    """
    renseigne = df["est_controle_renseigne"].fillna(False).astype(bool)
    critique  = df["est_anomalie_critique"].fillna(False).astype(bool)
    anomalie  = df["est_anomalie"].fillna(False).astype(bool)
    valeur    = df["valeur_controle"].fillna("").astype(str)

    status = pd.array(["UNKNOWN"] * len(df), dtype=object)

    # 5. OK values (lowest priority for renseigne rows)
    status[renseigne.values & valeur.isin(_OK_VALUES).values] = "OK"

    # 4. anomalie → WORN (overrides OK)
    status[renseigne.values & anomalie.values] = "WORN"

    # 3. anomalie critique → BROKEN (overrides WORN)
    status[renseigne.values & critique.values] = "BROKEN"

    # 2. repair phrase → REPAIRED (overrides BROKEN/WORN — repair was performed)
    mask_repair = pd.Series(False, index=df.index)
    for phrase in _REPAIR_SUBSTRINGS:
        mask_repair = mask_repair | valeur.str.contains(phrase, regex=False, na=False)
    status[renseigne.values & mask_repair.values] = "REPAIRED"

    # 1. not renseigne → UNKNOWN (overrides everything — evaluation not performed)
    status[~renseigne.values] = "UNKNOWN"

    return pd.Series(status, index=df.index, name="observed_status")


def _km_penalty(km) -> float:
    if km is None or (isinstance(km, float) and np.isnan(km)) or km <= 0:
        return 1.0
    km = float(km)
    if km >= 350_000:
        return 6.0
    if km >= 250_000:
        return 4.0
    if km >= 180_000:
        return 2.5
    if km >= 120_000:
        return 1.0
    return 0.0


def _state_value(status: str) -> float | None:
    """Return numeric state for subscoring, None for UNKNOWN/REPAIRED."""
    return {"OK": 1.0, "WORN": 0.5, "BROKEN": 0.0}.get(status)


def _compute_grade(t1_vital_broken: int, t1_important_broken: int, t1_worn: int) -> str:
    if t1_vital_broken >= 1 or t1_important_broken >= 3:
        return "D"
    if t1_important_broken >= 1 or t1_worn >= 4:
        return "C"
    if t1_worn >= 1:
        return "B"
    return "A"


def _compute_decision(grade: str, drivable: bool, has_cf: bool, vhs_bc: float) -> str:
    if grade == "D":
        return "CRITIQUE"
    if not drivable:
        return "IMMOBILISE"
    if grade == "C" or has_cf or vhs_bc < 70.0:
        return "DEGRADE"
    return "OK"


def _compute_cap(grade: str, drivable: bool, has_cf: bool) -> tuple[float | None, str | None]:
    """Return (cap_value, cap_type) or (None, None) when no cap applies."""
    if grade == "D":
        return 40.0, "GRADE_D"
    if not drivable:
        return 50.0, "IMMOBILIZED"
    if grade == "C":
        return 65.0, "GRADE_C"
    if has_cf:
        return 65.0, "CRITICAL_FUNCTIONAL"
    return None, None


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def _process_all(
    df_veh: pd.DataFrame,
    df_cp_raw: pd.DataFrame,
    df_dim: pd.DataFrame,
    run_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns (df_scores, df_penalty) ready for DB insert.
    """
    # Join source checkpoints with scored dim_checkpoint entries only
    df_cp = df_cp_raw.merge(df_dim[_DIM_COLS], on="checkpoint_code", how="inner")

    # Convert penalty columns to float (PostgreSQL NUMERIC → Decimal → float)
    df_cp["penalty_worn"]   = df_cp["penalty_worn"].astype(float)
    df_cp["penalty_broken"] = df_cp["penalty_broken"].astype(float)

    # Normalize observed status
    df_cp["observed_status"] = _normalize_status_vectorized(df_cp)

    # Penalty per checkpoint row
    status = df_cp["observed_status"]
    df_cp["penalty_applied"] = np.where(
        status == "WORN",   df_cp["penalty_worn"],
        np.where(
            status == "BROKEN", df_cp["penalty_broken"],
            0.0
        )
    )

    # State value for subscores (NaN = excluded from average)
    df_cp["state_value"] = df_cp["observed_status"].map(
        {"OK": 1.0, "WORN": 0.5, "BROKEN": 0.0}
    )

    all_keys = df_veh["inspection_key"].values

    # ── Aggregations ────────────────────────────────────────────────────────

    total_pen = (
        df_cp.groupby("inspection_key")["penalty_applied"].sum()
        .reindex(all_keys, fill_value=0.0)
    )

    # Subscores — reindex without fill_value so inspections without T1/T2/T3 data get NaN
    df_t1 = df_cp[df_cp["tier"].isin(["T1_VITAL", "T1_IMPORTANT"])]
    df_t2 = df_cp[df_cp["tier"].isin(["T2_CRITICAL", "T2_NORMAL"])]
    df_t3 = df_cp[df_cp["tier"] == "T3_COSMETIC"]

    safety_agg    = df_t1.groupby("inspection_key")["state_value"].mean() * 100
    functional_agg = df_t2.groupby("inspection_key")["state_value"].mean() * 100
    cosmetic_agg  = df_t3.groupby("inspection_key")["state_value"].mean() * 100

    # Grade metrics
    t1_vital_broken = (
        df_cp[(df_cp["tier"] == "T1_VITAL") & (df_cp["observed_status"] == "BROKEN")]
        .groupby("inspection_key").size()
        .reindex(all_keys, fill_value=0)
    )
    t1_important_broken = (
        df_cp[(df_cp["tier"] == "T1_IMPORTANT") & (df_cp["observed_status"] == "BROKEN")]
        .groupby("inspection_key").size()
        .reindex(all_keys, fill_value=0)
    )
    t1_worn_count = (
        df_cp[
            df_cp["tier"].isin(["T1_VITAL", "T1_IMPORTANT"]) &
            (df_cp["observed_status"] == "WORN")
        ]
        .groupby("inspection_key").size()
        .reindex(all_keys, fill_value=0)
    )

    # Drivability: any is_immobilizing BROKEN?
    immo_broken_count = (
        df_cp[df_cp["is_immobilizing"].astype(bool) & (df_cp["observed_status"] == "BROKEN")]
        .groupby("inspection_key").size()
        .reindex(all_keys, fill_value=0)
    )

    # Critical functional BROKEN
    cf_broken_count = (
        df_cp[df_cp["is_critical_functional"].astype(bool) & (df_cp["observed_status"] == "BROKEN")]
        .groupby("inspection_key").size()
        .reindex(all_keys, fill_value=0)
    )

    # Count of penalty rows (rows that contributed a non-zero penalty)
    nb_penalties = (
        df_cp[df_cp["penalty_applied"] > 0]
        .groupby("inspection_key").size()
        .reindex(all_keys, fill_value=0)
    )

    # ── Build one score row per inspection ────────────────────────────────

    score_rows = []
    for _, vrow in df_veh.iterrows():
        key = vrow["inspection_key"]

        total_p  = float(total_pen[key])
        vhs_raw  = round(max(0.0, 100.0 - total_p), 2)
        km_p     = round(_km_penalty(vrow.get("kilometrage")), 2)
        vhs_bc   = round(max(0.0, vhs_raw - km_p), 2)

        vital_b   = int(t1_vital_broken[key])
        import_b  = int(t1_important_broken[key])
        t1_w      = int(t1_worn_count[key])
        grade     = _compute_grade(vital_b, import_b, t1_w)
        drivable  = immo_broken_count[key] == 0
        has_cf    = cf_broken_count[key] > 0

        decision        = _compute_decision(grade, drivable, has_cf, vhs_bc)
        cap_val, cap_tp = _compute_cap(grade, drivable, has_cf)

        vhs_final = round(min(vhs_bc, cap_val), 2) if cap_val is not None else vhs_bc
        hard_cap_applied = (cap_val is not None) and (vhs_final < vhs_bc)

        ss = safety_agg.get(key)
        fs = functional_agg.get(key)
        cs = cosmetic_agg.get(key)

        score_rows.append({
            "inspection_key":        key,
            "vehicule_sk":           int(vrow["vehicule_sk"]) if pd.notna(vrow.get("vehicule_sk")) else None,
            "date_inspection_sk":    int(vrow["date_inspection_sk"]) if pd.notna(vrow.get("date_inspection_sk")) else None,
            "immatriculation_norm":  vrow.get("immatriculation_norm"),
            "kilometrage":           float(vrow["kilometrage"]) if pd.notna(vrow.get("kilometrage")) else None,
            "vhs_raw_score":         vhs_raw,
            "kilometrage_penalty":   km_p,
            "vhs_before_cap":        vhs_bc,
            "vhs_final_score":       vhs_final,
            "safety_score":          round(float(ss), 2) if pd.notna(ss) else None,
            "functional_score":      round(float(fs), 2) if pd.notna(fs) else None,
            "cosmetic_score":        round(float(cs), 2) if pd.notna(cs) else None,
            "safety_grade":          grade,
            "decision":              decision,
            "is_drivable":           bool(drivable),
            "hard_cap_applied":      bool(hard_cap_applied),
            "hard_cap_type":         cap_tp,
            "nb_penalties_applied":  int(nb_penalties[key]),
            "nb_anomalies_total":    int(vrow["nb_anomalies_total"]) if pd.notna(vrow.get("nb_anomalies_total")) else 0,
            "nb_anomalies_critiques": int(vrow["nb_anomalies_critiques"]) if pd.notna(vrow.get("nb_anomalies_critiques")) else 0,
            "profile_name":          PROFILE_NAME,
            "rule_version":          RULE_VERSION,
            "run_id":                run_id,
            "calculated_at":         TODAY,
            "source_system":         "IRIS_VHS",
            "created_at":            TODAY,
        })

    df_scores = pd.DataFrame(score_rows)

    # ── Build penalty detail rows ─────────────────────────────────────────
    # Include WORN, BROKEN, REPAIRED (for traceability); exclude OK and UNKNOWN
    df_det = df_cp[
        df_cp["observed_status"].isin(["WORN", "BROKEN", "REPAIRED"])
    ].copy()

    df_det["penalty_reason"] = df_det["observed_status"].map({
        "WORN":     "Worn or non-critical anomaly. Penalty from dim_checkpoint.penalty_worn.",
        "BROKEN":   "Broken or critical anomaly. Penalty from dim_checkpoint.penalty_broken.",
        "REPAIRED": "Repair performed after client approval. Kept for traceability without VHS penalty in V1.",
    })

    # Hard-cap trigger flags
    # Apply in reverse priority order so higher priority overwrites lower priority.
    df_det["is_hard_cap_trigger"] = False
    df_det["hard_cap_type"]       = None

    def _mark_trigger(mask: pd.Series, cap_type: str) -> None:
        df_det.loc[mask, "is_hard_cap_trigger"] = True
        df_det.loc[mask, "hard_cap_type"]        = cap_type

    # 4. CRITICAL_FUNCTIONAL (lowest priority — will be overwritten by higher caps)
    cf_inspections = df_scores.loc[df_scores["hard_cap_type"] == "CRITICAL_FUNCTIONAL", "inspection_key"]
    if len(cf_inspections):
        _mark_trigger(
            df_det["inspection_key"].isin(cf_inspections) &
            df_det["is_critical_functional"].astype(bool) &
            (df_det["observed_status"] == "BROKEN"),
            "CRITICAL_FUNCTIONAL",
        )

    # 3. GRADE_C
    # For grade C inspections, mark T1_IMPORTANT BROKEN rows
    # and, if t1_worn >= 4, also mark all T1 WORN rows
    grade_c_keys = df_scores.loc[df_scores["safety_grade"] == "C", "inspection_key"]
    if len(grade_c_keys):
        c_keys_arr = grade_c_keys.values
        # T1_IMPORTANT BROKEN
        _mark_trigger(
            df_det["inspection_key"].isin(c_keys_arr) &
            (df_det["tier"] == "T1_IMPORTANT") &
            (df_det["observed_status"] == "BROKEN"),
            "GRADE_C",
        )
        # T1 WORN rows when the worn count triggered grade C (t1_worn >= 4)
        high_worn_mask = t1_worn_count[c_keys_arr].values >= 4
        high_worn_keys = c_keys_arr[high_worn_mask]
        if len(high_worn_keys):
            _mark_trigger(
                df_det["inspection_key"].isin(high_worn_keys) &
                df_det["tier"].isin(["T1_VITAL", "T1_IMPORTANT"]) &
                (df_det["observed_status"] == "WORN"),
                "GRADE_C",
            )

    # 2. IMMOBILIZED
    immo_inspections = df_scores.loc[~df_scores["is_drivable"], "inspection_key"]
    if len(immo_inspections):
        _mark_trigger(
            df_det["inspection_key"].isin(immo_inspections) &
            df_det["is_immobilizing"].astype(bool) &
            (df_det["observed_status"] == "BROKEN"),
            "IMMOBILIZED",
        )

    # 1. GRADE_D (highest priority — overwrites all)
    grade_d_keys = df_scores.loc[df_scores["safety_grade"] == "D", "inspection_key"]
    if len(grade_d_keys):
        _mark_trigger(
            df_det["inspection_key"].isin(grade_d_keys) &
            (df_det["tier"] == "T1_VITAL") &
            (df_det["observed_status"] == "BROKEN"),
            "GRADE_D",
        )

    # Finalize penalty detail DataFrame
    df_det["profile_name"] = PROFILE_NAME
    df_det["rule_version"] = RULE_VERSION
    df_det["run_id"]       = run_id
    df_det["created_at"]   = TODAY

    # Rename valeur_controle → observed_value
    df_det = df_det.rename(columns={"valeur_controle": "observed_value"})

    _penalty_cols = [
        "inspection_key", "vehicule_sk", "date_inspection_sk", "immatriculation_norm",
        "checkpoint_code", "checkpoint_libelle", "zone_controle",
        "observed_value", "observed_status", "penalty_applied", "penalty_reason",
        "tier", "is_vital", "is_important", "is_critical_functional", "is_immobilizing",
        "is_hard_cap_trigger", "hard_cap_type",
        "profile_name", "rule_version", "run_id", "created_at",
    ]
    df_penalty = df_det[[c for c in _penalty_cols if c in df_det.columns]].copy()

    return df_scores, df_penalty


# ---------------------------------------------------------------------------
# Business rule audit
# ---------------------------------------------------------------------------

def _run_audit(
    df_scores: pd.DataFrame,
    df_penalty: pd.DataFrame,
    run_id: str,
) -> pd.DataFrame:
    """Run 7 business rule checks. Returns DataFrame of issues (empty = all pass)."""
    issues: list[dict] = []

    def _add(test: str, key: str, desc: str, severity: str) -> None:
        issues.append({
            "test_name":         test,
            "inspection_key":    key,
            "issue_description": desc,
            "severity":          severity,
            "profile_name":      PROFILE_NAME,
            "rule_version":      RULE_VERSION,
            "run_id":            run_id,
        })

    penalty_by_key = df_penalty.set_index("inspection_key") if len(df_penalty) else pd.DataFrame()

    for _, row in df_scores.iterrows():
        key      = row["inspection_key"]
        decision = row["decision"]
        grade    = row["safety_grade"]
        drivable = row["is_drivable"]
        det = df_penalty[df_penalty["inspection_key"] == key] if len(df_penalty) else pd.DataFrame()

        # Test 1: T1_VITAL BROKEN → must not be OK
        has_t1_vital_broken = (
            len(det) > 0 and
            any((det["tier"] == "T1_VITAL") & (det["observed_status"] == "BROKEN"))
        )
        if has_t1_vital_broken and decision == "OK":
            _add(
                "T1_VITAL_BROKEN_NOT_OK", key,
                "Vehicle has T1_VITAL BROKEN but decision is OK",
                "CRITICAL",
            )

        # Test 2: immobilizing BROKEN → must not be OK
        has_immo_broken = (
            len(det) > 0 and
            any(det["is_immobilizing"].astype(bool) & (det["observed_status"] == "BROKEN"))
        )
        if has_immo_broken and decision == "OK":
            _add(
                "IMMOBILIZING_BROKEN_NOT_OK", key,
                "Vehicle has immobilizing BROKEN but decision is OK",
                "CRITICAL",
            )

        # Test 3: only T3_COSMETIC penalties → must not be CRITIQUE
        all_tiers = set(det["tier"].unique()) if len(det) > 0 else set()
        only_cosmetic = all_tiers.issubset({"T3_COSMETIC"}) and len(all_tiers) > 0
        if only_cosmetic and decision == "CRITIQUE":
            _add(
                "COSMETIC_ONLY_NOT_CRITIQUE", key,
                "Vehicle has only T3_COSMETIC penalties but decision is CRITIQUE",
                "HIGH",
            )

        # Test 4: kilometrage alone should not make a vehicle CRITIQUE
        no_checkpoint_penalties = row["nb_penalties_applied"] == 0
        if no_checkpoint_penalties and decision == "CRITIQUE":
            _add(
                "KM_ALONE_NOT_CRITIQUE", key,
                "Vehicle has no checkpoint penalties but decision is CRITIQUE",
                "HIGH",
            )

        # Test 5: hard_cap_applied = true must have non-null hard_cap_type
        if row["hard_cap_applied"] and (row["hard_cap_type"] is None or pd.isna(row["hard_cap_type"])):
            _add(
                "HARD_CAP_TYPE_MISSING", key,
                "hard_cap_applied=true but hard_cap_type is null",
                "CRITICAL",
            )

        # Test 6: CRITIQUE decision must have at least one explanation row
        if decision == "CRITIQUE" and len(det) == 0:
            _add(
                "CRITIQUE_NEEDS_EXPLANATION", key,
                "CRITIQUE decision has no rows in fact_vhs_penalty_detail",
                "HIGH",
            )

    # Test 7: UNKNOWN_REVIEW checkpoints must not contribute penalties
    # (guaranteed by inner join with is_vhs_scored=true, but verify)
    if len(df_penalty) > 0 and "tier" in df_penalty.columns:
        unknown_with_penalty = df_penalty[
            (df_penalty["tier"] == "UNKNOWN_REVIEW") & (df_penalty["penalty_applied"] > 0)
        ]
        for _, prow in unknown_with_penalty.iterrows():
            _add(
                "UNKNOWN_REVIEW_NO_PENALTY", prow["inspection_key"],
                f"UNKNOWN_REVIEW checkpoint {prow['checkpoint_code']} has penalty > 0",
                "CRITICAL",
            )

    return pd.DataFrame(issues) if issues else pd.DataFrame(columns=[
        "test_name", "inspection_key", "issue_description",
        "severity", "profile_name", "rule_version", "run_id",
    ])


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def compute_vhs():
    logger = dwh_utils.setup_logging("compute_vhs")
    run_id = f"VHS_BALANCED_V1_{TODAY.strftime('%Y%m%d_%H%M%S')}"

    logger.info("=" * 65)
    logger.info(f"[RUN] {run_id}")
    logger.info(f"      profile={PROFILE_NAME}  rule={RULE_VERSION}")
    logger.info("=" * 65)

    engine = dwh_utils.build_engine(logger)

    # ------------------------------------------------------------------
    # 1. DDL
    # ------------------------------------------------------------------
    with engine.begin() as conn:
        conn.execute(text(DDL_CREATE_SCHEMA))
        conn.execute(text(DDL_FACT_VHS_SCORE))
        conn.execute(text(DDL_FACT_VHS_PENALTY_DETAIL))
    logger.info("  mart.fact_vhs_score: OK (CREATE IF NOT EXISTS)")
    logger.info("  mart.fact_vhs_penalty_detail: OK (CREATE IF NOT EXISTS)")

    # ------------------------------------------------------------------
    # 2. Load source data
    # ------------------------------------------------------------------
    with engine.connect() as conn:
        df_veh = pd.read_sql(text("SELECT * FROM dwh.fact_inspection_vehicule"), conn)
        df_cp_raw = pd.read_sql(text("SELECT * FROM dwh.fact_inspection_checkpoint"), conn)
        df_dim = pd.read_sql(
            text("SELECT * FROM mart.dim_checkpoint WHERE is_vhs_scored = true"),
            conn,
        )

    logger.info(f"  inspections loaded           : {len(df_veh)}")
    logger.info(f"  checkpoint observations      : {len(df_cp_raw)}")
    logger.info(f"  scored dim_checkpoint rows   : {len(df_dim)}")

    # ------------------------------------------------------------------
    # 3. Compute
    # ------------------------------------------------------------------
    df_scores, df_penalty = _process_all(df_veh, df_cp_raw, df_dim, run_id)
    logger.info(f"  VHS scores computed          : {len(df_scores)}")
    logger.info(f"  penalty detail rows          : {len(df_penalty)}")

    # ------------------------------------------------------------------
    # 4. Delete existing rows for this run_id (idempotency)
    # ------------------------------------------------------------------
    with engine.begin() as conn:
        conn.execute(text("""
            DELETE FROM mart.fact_vhs_score
            WHERE profile_name = :p AND rule_version = :v AND run_id = :r
        """), {"p": PROFILE_NAME, "v": RULE_VERSION, "r": run_id})
        conn.execute(text("""
            DELETE FROM mart.fact_vhs_penalty_detail
            WHERE profile_name = :p AND rule_version = :v AND run_id = :r
        """), {"p": PROFILE_NAME, "v": RULE_VERSION, "r": run_id})

    # ------------------------------------------------------------------
    # 5. Insert scores
    # ------------------------------------------------------------------
    with engine.begin() as conn:
        df_scores.to_sql(
            "fact_vhs_score", conn, schema="mart",
            if_exists="append", index=False, chunksize=500, method="multi",
        )
    logger.info(f"  inserted -> mart.fact_vhs_score : {len(df_scores)} rows")

    # ------------------------------------------------------------------
    # 6. Insert penalty details
    # ------------------------------------------------------------------
    if len(df_penalty) > 0:
        with engine.begin() as conn:
            df_penalty.to_sql(
                "fact_vhs_penalty_detail", conn, schema="mart",
                if_exists="append", index=False, chunksize=500, method="multi",
            )
    logger.info(f"  inserted -> mart.fact_vhs_penalty_detail : {len(df_penalty)} rows")

    # ------------------------------------------------------------------
    # 7. Business rule audit
    # ------------------------------------------------------------------
    df_audit = _run_audit(df_scores, df_penalty, run_id)
    VHS_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    df_audit.to_csv(VHS_AUDIT_PATH, index=False, encoding="utf-8-sig")
    logger.info(f"  business rule audit issues   : {len(df_audit)}")
    logger.info(f"  audit report                 : {VHS_AUDIT_PATH}")

    # ------------------------------------------------------------------
    # 8. Summary metrics
    # ------------------------------------------------------------------
    decision_counts   = df_scores["decision"].value_counts().sort_index().to_dict()
    grade_counts      = df_scores["safety_grade"].value_counts().sort_index().to_dict()
    cap_counts        = df_scores[df_scores["hard_cap_applied"]]["hard_cap_type"].value_counts().sort_index().to_dict()
    vhs_final         = df_scores["vhs_final_score"]

    logger.info("=" * 65)
    logger.info(f"  total inspections scored     : {len(df_scores)}")
    logger.info(f"  total penalty detail rows    : {len(df_penalty)}")
    logger.info("  Decision distribution:")
    for k, v in sorted(decision_counts.items()):
        logger.info(f"    {k:<15}: {v}")
    logger.info("  Safety grade distribution:")
    for k, v in sorted(grade_counts.items()):
        logger.info(f"    {k:<5}: {v}")
    logger.info("  Hard cap type distribution:")
    for k, v in sorted(cap_counts.items()):
        logger.info(f"    {k:<25}: {v}")
    logger.info(f"  vhs_final_score avg          : {vhs_final.mean():.2f}")
    logger.info(f"  vhs_final_score min          : {vhs_final.min():.2f}")
    logger.info(f"  vhs_final_score max          : {vhs_final.max():.2f}")
    logger.info(f"  audit issues                 : {len(df_audit)}")
    logger.info(f"  run_id                       : {run_id}")
    logger.info("=" * 65)

    # Validation SQL
    logger.info("Validation SQL queries:")
    logger.info(VALIDATION_SQL)

    # ------------------------------------------------------------------
    # 9. Print summary
    # ------------------------------------------------------------------
    print("=" * 65)
    print(f"  run_id                  : {run_id}")
    print(f"  inspections scored      : {len(df_scores)}")
    print(f"  penalty detail rows     : {len(df_penalty)}")
    print()
    print("  Decision distribution:")
    for k in ["OK", "DEGRADE", "IMMOBILISE", "CRITIQUE"]:
        print(f"    {k:<15}: {decision_counts.get(k, 0)}")
    print()
    print("  Safety grade distribution:")
    for k in ["A", "B", "C", "D"]:
        print(f"    Grade {k}: {grade_counts.get(k, 0)}")
    print()
    print("  Hard caps applied:")
    for k, v in sorted(cap_counts.items()):
        print(f"    {k:<25}: {v}")
    print()
    print(f"  VHS final — avg={vhs_final.mean():.1f}  min={vhs_final.min():.1f}  max={vhs_final.max():.1f}")
    print(f"  Audit issues            : {len(df_audit)}")
    print("=" * 65)

    logger.info(f"Done: {len(df_scores)} scores, {len(df_penalty)} penalty rows -> mart")
    return df_scores, df_penalty, df_audit


if __name__ == "__main__":
    compute_vhs()
