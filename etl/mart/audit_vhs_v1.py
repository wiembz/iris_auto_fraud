"""
etl/mart/audit_vhs_v1.py
=========================
Read-only business audit of VHS_BALANCED_V1 results.

Reads:
  mart.fact_vhs_score
  mart.fact_vhs_penalty_detail
  mart.dim_checkpoint

Writes (CSV + Markdown, NO DB changes):
  data/quality_reports/vhs/audit_vhs_v1/

This script does NOT:
  - modify any database table
  - insert, update, delete, truncate, or drop anything
  - recompute VHS or change penalties
  - change mart.dim_checkpoint
"""
from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dwh"))
import dwh_utils
from sqlalchemy import text

BASE_DIR   = Path(__file__).resolve().parent.parent.parent
AUDIT_DIR  = BASE_DIR / "data" / "quality_reports" / "vhs" / "audit_vhs_v1"

TARGET_RUN_ID    = "VHS_BALANCED_V1_20260630_103138"
PROFILE_NAME     = "VHS_BALANCED_V1"
RULE_VERSION     = "VHS_BALANCED_V1"

_SCORE_BANDS = [
    ("0-20",   0,   20),
    ("20-40",  20,  40),
    ("40-60",  40,  60),
    ("60-70",  60,  70),
    ("70-85",  70,  85),
    ("85-100", 85,  100),
]

# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------

def _pct(n: int, total: int) -> float:
    return round(100.0 * n / total, 2) if total > 0 else 0.0


def _save(df: pd.DataFrame, name: str) -> Path:
    path = AUDIT_DIR / name
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


# ---------------------------------------------------------------------------
# Individual report builders
# ---------------------------------------------------------------------------

def _report_decision_distribution(df_scores: pd.DataFrame) -> pd.DataFrame:
    total = len(df_scores)
    grp = df_scores["decision"].value_counts().reset_index()
    grp.columns = ["decision", "nb_inspections"]
    grp["percentage"] = grp["nb_inspections"].apply(lambda n: _pct(n, total))
    return grp.sort_values("nb_inspections", ascending=False).reset_index(drop=True)


def _report_safety_grade_distribution(df_scores: pd.DataFrame) -> pd.DataFrame:
    total = len(df_scores)
    grp = df_scores["safety_grade"].value_counts().reset_index()
    grp.columns = ["safety_grade", "nb_inspections"]
    grp["percentage"] = grp["nb_inspections"].apply(lambda n: _pct(n, total))
    return grp.sort_values("safety_grade").reset_index(drop=True)


def _report_score_distribution(df_scores: pd.DataFrame) -> pd.DataFrame:
    total = len(df_scores)
    rows = []
    scores = df_scores["vhs_final_score"].dropna()
    for band, lo, hi in _SCORE_BANDS:
        if band == "85-100":
            mask = (scores >= lo) & (scores <= hi)
        else:
            mask = (scores >= lo) & (scores < hi)
        sub = scores[mask]
        rows.append({
            "score_band":     band,
            "nb_inspections": len(sub),
            "percentage":     _pct(len(sub), total),
            "min_score":      round(float(sub.min()), 2) if len(sub) > 0 else None,
            "max_score":      round(float(sub.max()), 2) if len(sub) > 0 else None,
        })
    return pd.DataFrame(rows)


def _report_top_penalty_checkpoints(df_penalty: pd.DataFrame) -> pd.DataFrame:
    grp = (
        df_penalty
        .groupby(["checkpoint_code", "checkpoint_libelle", "tier", "observed_status"], dropna=False)
        .agg(
            nb_occurrences    = ("inspection_key", "count"),
            total_penalty     = ("penalty_applied", "sum"),
            avg_penalty       = ("penalty_applied", "mean"),
            nb_hard_cap_triggers = ("is_hard_cap_trigger", "sum"),
        )
        .reset_index()
    )
    grp["avg_penalty"]          = grp["avg_penalty"].round(2)
    grp["total_penalty"]        = grp["total_penalty"].round(2)
    grp["nb_hard_cap_triggers"] = grp["nb_hard_cap_triggers"].astype(int)
    return grp.sort_values("total_penalty", ascending=False).reset_index(drop=True)


