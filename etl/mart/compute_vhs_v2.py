"""
etl/mart/compute_vhs_v2.py
===========================
Computes the Vehicle Health Score V2 (VHS_BALANCED_V2).

Changes from V1:
  - New observed_status: WORN_STRONG
    -> triggered when est_anomalie_critique=true AND valeur_controle='Intervention conseillée'
    -> penalty = (penalty_worn + penalty_broken) / 2
    -> state_value = 0.25 (between WORN=0.5 and BROKEN=0.0)
  - Updated safety grade logic to track WORN_STRONG separately:
    -> Grade D: t1_vital_broken >= 1 OR t1_important_broken >= 3  (unchanged)
    -> Grade C: t1_vital_worn_strong >= 1 OR t1_important_broken >= 1 OR (t1_worn + t1_worn_strong) >= 4
    -> Grade B: t1_worn >= 1 OR t1_worn_strong >= 1
  - Same hard caps, same decision tree, same km penalty as V1.

V1 results are NEVER modified.

Sources:
  dwh.fact_inspection_vehicule   — one row per inspection
  dwh.fact_inspection_checkpoint — observed checkpoint values
  mart.dim_checkpoint            — scoring reference (criticality, penalties)

Outputs (appended to existing tables from V1):
  mart.fact_vhs_score
  mart.fact_vhs_penalty_detail
  data/quality_reports/vhs/vhs_business_rule_audit_v2.csv
  data/quality_reports/vhs/vhs_v1_vs_v2_comparison.csv
  data/quality_reports/vhs/vhs_v1_vs_v2_summary.md
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent

import numpy as np
import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dwh"))
import dwh_utils

BASE_DIR       = Path(__file__).resolve().parent.parent.parent
VHS_REPORT_DIR = BASE_DIR / "data" / "quality_reports" / "vhs"

PROFILE_NAME = "VHS_BALANCED_V2"
RULE_VERSION  = "VHS_BALANCED_V2"
TODAY = datetime.now(timezone.utc).replace(tzinfo=None)

V1_RUN_ID = "VHS_BALANCED_V1_20260630_103138"

# Two DB variants of the repair phrase
_REPAIR_SUBSTRINGS = [
    "Réparation effectuée suite à l'accord client",      # ASCII apostrophe
    "Réparation effectuée suite à l’accord client", # Unicode right single quote U+2019
]
_OK_VALUES          = frozenset({"Contrôle OK", "Bon", "OUI"})
_INTERVENTION_VALUE = "Intervention conseillée"

# State values for subscore computation (None = excluded from average)
_STATE_VALUES_V2 = {"OK": 1.0, "WORN": 0.5, "WORN_STRONG": 0.25, "BROKEN": 0.0}

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
# DDL — tables already exist from V1; CREATE IF NOT EXISTS is a safe no-op
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

# ---------------------------------------------------------------------------
# Pure functions — V2 scoring rules
# ---------------------------------------------------------------------------

def _normalize_status_v2_vectorized(df: pd.DataFrame) -> pd.Series:
    """
    V2 observed_status normalization (vectorized).
    Priority (applied bottom to top; highest priority applied last):

    8. default → UNKNOWN
    7. valeur_controle in OK_VALUES → OK
    6. est_anomalie = true → WORN
    5. est_anomalie_critique = true → BROKEN  (conservative fallback for any unrecognized value)
    3. est_anomalie_critique = true AND valeur_controle = 'Intervention conseillée' → WORN_STRONG
    2. valeur_controle contains repair phrase → REPAIRED
    1. est_controle_renseigne = false → UNKNOWN  (highest: evaluation not performed)
    """
    renseigne    = df["est_controle_renseigne"].fillna(False).astype(bool)
    critique     = df["est_anomalie_critique"].fillna(False).astype(bool)
    anomalie     = df["est_anomalie"].fillna(False).astype(bool)
    valeur       = df["valeur_controle"].fillna("").astype(str)
    intervention = valeur == _INTERVENTION_VALUE

    status = pd.array(["UNKNOWN"] * len(df), dtype=object)

    # 7. OK
    status[renseigne.values & valeur.isin(_OK_VALUES).values] = "OK"
    # 6. WORN
    status[renseigne.values & anomalie.values] = "WORN"
    # 5. BROKEN (covers all est_anomalie_critique=true including unrecognized valeur)
    status[renseigne.values & critique.values] = "BROKEN"
    # 3. WORN_STRONG — overrides BROKEN for advisory wording
    status[renseigne.values & critique.values & intervention.values] = "WORN_STRONG"
    # 2. REPAIRED — overrides WORN_STRONG/BROKEN/WORN
    mask_repair = pd.Series(False, index=df.index)
    for phrase in _REPAIR_SUBSTRINGS:
        mask_repair = mask_repair | valeur.str.contains(phrase, regex=False, na=False)
    status[renseigne.values & mask_repair.values] = "REPAIRED"
    # 1. UNKNOWN — highest priority
    status[~renseigne.values] = "UNKNOWN"

    return pd.Series(status, index=df.index, name="observed_status")


def _km_penalty(km) -> float:
    if km is None or (isinstance(km, float) and np.isnan(km)) or km <= 0:
        return 1.0
    km = float(km)
    if km >= 350_000: return 6.0
    if km >= 250_000: return 4.0
    if km >= 180_000: return 2.5
    if km >= 120_000: return 1.0
    return 0.0


def _compute_grade_v2(
    vital_broken: int,
    vital_worn_strong: int,
    important_broken: int,
    t1_worn: int,
    t1_worn_strong: int,
) -> str:
    if vital_broken >= 1 or important_broken >= 3:
        return "D"
    if vital_worn_strong >= 1 or important_broken >= 1 or (t1_worn + t1_worn_strong) >= 4:
        return "C"
    if t1_worn >= 1 or t1_worn_strong >= 1:
        return "B"
    return "A"


def _compute_decision(grade: str, drivable: bool, has_cf: bool, vhs_bc: float) -> str:
    if grade == "D":       return "CRITIQUE"
    if not drivable:       return "IMMOBILISE"
    if grade == "C" or has_cf or vhs_bc < 70.0: return "DEGRADE"
    return "OK"


def _compute_cap(grade: str, drivable: bool, has_cf: bool) -> tuple[float | None, str | None]:
    if grade == "D":   return 40.0, "GRADE_D"
    if not drivable:   return 50.0, "IMMOBILIZED"
    if grade == "C":   return 65.0, "GRADE_C"
    if has_cf:         return 65.0, "CRITICAL_FUNCTIONAL"
    return None, None


# ---------------------------------------------------------------------------
# Core processing — V2
# ---------------------------------------------------------------------------

def _process_all_v2(
    df_veh: pd.DataFrame,
    df_cp_raw: pd.DataFrame,
    df_dim: pd.DataFrame,
    run_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (df_scores, df_penalty) ready for DB insert."""

    df_cp = df_cp_raw.merge(df_dim[_DIM_COLS], on="checkpoint_code", how="inner")

    # Cast penalty columns (PostgreSQL NUMERIC → Decimal → float)
    df_cp["penalty_worn"]   = df_cp["penalty_worn"].astype(float)
    df_cp["penalty_broken"] = df_cp["penalty_broken"].astype(float)

    # Normalize V2 observed status
    df_cp["observed_status"] = _normalize_status_v2_vectorized(df_cp)

    # WORN_STRONG penalty = midpoint between worn and broken
    penalty_worn        = df_cp["penalty_worn"]
    penalty_broken      = df_cp["penalty_broken"]
    penalty_worn_strong = ((penalty_worn + penalty_broken) / 2).round(2)

    status = df_cp["observed_status"]
    df_cp["penalty_applied"] = np.where(
        status == "WORN",        penalty_worn,
        np.where(
            status == "WORN_STRONG", penalty_worn_strong,
            np.where(
                status == "BROKEN",  penalty_broken,
                0.0
            )
        )
    )

    # State value (NaN = excluded from subscore average)
    df_cp["state_value"] = status.map(_STATE_VALUES_V2)

    all_keys = df_veh["inspection_key"].values

    # ── Aggregations ────────────────────────────────────────────────────────

    total_pen = (
        df_cp.groupby("inspection_key")["penalty_applied"].sum()
        .reindex(all_keys, fill_value=0.0)
    )

    df_t1 = df_cp[df_cp["tier"].isin(["T1_VITAL", "T1_IMPORTANT"])]
    df_t2 = df_cp[df_cp["tier"].isin(["T2_CRITICAL", "T2_NORMAL"])]
    df_t3 = df_cp[df_cp["tier"] == "T3_COSMETIC"]

    safety_agg     = df_t1.groupby("inspection_key")["state_value"].mean() * 100
    functional_agg = df_t2.groupby("inspection_key")["state_value"].mean() * 100
    cosmetic_agg   = df_t3.groupby("inspection_key")["state_value"].mean() * 100

    t1_vital_broken = (
        df_cp[(df_cp["tier"] == "T1_VITAL") & (status == "BROKEN")]
        .groupby("inspection_key").size()
        .reindex(all_keys, fill_value=0)
    )
    t1_vital_worn_strong = (
        df_cp[(df_cp["tier"] == "T1_VITAL") & (status == "WORN_STRONG")]
        .groupby("inspection_key").size()
        .reindex(all_keys, fill_value=0)
    )
    t1_important_broken = (
        df_cp[(df_cp["tier"] == "T1_IMPORTANT") & (status == "BROKEN")]
        .groupby("inspection_key").size()
        .reindex(all_keys, fill_value=0)
    )
    t1_worn_count = (
        df_cp[df_cp["tier"].isin(["T1_VITAL", "T1_IMPORTANT"]) & (status == "WORN")]
        .groupby("inspection_key").size()
        .reindex(all_keys, fill_value=0)
    )
    t1_worn_strong_count = (
        df_cp[df_cp["tier"].isin(["T1_VITAL", "T1_IMPORTANT"]) & (status == "WORN_STRONG")]
        .groupby("inspection_key").size()
        .reindex(all_keys, fill_value=0)
    )
    immo_broken_count = (
        df_cp[df_cp["is_immobilizing"].astype(bool) & (status == "BROKEN")]
        .groupby("inspection_key").size()
        .reindex(all_keys, fill_value=0)
    )
    cf_broken_count = (
        df_cp[df_cp["is_critical_functional"].astype(bool) & (status == "BROKEN")]
        .groupby("inspection_key").size()
        .reindex(all_keys, fill_value=0)
    )
    nb_penalties = (
        df_cp[df_cp["penalty_applied"] > 0]
        .groupby("inspection_key").size()
        .reindex(all_keys, fill_value=0)
    )

    # ── Build score rows ─────────────────────────────────────────────────────

    score_rows = []
    for _, vrow in df_veh.iterrows():
        key = vrow["inspection_key"]

        total_p = float(total_pen[key])
        vhs_raw = round(max(0.0, 100.0 - total_p), 2)
        km_p    = round(_km_penalty(vrow.get("kilometrage")), 2)
        vhs_bc  = round(max(0.0, vhs_raw - km_p), 2)

        vital_b     = int(t1_vital_broken[key])
        vital_ws    = int(t1_vital_worn_strong[key])
        import_b    = int(t1_important_broken[key])
        t1_w        = int(t1_worn_count[key])
        t1_ws       = int(t1_worn_strong_count[key])
        grade       = _compute_grade_v2(vital_b, vital_ws, import_b, t1_w, t1_ws)
        drivable    = immo_broken_count[key] == 0
        has_cf      = cf_broken_count[key] > 0

        decision        = _compute_decision(grade, drivable, has_cf, vhs_bc)
        cap_val, cap_tp = _compute_cap(grade, drivable, has_cf)

        vhs_final        = round(min(vhs_bc, cap_val), 2) if cap_val is not None else vhs_bc
        hard_cap_applied = (cap_val is not None) and (vhs_final < vhs_bc)

        ss = safety_agg.get(key)
        fs = functional_agg.get(key)
        cs = cosmetic_agg.get(key)

        score_rows.append({
            "inspection_key":         key,
            "vehicule_sk":            int(vrow["vehicule_sk"])         if pd.notna(vrow.get("vehicule_sk"))         else None,
            "date_inspection_sk":     int(vrow["date_inspection_sk"])  if pd.notna(vrow.get("date_inspection_sk"))  else None,
            "immatriculation_norm":   vrow.get("immatriculation_norm"),
            "kilometrage":            float(vrow["kilometrage"])        if pd.notna(vrow.get("kilometrage"))         else None,
            "vhs_raw_score":          vhs_raw,
            "kilometrage_penalty":    km_p,
            "vhs_before_cap":         vhs_bc,
            "vhs_final_score":        vhs_final,
            "safety_score":           round(float(ss), 2) if pd.notna(ss) else None,
            "functional_score":       round(float(fs), 2) if pd.notna(fs) else None,
            "cosmetic_score":         round(float(cs), 2) if pd.notna(cs) else None,
            "safety_grade":           grade,
            "decision":               decision,
            "is_drivable":            bool(drivable),
            "hard_cap_applied":       bool(hard_cap_applied),
            "hard_cap_type":          cap_tp,
            "nb_penalties_applied":   int(nb_penalties[key]),
            "nb_anomalies_total":     int(vrow["nb_anomalies_total"])     if pd.notna(vrow.get("nb_anomalies_total"))     else 0,
            "nb_anomalies_critiques": int(vrow["nb_anomalies_critiques"]) if pd.notna(vrow.get("nb_anomalies_critiques")) else 0,
            "profile_name":           PROFILE_NAME,
            "rule_version":           RULE_VERSION,
            "run_id":                 run_id,
            "calculated_at":          TODAY,
            "source_system":          "IRIS_VHS",
            "created_at":             TODAY,
        })

    df_scores = pd.DataFrame(score_rows)

    # ── Build penalty detail rows ────────────────────────────────────────────
    df_det = df_cp[
        df_cp["observed_status"].isin(["WORN", "WORN_STRONG", "BROKEN", "REPAIRED"])
    ].copy()

    df_det["penalty_reason"] = df_det["observed_status"].map({
        "WORN":       "Worn or non-critical anomaly. Penalty from dim_checkpoint.penalty_worn.",
        "WORN_STRONG": (
            "Critical advisory anomaly. valeur_controle=Intervention conseillée with "
            "est_anomalie_critique=true. Intermediate penalty between worn and broken."
        ),
        "BROKEN":     "Broken or confirmed critical anomaly. Penalty from dim_checkpoint.penalty_broken.",
        "REPAIRED":   "Repair performed after client approval. Kept for traceability without VHS penalty in V2.",
    })

    df_det["is_hard_cap_trigger"] = False
    df_det["hard_cap_type"]       = None

    def _mark_trigger(mask: pd.Series, cap_type: str) -> None:
        df_det.loc[mask, "is_hard_cap_trigger"] = True
        df_det.loc[mask, "hard_cap_type"]        = cap_type

    # 4. CRITICAL_FUNCTIONAL (lowest priority)
    cf_inspections = df_scores.loc[df_scores["hard_cap_type"] == "CRITICAL_FUNCTIONAL", "inspection_key"]
    if len(cf_inspections):
        _mark_trigger(
            df_det["inspection_key"].isin(cf_inspections) &
            df_det["is_critical_functional"].astype(bool) &
            (df_det["observed_status"] == "BROKEN"),
            "CRITICAL_FUNCTIONAL",
        )

    # 3. GRADE_C
    grade_c_keys = df_scores.loc[df_scores["safety_grade"] == "C", "inspection_key"]
    if len(grade_c_keys):
        c_keys_arr = grade_c_keys.values

        # T1_VITAL WORN_STRONG trigger
        vital_ws_mask = t1_vital_worn_strong[c_keys_arr].values >= 1
        vital_ws_keys = c_keys_arr[vital_ws_mask]
        if len(vital_ws_keys):
            _mark_trigger(
                df_det["inspection_key"].isin(vital_ws_keys) &
                (df_det["tier"] == "T1_VITAL") &
                (df_det["observed_status"] == "WORN_STRONG"),
                "GRADE_C",
            )

        # T1_IMPORTANT BROKEN trigger
        _mark_trigger(
            df_det["inspection_key"].isin(c_keys_arr) &
            (df_det["tier"] == "T1_IMPORTANT") &
            (df_det["observed_status"] == "BROKEN"),
            "GRADE_C",
        )

        # T1 WORN/WORN_STRONG when (worn + worn_strong) >= 4
        t1_combined = t1_worn_count[c_keys_arr].values + t1_worn_strong_count[c_keys_arr].values
        high_combined_keys = c_keys_arr[t1_combined >= 4]
        if len(high_combined_keys):
            _mark_trigger(
                df_det["inspection_key"].isin(high_combined_keys) &
                df_det["tier"].isin(["T1_VITAL", "T1_IMPORTANT"]) &
                df_det["observed_status"].isin(["WORN", "WORN_STRONG"]),
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
        d_keys_arr = grade_d_keys.values
        # Triggered by T1_VITAL BROKEN
        _mark_trigger(
            df_det["inspection_key"].isin(d_keys_arr) &
            (df_det["tier"] == "T1_VITAL") &
            (df_det["observed_status"] == "BROKEN"),
            "GRADE_D",
        )
        # Triggered by T1_IMPORTANT BROKEN >= 3
        imp_d_mask = t1_important_broken[d_keys_arr].values >= 3
        imp_d_keys = d_keys_arr[imp_d_mask]
        if len(imp_d_keys):
            _mark_trigger(
                df_det["inspection_key"].isin(imp_d_keys) &
                (df_det["tier"] == "T1_IMPORTANT") &
                (df_det["observed_status"] == "BROKEN"),
                "GRADE_D",
            )

    df_det["profile_name"] = PROFILE_NAME
    df_det["rule_version"] = RULE_VERSION
    df_det["run_id"]       = run_id
    df_det["created_at"]   = TODAY

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
# Business rule audit — V2 (9 checks)
# ---------------------------------------------------------------------------

def _run_audit_v2(
    df_scores: pd.DataFrame,
    df_penalty: pd.DataFrame,
    run_id: str,
    n_intervention_critique: int,
) -> pd.DataFrame:
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

    for _, row in df_scores.iterrows():
        key      = row["inspection_key"]
        decision = row["decision"]
        det      = df_penalty[df_penalty["inspection_key"] == key] if len(df_penalty) else pd.DataFrame()

        # 1. T1_VITAL BROKEN → must not be OK
        if (
            len(det) > 0 and
            any((det["tier"] == "T1_VITAL") & (det["observed_status"] == "BROKEN")) and
            decision == "OK"
        ):
            _add("T1_VITAL_BROKEN_NOT_OK", key,
                 "Vehicle has T1_VITAL BROKEN but decision is OK", "CRITICAL")

        # 2. T1_VITAL WORN_STRONG → must not be OK
        if (
            len(det) > 0 and
            any((det["tier"] == "T1_VITAL") & (det["observed_status"] == "WORN_STRONG")) and
            decision == "OK"
        ):
            _add("T1_VITAL_WORN_STRONG_NOT_OK", key,
                 "Vehicle has T1_VITAL WORN_STRONG but decision is OK", "CRITICAL")

        # 3. Immobilizing BROKEN → must not be OK
        if (
            len(det) > 0 and
            any(det["is_immobilizing"].astype(bool) & (det["observed_status"] == "BROKEN")) and
            decision == "OK"
        ):
            _add("IMMOBILIZING_BROKEN_NOT_OK", key,
                 "Vehicle has immobilizing BROKEN but decision is OK", "CRITICAL")

        # 4. Only T3_COSMETIC penalties → must not be CRITIQUE
        all_tiers   = set(det["tier"].unique()) if len(det) > 0 else set()
        only_cosm   = all_tiers.issubset({"T3_COSMETIC"}) and len(all_tiers) > 0
        if only_cosm and decision == "CRITIQUE":
            _add("COSMETIC_ONLY_NOT_CRITIQUE", key,
                 "Vehicle has only T3_COSMETIC penalties but decision is CRITIQUE", "HIGH")

        # 5. Kilometrage alone → must not be CRITIQUE
        if row["nb_penalties_applied"] == 0 and decision == "CRITIQUE":
            _add("KM_ALONE_NOT_CRITIQUE", key,
                 "Vehicle has no checkpoint penalties but decision is CRITIQUE", "HIGH")

        # 6. hard_cap_applied = true → must have non-null hard_cap_type
        if row["hard_cap_applied"] and (row["hard_cap_type"] is None or pd.isna(row["hard_cap_type"])):
            _add("HARD_CAP_TYPE_MISSING", key,
                 "hard_cap_applied=true but hard_cap_type is null", "CRITICAL")

        # 7. CRITIQUE → must have at least one explanation row
        if decision == "CRITIQUE" and len(det) == 0:
            _add("CRITIQUE_NEEDS_EXPLANATION", key,
                 "CRITIQUE decision has no rows in fact_vhs_penalty_detail", "HIGH")

    # 8. UNKNOWN_REVIEW checkpoints must not contribute penalties
    if len(df_penalty) > 0 and "tier" in df_penalty.columns:
        for _, prow in df_penalty[
            (df_penalty["tier"] == "UNKNOWN_REVIEW") & (df_penalty["penalty_applied"] > 0)
        ].iterrows():
            _add("UNKNOWN_REVIEW_NO_PENALTY", prow["inspection_key"],
                 f"UNKNOWN_REVIEW checkpoint {prow['checkpoint_code']} has penalty > 0",
                 "CRITICAL")

    # 9. WORN_STRONG rows must exist when source had T1 Intervention conseillée + critique
    if n_intervention_critique > 0:
        n_ws = len(df_penalty[df_penalty["observed_status"] == "WORN_STRONG"]) if len(df_penalty) > 0 else 0
        if n_ws == 0:
            _add("WORN_STRONG_ROWS_MISSING", "GLOBAL",
                 f"Source had {n_intervention_critique} T1 'Intervention conseillée' + critique rows "
                 "but no WORN_STRONG rows produced in penalty detail",
                 "CRITICAL")

    cols = ["test_name", "inspection_key", "issue_description",
            "severity", "profile_name", "rule_version", "run_id"]
    return pd.DataFrame(issues) if issues else pd.DataFrame(columns=cols)


# ---------------------------------------------------------------------------
# V1 vs V2 comparison
# ---------------------------------------------------------------------------

def _compare_v1_v2(
    engine,
    df_v2_scores: pd.DataFrame,
    df_v2_penalty: pd.DataFrame,
    run_id_v2: str,
    logger,
) -> tuple[pd.DataFrame, str]:
    """Build comparison DataFrame and markdown summary."""

    logger.info("  Loading V1 scores for comparison ...")
    with engine.connect() as conn:
        df_v1 = pd.read_sql(
            text("""
                SELECT inspection_key, immatriculation_norm,
                       vhs_final_score, safety_grade, decision,
                       hard_cap_type, nb_penalties_applied
                FROM mart.fact_vhs_score
                WHERE run_id = :rid
            """),
            conn, params={"rid": V1_RUN_ID},
        )
        df_v1_nb = pd.read_sql(
            text("""
                SELECT inspection_key, COUNT(*) AS n
                FROM mart.fact_vhs_penalty_detail
                WHERE run_id = :rid
                GROUP BY inspection_key
            """),
            conn, params={"rid": V1_RUN_ID},
        ).rename(columns={"n": "v1_nb_penalties"})

    df_v2 = df_v2_scores[[
        "inspection_key", "vhs_final_score", "safety_grade",
        "decision", "hard_cap_type", "nb_penalties_applied",
    ]].copy()

    df_v2_nb = (
        df_v2_penalty[df_v2_penalty["observed_status"] != "REPAIRED"]
        .groupby("inspection_key").size()
        .reset_index(name="v2_nb_penalties")
    ) if len(df_v2_penalty) > 0 else pd.DataFrame(columns=["inspection_key", "v2_nb_penalties"])

    merged = df_v1.rename(columns={
        "vhs_final_score":   "v1_score",
        "safety_grade":      "v1_grade",
        "decision":          "v1_decision",
        "hard_cap_type":     "v1_hard_cap_type",
        "nb_penalties_applied": "_v1_np",
    }).merge(
        df_v2.rename(columns={
            "vhs_final_score":   "v2_score",
            "safety_grade":      "v2_grade",
            "decision":          "v2_decision",
            "hard_cap_type":     "v2_hard_cap_type",
            "nb_penalties_applied": "_v2_np",
        }),
        on="inspection_key", how="outer",
    )
    merged = merged.merge(df_v1_nb, on="inspection_key", how="left")
    merged = merged.merge(df_v2_nb, on="inspection_key", how="left")
    merged["v1_nb_penalties"] = merged["v1_nb_penalties"].fillna(0).astype(int)
    merged["v2_nb_penalties"] = merged["v2_nb_penalties"].fillna(0).astype(int)

    merged["score_delta"]      = (merged["v2_score"]    - merged["v1_score"]).round(2)
    merged["grade_changed"]    = merged["v1_grade"]    != merged["v2_grade"]
    merged["decision_changed"] = merged["v1_decision"] != merged["v2_decision"]

    comparison_cols = [
        "inspection_key", "immatriculation_norm",
        "v1_score", "v2_score", "score_delta",
        "v1_grade", "v2_grade", "grade_changed",
        "v1_decision", "v2_decision", "decision_changed",
        "v1_hard_cap_type", "v2_hard_cap_type",
        "v1_nb_penalties", "v2_nb_penalties",
    ]
    df_cmp = merged[[c for c in comparison_cols if c in merged.columns]].copy()
    df_cmp = df_cmp.sort_values(["decision_changed", "grade_changed"], ascending=False).reset_index(drop=True)

    # ── Markdown ─────────────────────────────────────────────────────────────

    n_total      = len(df_cmp)
    n_dec_change = int(df_cmp["decision_changed"].sum())
    n_grd_change = int(df_cmp["grade_changed"].sum())

    # Decision distribution comparison
    def _dist(series: pd.Series) -> dict:
        return series.value_counts().sort_index().to_dict()

    v1_dec = _dist(df_cmp["v1_decision"])
    v2_dec = _dist(df_cmp["v2_decision"])
    v1_grd = _dist(df_cmp["v1_grade"])
    v2_grd = _dist(df_cmp["v2_grade"])

    def _score_stats(col: str) -> tuple[float, float, float]:
        s = df_cmp[col].dropna()
        return round(s.mean(), 2), round(s.min(), 2), round(s.max(), 2)

    v1_avg, v1_min, v1_max = _score_stats("v1_score")
    v2_avg, v2_min, v2_max = _score_stats("v2_score")

    # Decision transitions
    def _trans(from_d: str, to_d: str) -> int:
        return int(((df_cmp["v1_decision"] == from_d) & (df_cmp["v2_decision"] == to_d)).sum())

    def _gtrans(from_g: str, to_g: str) -> int:
        return int(((df_cmp["v1_grade"] == from_g) & (df_cmp["v2_grade"] == to_g)).sum())

    # WORN_STRONG stats
    n_ws_rows = len(df_v2_penalty[df_v2_penalty["observed_status"] == "WORN_STRONG"]) if len(df_v2_penalty) > 0 else 0
    if n_ws_rows > 0:
        ws_by_cp = (
            df_v2_penalty[df_v2_penalty["observed_status"] == "WORN_STRONG"]
            .groupby(["checkpoint_code", "checkpoint_libelle", "tier"])
            .size().reset_index(name="n")
            .sort_values("n", ascending=False)
            .head(10)
        )
        ws_lines = ["| checkpoint | tier | nb_worn_strong |", "|---|---|---|"]
        for r in ws_by_cp.itertuples():
            ws_lines.append(f"| {r.checkpoint_libelle} | {r.tier} | {r.n} |")
    else:
        ws_lines = ["No WORN_STRONG rows were generated."]

    decision_order = ["CRITIQUE", "DEGRADE", "IMMOBILISE", "OK"]
    grade_order    = ["A", "B", "C", "D"]

    dec_table = (
        "| Decision | V1 | V2 | Delta |\n|---|---|---|---|\n" +
        "\n".join(
            f"| {d} | {v1_dec.get(d, 0)} | {v2_dec.get(d, 0)} | {v2_dec.get(d, 0) - v1_dec.get(d, 0):+d} |"
            for d in decision_order
        )
    )
    grd_table = (
        "| Grade | V1 | V2 | Delta |\n|---|---|---|---|\n" +
        "\n".join(
            f"| {g} | {v1_grd.get(g, 0)} | {v2_grd.get(g, 0)} | {v2_grd.get(g, 0) - v1_grd.get(g, 0):+d} |"
            for g in grade_order
        )
    )

    markdown = dedent(f"""
    # VHS V1 vs V2 — Comparison Summary

    ---

    ## 1. Run IDs

    | | Value |
    |---|---|
    | V1 run_id | `{V1_RUN_ID}` |
    | V2 run_id | `{run_id_v2}` |
    | Inspections compared | {n_total} |
    | Decision changed | {n_dec_change} ({round(100 * n_dec_change / n_total, 1) if n_total else 0}%) |
    | Safety grade changed | {n_grd_change} ({round(100 * n_grd_change / n_total, 1) if n_total else 0}%) |

    ---

    ## 2. Decision Distribution

    {dec_table}

    ---

    ## 3. Safety Grade Distribution

    {grd_table}

    ---

    ## 4. Score Statistics

    | Metric | V1 | V2 |
    |---|---|---|
    | Average score | {v1_avg} | {v2_avg} |
    | Min score | {v1_min} | {v2_min} |
    | Max score | {v1_max} | {v2_max} |

    ---

    ## 5. Decision and Grade Transitions

    | Transition | Count |
    |---|---|
    | CRITIQUE → DEGRADE | {_trans('CRITIQUE', 'DEGRADE')} |
    | CRITIQUE → OK | {_trans('CRITIQUE', 'OK')} |
    | DEGRADE → OK | {_trans('DEGRADE', 'OK')} |
    | OK → DEGRADE | {_trans('OK', 'DEGRADE')} |
    | OK → CRITIQUE | {_trans('OK', 'CRITIQUE')} |
    | Grade D → Grade C | {_gtrans('D', 'C')} |
    | Grade D → Grade B | {_gtrans('D', 'B')} |
    | Grade D → Grade A | {_gtrans('D', 'A')} |
    | Grade C → Grade B | {_gtrans('C', 'B')} |
    | Grade C → Grade A | {_gtrans('C', 'A')} |
    | Grade B → Grade A | {_gtrans('B', 'A')} |
    | Grade A → Grade B | {_gtrans('A', 'B')} |
    | Grade A → Grade C | {_gtrans('A', 'C')} |

    ---

    ## 6. WORN_STRONG Analysis

    WORN_STRONG rows created: **{n_ws_rows}**

    These are T1 checkpoint observations where:
    - `est_anomalie_critique = true`
    - `valeur_controle = 'Intervention conseillée'`

    In V1, these were scored as BROKEN (full `penalty_broken`).
    In V2, they are scored as WORN_STRONG (intermediate penalty = `(penalty_worn + penalty_broken) / 2`).

    ### Top checkpoints contributing WORN_STRONG rows

    {chr(10).join(ws_lines)}

    ---

    ## 7. Business Conclusion

    **V2 softens advisory critical anomalies without ignoring them.**
    - `Intervention conseillée` + `est_anomalie_critique=true` now maps to WORN_STRONG
      instead of BROKEN, reducing unwarranted Grade D assignments.
    - Confirmed defects (`Défectueux`, `Contrôle non OK`, `Proposition faite`) still map
      to BROKEN and can trigger Grade D.
    - Grade B is now reachable: inspections with only WORN or WORN_STRONG T1 anomalies
      no longer jump directly to Grade D.
    - Hard caps are unchanged. Any remaining Grade D inspections are confirmed critical cases.

    **V2 should be reviewed against the top critical cases before final calibration.**
    - Check `vhs_v1_vs_v2_comparison.csv` for all decision-changed rows.
    - Validate with domain experts that `Intervention conseillée` + `est_anomalie_critique=true`
      truly warrants WORN_STRONG rather than BROKEN in all cases.
    - If further softening is needed, adjust Grade D/C thresholds in a V3 revision.

    ---

    *Generated by etl/mart/compute_vhs_v2.py — V1 data is unchanged.*
    """).strip()

    return df_cmp, markdown


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def compute_vhs_v2():
    logger = dwh_utils.setup_logging("compute_vhs_v2")
    run_id = f"VHS_BALANCED_V2_{TODAY.strftime('%Y%m%d_%H%M%S')}"

    logger.info("=" * 65)
    logger.info(f"[RUN] {run_id}")
    logger.info(f"      profile={PROFILE_NAME}  rule={RULE_VERSION}")
    logger.info("  V1 data will NOT be modified")
    logger.info("=" * 65)

    engine = dwh_utils.build_engine(logger)

    # ------------------------------------------------------------------
    # 1. DDL — no-op if tables already exist from V1
    # ------------------------------------------------------------------
    with engine.begin() as conn:
        conn.execute(text(DDL_CREATE_SCHEMA))
        conn.execute(text(DDL_FACT_VHS_SCORE))
        conn.execute(text(DDL_FACT_VHS_PENALTY_DETAIL))
    logger.info("  DDL: CREATE IF NOT EXISTS (no-op if V1 tables exist)")

    # ------------------------------------------------------------------
    # 2. Load source data
    # ------------------------------------------------------------------
    with engine.connect() as conn:
        df_veh    = pd.read_sql(text("SELECT * FROM dwh.fact_inspection_vehicule"), conn)
        df_cp_raw = pd.read_sql(text("SELECT * FROM dwh.fact_inspection_checkpoint"), conn)
        df_dim    = pd.read_sql(
            text("SELECT * FROM mart.dim_checkpoint WHERE is_vhs_scored = true"), conn
        )

    logger.info(f"  inspections loaded           : {len(df_veh)}")
    logger.info(f"  checkpoint observations      : {len(df_cp_raw)}")
    logger.info(f"  scored dim_checkpoint rows   : {len(df_dim)}")

    # Count T1 "Intervention conseillée" + est_anomalie_critique for audit check #9
    t1_codes = set(df_dim.loc[df_dim["tier"].isin(["T1_VITAL", "T1_IMPORTANT"]), "checkpoint_code"])
    df_cp_raw_bool = df_cp_raw.copy()
    df_cp_raw_bool["est_anomalie_critique"] = df_cp_raw_bool["est_anomalie_critique"].fillna(False).astype(bool)
    n_intervention_critique = int(
        (
            df_cp_raw_bool["checkpoint_code"].isin(t1_codes) &
            (df_cp_raw_bool["valeur_controle"] == _INTERVENTION_VALUE) &
            df_cp_raw_bool["est_anomalie_critique"]
        ).sum()
    )
    logger.info(f"  T1 Intervention+critique rows: {n_intervention_critique}")

    # ------------------------------------------------------------------
    # 3. Compute V2
    # ------------------------------------------------------------------
    df_scores, df_penalty = _process_all_v2(df_veh, df_cp_raw, df_dim, run_id)
    n_ws = int((df_penalty["observed_status"] == "WORN_STRONG").sum()) if len(df_penalty) else 0
    logger.info(f"  VHS V2 scores computed       : {len(df_scores)}")
    logger.info(f"  penalty detail rows          : {len(df_penalty)}")
    logger.info(f"  WORN_STRONG rows             : {n_ws}")

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
    # 7. Business rule audit V2
    # ------------------------------------------------------------------
    df_audit = _run_audit_v2(df_scores, df_penalty, run_id, n_intervention_critique)
    VHS_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    audit_path = VHS_REPORT_DIR / "vhs_business_rule_audit_v2.csv"
    df_audit.to_csv(audit_path, index=False, encoding="utf-8-sig")
    logger.info(f"  V2 business rule audit issues: {len(df_audit)}")
    logger.info(f"  audit report                 : {audit_path}")

    # ------------------------------------------------------------------
    # 8. V1 vs V2 comparison
    # ------------------------------------------------------------------
    df_cmp, md_summary = _compare_v1_v2(engine, df_scores, df_penalty, run_id, logger)
    cmp_path = VHS_REPORT_DIR / "vhs_v1_vs_v2_comparison.csv"
    md_path  = VHS_REPORT_DIR / "vhs_v1_vs_v2_summary.md"
    df_cmp.to_csv(cmp_path, index=False, encoding="utf-8-sig")
    md_path.write_text(md_summary, encoding="utf-8")
    logger.info(f"  comparison CSV               : {cmp_path}")
    logger.info(f"  comparison markdown          : {md_path}")

    n_dec_changes = int(df_cmp["decision_changed"].sum()) if "decision_changed" in df_cmp.columns else 0
    n_grd_changes = int(df_cmp["grade_changed"].sum())    if "grade_changed"    in df_cmp.columns else 0

    # ------------------------------------------------------------------
    # 9. Summary metrics
    # ------------------------------------------------------------------
    decision_counts = df_scores["decision"].value_counts().sort_index().to_dict()
    grade_counts    = df_scores["safety_grade"].value_counts().sort_index().to_dict()
    cap_counts      = df_scores[df_scores["hard_cap_applied"]]["hard_cap_type"].value_counts().sort_index().to_dict()
    vhs_final       = df_scores["vhs_final_score"]

    logger.info("=" * 65)
    logger.info(f"  run_id                       : {run_id}")
    logger.info(f"  total inspections scored     : {len(df_scores)}")
    logger.info(f"  total penalty detail rows    : {len(df_penalty)}")
    logger.info(f"  WORN_STRONG rows             : {n_ws}")
    logger.info("  Decision distribution:")
    for k in ["OK", "DEGRADE", "IMMOBILISE", "CRITIQUE"]:
        logger.info(f"    {k:<15}: {decision_counts.get(k, 0)}")
    logger.info("  Safety grade distribution:")
    for k in ["A", "B", "C", "D"]:
        logger.info(f"    {k:<5}: {grade_counts.get(k, 0)}")
    logger.info("  Hard cap type distribution:")
    for k, v in sorted(cap_counts.items()):
        logger.info(f"    {k:<25}: {v}")
    logger.info(f"  vhs_final_score avg          : {vhs_final.mean():.2f}")
    logger.info(f"  vhs_final_score min          : {vhs_final.min():.2f}")
    logger.info(f"  vhs_final_score max          : {vhs_final.max():.2f}")
    logger.info(f"  audit issues                 : {len(df_audit)}")
    logger.info(f"  V1 vs V2 decision changes    : {n_dec_changes}")
    logger.info(f"  V1 vs V2 grade changes       : {n_grd_changes}")
    logger.info("=" * 65)

    # ------------------------------------------------------------------
    # 10. Print summary
    # ------------------------------------------------------------------
    print("=" * 65)
    print(f"  V2 run_id               : {run_id}")
    print(f"  inspections scored      : {len(df_scores)}")
    print(f"  penalty detail rows     : {len(df_penalty)}")
    print(f"  WORN_STRONG rows        : {n_ws}")
    print()
    print("  Decision distribution (V2):")
    for k in ["OK", "DEGRADE", "IMMOBILISE", "CRITIQUE"]:
        print(f"    {k:<15}: {decision_counts.get(k, 0)}")
    print()
    print("  Safety grade distribution (V2):")
    for k in ["A", "B", "C", "D"]:
        print(f"    Grade {k}: {grade_counts.get(k, 0)}")
    print()
    print("  Hard caps (V2):")
    for k, v in sorted(cap_counts.items()):
        print(f"    {k:<25}: {v}")
    print()
    print(f"  VHS final — avg={vhs_final.mean():.1f}  min={vhs_final.min():.1f}  max={vhs_final.max():.1f}")
    print(f"  Audit issues            : {len(df_audit)}")
    print()
    print(f"  V1 vs V2 decision changes: {n_dec_changes}")
    print(f"  V1 vs V2 grade changes   : {n_grd_changes}")
    print()
    print(f"  Reports:")
    print(f"    {audit_path}")
    print(f"    {cmp_path}")
    print(f"    {md_path}")
    print("=" * 65)

    logger.info(f"Done: {len(df_scores)} V2 scores, {len(df_penalty)} penalty rows -> mart")
    return df_scores, df_penalty, df_audit, df_cmp


if __name__ == "__main__":
    compute_vhs_v2()