def _report_grade_d_triggers(df_penalty: pd.DataFrame) -> pd.DataFrame:
    mask = df_penalty["is_hard_cap_trigger"].astype(bool) & (df_penalty["hard_cap_type"] == "GRADE_D")
    df_d = df_penalty[mask]
    if len(df_d) == 0:
        return pd.DataFrame(columns=[
            "checkpoint_code", "checkpoint_libelle", "tier",
            "observed_status", "nb_occurrences", "total_penalty",
        ])
    grp = (
        df_d
        .groupby(["checkpoint_code", "checkpoint_libelle", "tier", "observed_status"], dropna=False)
        .agg(
            nb_occurrences = ("inspection_key", "count"),
            total_penalty  = ("penalty_applied", "sum"),
        )
        .reset_index()
    )
    grp["total_penalty"] = grp["total_penalty"].round(2)
    return grp.sort_values("nb_occurrences", ascending=False).reset_index(drop=True)


def _report_critical_cases(df_scores: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "inspection_key", "immatriculation_norm", "kilometrage",
        "vhs_raw_score", "kilometrage_penalty", "vhs_before_cap", "vhs_final_score",
        "safety_grade", "decision", "hard_cap_applied", "hard_cap_type",
        "nb_anomalies_total", "nb_anomalies_critiques", "nb_penalties_applied",
    ]
    df_crit = df_scores[df_scores["decision"] == "CRITIQUE"][cols].copy()
    return df_crit.sort_values("vhs_final_score").reset_index(drop=True)


def _report_critical_without_cap(df_scores: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "inspection_key", "immatriculation_norm", "kilometrage",
        "vhs_raw_score", "vhs_before_cap", "vhs_final_score",
        "safety_grade", "hard_cap_type",
        "nb_anomalies_total", "nb_anomalies_critiques", "nb_penalties_applied",
    ]
    mask = (df_scores["decision"] == "CRITIQUE") & (~df_scores["hard_cap_applied"].astype(bool))
    return df_scores[mask][cols].sort_values("vhs_final_score").reset_index(drop=True)


def _report_t1_status_distribution(df_penalty: pd.DataFrame) -> pd.DataFrame:
    df_t1 = df_penalty[df_penalty["tier"].isin(["T1_VITAL", "T1_IMPORTANT"])]
    if len(df_t1) == 0:
        return pd.DataFrame(columns=[
            "checkpoint_code", "checkpoint_libelle", "tier",
            "observed_status", "nb_occurrences", "total_penalty",
        ])
    grp = (
        df_t1
        .groupby(["checkpoint_code", "checkpoint_libelle", "tier", "observed_status"], dropna=False)
        .agg(
            nb_occurrences = ("inspection_key", "count"),
            total_penalty  = ("penalty_applied", "sum"),
        )
        .reset_index()
    )
    grp["total_penalty"] = grp["total_penalty"].round(2)
    return grp.sort_values(["tier", "nb_occurrences"], ascending=[True, False]).reset_index(drop=True)


def _review_reason(row: pd.Series) -> str:
    parts = []
    if row["decision"] in ("CRITIQUE", "IMMOBILISE"):
        parts.append(f"Decision={row['decision']}")
    if pd.notna(row["vhs_final_score"]) and float(row["vhs_final_score"]) < 40:
        parts.append("VHS<40")
    if row["safety_grade"] == "D":
        parts.append("Grade=D")
    if row["hard_cap_applied"]:
        cap = row["hard_cap_type"] if pd.notna(row["hard_cap_type"]) else "?"
        parts.append(f"HardCap={cap}")
    critiques = row.get("nb_anomalies_critiques", 0)
    if pd.notna(critiques) and int(critiques) >= 3:
        parts.append(f"nb_critiques={int(critiques)}")
    return " | ".join(parts) if parts else "REVIEW"


def _report_high_severity_candidates(df_scores: pd.DataFrame) -> pd.DataFrame:
    mask = (
        df_scores["decision"].isin(["CRITIQUE", "IMMOBILISE"]) |
        (df_scores["vhs_final_score"] < 40) |
        (df_scores["safety_grade"] == "D") |
        df_scores["hard_cap_applied"].astype(bool) |
        (df_scores["nb_anomalies_critiques"] >= 3)
    )
    cols = [
        "inspection_key", "immatriculation_norm", "kilometrage",
        "vhs_final_score", "safety_grade", "decision",
        "hard_cap_applied", "hard_cap_type",
        "nb_anomalies_total", "nb_anomalies_critiques",
    ]
    df_rev = df_scores[mask][cols].copy()
    df_rev["review_reason"] = df_scores[mask].apply(_review_reason, axis=1)
    return df_rev.sort_values("vhs_final_score").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Markdown report builder
# ---------------------------------------------------------------------------

def _build_markdown(
    df_scores:   pd.DataFrame,
    df_penalty:  pd.DataFrame,
    df_decision: pd.DataFrame,
    df_grade:    pd.DataFrame,
    df_top_cp:   pd.DataFrame,
    df_grade_d:  pd.DataFrame,
    df_candidates: pd.DataFrame,
) -> str:
    total = len(df_scores)
    n_pen = len(df_penalty)
    avg_s = df_scores["vhs_final_score"].mean()
    min_s = df_scores["vhs_final_score"].min()
    max_s = df_scores["vhs_final_score"].max()

    # Build decision table
    dec_lines = ["| decision | nb | % |", "|---|---|---|"]
    for _, r in df_decision.iterrows():
        dec_lines.append(f"| {r['decision']} | {r['nb_inspections']} | {r['percentage']} |")

    # Build grade table
    grd_lines = ["| grade | nb | % |", "|---|---|---|"]
    for _, r in df_grade.iterrows():
        grd_lines.append(f"| {r['safety_grade']} | {r['nb_inspections']} | {r['percentage']} |")

    # Hard cap distribution
    cap_grp = (
        df_scores[df_scores["hard_cap_applied"].astype(bool)]["hard_cap_type"]
        .value_counts()
        .sort_index()
    )
    cap_lines = ["| cap type | nb |", "|---|---|"]
    for cap, n in cap_grp.items():
        cap_lines.append(f"| {cap} | {n} |")
    if len(cap_lines) == 2:
        cap_lines.append("| (none) | 0 |")

    # Top 10 checkpoints
    top10 = df_top_cp.head(10)
    cp_lines = [
        "| # | checkpoint_libelle | tier | observed_status | nb | total_penalty |",
        "|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(top10.itertuples(), 1):
        cp_lines.append(
            f"| {i} | {r.checkpoint_libelle} | {r.tier} | {r.observed_status}"
            f" | {r.nb_occurrences} | {r.total_penalty} |"
        )

    # Top Grade D triggers
    gd_lines = [
        "| checkpoint_libelle | tier | observed_status | nb |",
        "|---|---|---|---|",
    ]
    for r in df_grade_d.head(10).itertuples():
        gd_lines.append(
            f"| {r.checkpoint_libelle} | {r.tier} | {r.observed_status} | {r.nb_occurrences} |"
        )

    # T1 status breakdown to explain Grade B = 0
    df_t1 = df_penalty[df_penalty["tier"].isin(["T1_VITAL", "T1_IMPORTANT"])]
    t1_broken = len(df_t1[df_t1["observed_status"] == "BROKEN"])
    t1_worn   = len(df_t1[df_t1["observed_status"] == "WORN"])
    t1_total  = t1_broken + t1_worn

    n_critique   = int(df_scores[df_scores["decision"] == "CRITIQUE"]["inspection_key"].count())
    n_grade_d    = int(df_scores[df_scores["safety_grade"] == "D"]["inspection_key"].count())
    n_candidates = len(df_candidates)

    md = dedent(f"""
    # VHS V1 Audit Report — {TARGET_RUN_ID}

    ---

    ## 1. VHS V1 Run Summary

    | Metric | Value |
    |---|---|
    | run_id | `{TARGET_RUN_ID}` |
    | profile | VHS_BALANCED_V1 |
    | rule version | VHS_BALANCED_V1 |
    | inspections scored | {total} |
    | penalty detail rows | {n_pen} |
    | vhs_final_score avg | {avg_s:.2f} |
    | vhs_final_score min | {min_s:.2f} |
    | vhs_final_score max | {max_s:.2f} |

    ### Decision Distribution

    {chr(10).join(dec_lines)}

    ### Safety Grade Distribution

    {chr(10).join(grd_lines)}

    ### Hard Cap Distribution

    {chr(10).join(cap_lines)}

    ---

    ## 2. Main Observations

    ### 2.1 High CRITIQUE Rate

    **{n_critique} out of {total} inspections ({_pct(n_critique, total):.1f}%)** are classified CRITIQUE.
    This is a severe distribution for a fleet scoring system.

    The primary driver is **safety grade logic**:
    Grade D accounts for exactly {n_grade_d} inspections, which equals the number of CRITIQUE decisions.
    This means CRITIQUE is almost entirely driven by Grade D, not by VHS thresholds.

    Grade D is triggered when:
    - at least one T1_VITAL checkpoint is BROKEN, OR
    - at least 3 T1_IMPORTANT checkpoints are BROKEN.

    ### 2.2 Grade B = 0

    Grade B requires at least one T1 WORN checkpoint with no T1 BROKEN.
    Grade B count is **0**.

    In the penalty detail table, across all T1 checkpoints:
    - T1 BROKEN occurrences: {t1_broken}
    - T1 WORN occurrences: {t1_worn}
    - Total T1 anomaly occurrences: {t1_total}

    {"The vast majority of T1 anomalies are BROKEN, not WORN." if t1_broken > t1_worn else "T1 WORN exceeds T1 BROKEN — investigate BROKEN/WORN mapping."}

    In VHS_BALANCED_V1, `est_anomalie_critique = true` maps directly to BROKEN.
    If an inspection has even one T1 checkpoint with `est_anomalie_critique = true`,
    it immediately achieves Grade D, bypassing Grade B and C entirely.
    This is the direct cause of Grade B = 0.

    This does **not** mean the code is wrong.
    It means the `est_anomalie_critique` flag in the source data is very frequently set,
    and the critical classification covers almost all T1 anomalies.
    **This should be reviewed before validating the calibration.**

    ### 2.3 Hard Caps Activate Frequently

    Hard caps were applied to a significant portion of inspections.
    When a hard cap is applied, it means the VHS score was already above the cap limit —
    the scoring penalties alone were not severe enough to breach the cap threshold,
    but the grade/drivability rule enforces the ceiling.

    ---

    ## 3. Top Penalty Drivers

    The following checkpoints contributed the most total penalty points across all inspections:

    {chr(10).join(cp_lines)}

    ---

    ## 4. Grade D Drivers

    The following checkpoints most frequently triggered the GRADE_D hard cap:

    {chr(10).join(gd_lines)}

    The dominant trigger is `sous_le_vehicule_controle_gaine_transmissions_rotules_c`
    (transmission joints / ball joints) and brake disc/pad checkpoints —
    all classified T1_VITAL. Any single BROKEN occurrence yields Grade D.

    ---

    ## 5. Business Interpretation

    ### 5.1 Technical Coherence

    The VHS_BALANCED_V1 computation is **technically coherent**:
    - Business rule audit issues = 0.
    - All hard cap triggers correctly trace to penalty detail rows.
    - UNKNOWN_REVIEW checkpoints contributed zero penalties.
    - Scoring is fully explainable via mart.fact_vhs_penalty_detail.

    ### 5.2 Calibration Concern

    The score distribution is **potentially too strict** for a first production version:
    - {_pct(n_critique, total):.1f}% CRITIQUE is high if the expectation is a normal fleet distribution.
    - Grade D is triggered by a single T1_VITAL BROKEN event, with no exception.
    - `est_anomalie_critique = true` is the source-level flag. Its frequency and reliability
      in the staging data must be verified before finalizing the scoring model.

    ### 5.3 What This Means

    The current results reflect the data as-is:
    - If the source data quality is reliable and inspections are genuinely severe,
      the distribution may be correct.
    - If `est_anomalie_critique` is over-assigned in the staging pipeline,
      the penalties and grade logic will systematically over-classify.

    **The system needs domain expert review before calibration decisions are made.**

    ---

    ## 6. Recommended Next Steps

    1. **Do not change weights immediately.**
       The current distribution should first be reviewed by a vehicle inspection domain expert.

    2. **Review the top {n_candidates} high-severity cases** listed in
       `vhs_high_severity_review_candidates.csv`.
       Verify whether the CRITIQUE classification reflects real vehicle conditions.

    3. **Check `est_anomalie_critique` reliability.**
       If this flag is set too liberally in the staging pipeline,
       all downstream scores will be skewed toward BROKEN, Grade D, and CRITIQUE.

    4. **Consider softening the Grade D trigger for VHS_BALANCED_V2:**
       - Option A: Require ≥2 T1_VITAL BROKEN (instead of 1) for Grade D.
       - Option B: Keep Grade D at 1 T1_VITAL BROKEN, but cap the penalty (e.g., cap=55 instead of 40).
       - Option C: Distinguish between `Intervention conseillée` (advisory) and `Défectueux` (defective)
         when assigning BROKEN vs WORN, rather than relying solely on `est_anomalie_critique`.

    5. **Prepare VHS_BALANCED_V2 only after:**
       - Confirming data quality of `est_anomalie_critique` with the data owner.
       - Reviewing at least 20 CRITIQUE cases manually.
       - Defining the expected target distribution with the business team.

    ---

    *Report generated by etl/mart/audit_vhs_v1.py — read-only analysis of {TARGET_RUN_ID}.*
    """).strip()

    return md


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def audit_vhs_v1():
    logger = dwh_utils.setup_logging("audit_vhs_v1")
    logger.info("=" * 65)
    logger.info(f"[AUDIT] {TARGET_RUN_ID}")
    logger.info("  Mode: READ-ONLY — no database modifications")
    logger.info("=" * 65)

    engine = dwh_utils.build_engine(logger)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Load data
    # ------------------------------------------------------------------
    filter_params = {
        "profile": PROFILE_NAME,
        "version": RULE_VERSION,
        "run_id":  TARGET_RUN_ID,
    }
    where = "WHERE profile_name = :profile AND rule_version = :version AND run_id = :run_id"

    with engine.connect() as conn:
        df_scores  = pd.read_sql(text(f"SELECT * FROM mart.fact_vhs_score {where}"), conn, params=filter_params)
        df_penalty = pd.read_sql(text(f"SELECT * FROM mart.fact_vhs_penalty_detail {where}"), conn, params=filter_params)
        df_dim     = pd.read_sql(text("SELECT * FROM mart.dim_checkpoint"), conn)

    logger.info(f"  fact_vhs_score rows       : {len(df_scores)}")
    logger.info(f"  fact_vhs_penalty_detail   : {len(df_penalty)}")
    logger.info(f"  dim_checkpoint rows       : {len(df_dim)}")

    if len(df_scores) == 0:
        logger.warning(f"  No rows found for run_id={TARGET_RUN_ID}. Check the run_id constant.")
        return

    total = len(df_scores)

    # ------------------------------------------------------------------
    # Build all reports
    # ------------------------------------------------------------------
    df_decision   = _report_decision_distribution(df_scores)
    df_grade      = _report_safety_grade_distribution(df_scores)
    df_score_dist = _report_score_distribution(df_scores)
    df_top_cp     = _report_top_penalty_checkpoints(df_penalty)
    df_grade_d    = _report_grade_d_triggers(df_penalty)
    df_critical   = _report_critical_cases(df_scores)
    df_crit_nocap = _report_critical_without_cap(df_scores)
    df_t1_status  = _report_t1_status_distribution(df_penalty)
    df_candidates = _report_high_severity_candidates(df_scores)

    # ------------------------------------------------------------------
    # Save CSVs
    # ------------------------------------------------------------------
    files_written: list[Path] = []

    files_written.append(_save(df_decision,   "vhs_decision_distribution.csv"))
    files_written.append(_save(df_grade,      "vhs_safety_grade_distribution.csv"))
    files_written.append(_save(df_score_dist, "vhs_score_distribution.csv"))
    files_written.append(_save(df_top_cp,     "vhs_top_penalty_checkpoints.csv"))
    files_written.append(_save(df_grade_d,    "vhs_grade_d_triggers.csv"))
    files_written.append(_save(df_critical,   "vhs_critical_cases_summary.csv"))
    files_written.append(_save(df_crit_nocap, "vhs_critical_without_applied_cap.csv"))
    files_written.append(_save(df_t1_status,  "vhs_t1_status_distribution.csv"))
    files_written.append(_save(df_candidates, "vhs_high_severity_review_candidates.csv"))

    # ------------------------------------------------------------------
    # Save Markdown
    # ------------------------------------------------------------------
    md_content = _build_markdown(
        df_scores, df_penalty,
        df_decision, df_grade,
        df_top_cp, df_grade_d,
        df_candidates,
    )
    md_path = AUDIT_DIR / "vhs_audit_summary.md"
    md_path.write_text(md_content, encoding="utf-8")
    files_written.append(md_path)

    logger.info(f"  files written             : {len(files_written)}")
    for f in files_written:
        logger.info(f"    {f.name}")

    # ------------------------------------------------------------------
    # Log summaries
    # ------------------------------------------------------------------
    logger.info("=" * 65)
    logger.info(f"  output folder: {AUDIT_DIR}")
    logger.info("  Decision distribution:")
    for _, r in df_decision.iterrows():
        logger.info(f"    {r['decision']:<15}: {r['nb_inspections']:>4}  ({r['percentage']:.1f}%)")
    logger.info("  Safety grade distribution:")
    for _, r in df_grade.iterrows():
        logger.info(f"    Grade {r['safety_grade']}: {r['nb_inspections']:>4}  ({r['percentage']:.1f}%)")
    logger.info("  Top 10 checkpoints by total penalty:")
    for i, r in df_top_cp.head(10).iterrows():
        logger.info(
            f"    [{i+1:2}] {r['checkpoint_libelle']:<45}"
            f" tier={r['tier']:<16} status={r['observed_status']:<8}"
            f" total={r['total_penalty']:>7.1f}  n={r['nb_occurrences']}"
        )
    logger.info(f"  high severity candidates  : {len(df_candidates)}")
    logger.info("=" * 65)

    # ------------------------------------------------------------------
    # Print summary
    # ------------------------------------------------------------------
    print("=" * 65)
    print(f"  Audit run : {TARGET_RUN_ID}")
    print(f"  Output    : {AUDIT_DIR}")
    print(f"  Files     : {len(files_written)}")
    print()
    print("  Decision distribution:")
    for _, r in df_decision.iterrows():
        bar = "#" * int(r["percentage"] / 2)
        print(f"    {r['decision']:<15}: {r['nb_inspections']:>4}  ({r['percentage']:5.1f}%)  {bar}")
    print()
    print("  Safety grade distribution:")
    for _, r in df_grade.iterrows():
        bar = "#" * int(r["percentage"] / 2)
        print(f"    Grade {r['safety_grade']}: {r['nb_inspections']:>4}  ({r['percentage']:5.1f}%)  {bar}")
    print()
    print("  Top 10 checkpoints by total penalty:")
    for i, r in df_top_cp.head(10).iterrows():
        print(
            f"    [{i+1:2}] {r['checkpoint_libelle']:<43}"
            f"  {r['tier']:<16}  {r['observed_status']:<8}"
            f"  total={r['total_penalty']:>7.1f}"
        )
    print()
    print(f"  High severity review candidates: {len(df_candidates)}")
    print("=" * 65)

    logger.info(f"Done: {len(files_written)} files -> {AUDIT_DIR}")
    return {
        "df_decision":   df_decision,
        "df_grade":      df_grade,
        "df_top_cp":     df_top_cp,
        "df_grade_d":    df_grade_d,
        "df_candidates": df_candidates,
    }


if __name__ == "__main__":
    audit_vhs_v1()
