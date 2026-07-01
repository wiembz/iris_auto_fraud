"""
etl/mart/audit_vhs_t1_criticality.py
======================================
Read-only diagnostic focused on est_anomalie_critique for T1 checkpoints.

Purpose:
  Determine whether the high CRITIQUE/Grade-D rate in VHS_BALANCED_V1 is driven
  by genuinely broken T1 components or by over-assignment of est_anomalie_critique
  in the source inspection data.

Reads (no writes):
  dwh.fact_inspection_checkpoint
  mart.dim_checkpoint
  mart.fact_vhs_score
  mart.fact_vhs_penalty_detail

Writes (CSV + Markdown only):
  data/quality_reports/vhs/audit_t1_criticality/
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
AUDIT_DIR  = BASE_DIR / "data" / "quality_reports" / "vhs" / "audit_t1_criticality"

TARGET_RUN_ID = "VHS_BALANCED_V1_20260630_103138"
PROFILE_NAME  = "VHS_BALANCED_V1"
RULE_VERSION  = "VHS_BALANCED_V1"

_T1_TIERS = ("T1_VITAL", "T1_IMPORTANT")

# valeur_controle values of interest for overcriticality analysis
_INTERVENTION_VALUE = "Intervention conseillée"


def _save(df: pd.DataFrame, name: str) -> Path:
    path = AUDIT_DIR / name
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _pct(n: int, total: int) -> float:
    return round(100.0 * n / total, 2) if total > 0 else 0.0


# ---------------------------------------------------------------------------
# Report 1 — t1_criticality_by_checkpoint.csv
# ---------------------------------------------------------------------------

def _report_criticality_by_checkpoint(
    df_t1: pd.DataFrame,
    df_penalty: pd.DataFrame,
) -> pd.DataFrame:
    """
    Per T1 checkpoint: total rows, ok/non-critical/critical counts,
    and VHS BROKEN/WORN counts from penalty_detail.
    """
    # Aggregate from source data
    grp = (
        df_t1
        .groupby(["checkpoint_code", "checkpoint_libelle", "tier"])
        .apply(lambda g: pd.Series({
            "total_rows":             len(g),
            "nb_ok":                  int((~g["est_anomalie"] & ~g["est_anomalie_critique"]).sum()),
            "nb_anomalie_non_critique": int((g["est_anomalie"] & ~g["est_anomalie_critique"]).sum()),
            "nb_anomalie_critique":   int(g["est_anomalie_critique"].sum()),
        }), include_groups=False)
        .reset_index()
    )
    grp["pct_anomalie_critique"] = grp.apply(
        lambda r: _pct(int(r["nb_anomalie_critique"]), int(r["total_rows"])), axis=1
    )

    # VHS BROKEN/WORN counts from penalty_detail
    df_pen_t1 = df_penalty[df_penalty["tier"].isin(_T1_TIERS)]
    broken = (
        df_pen_t1[df_pen_t1["observed_status"] == "BROKEN"]
        .groupby("checkpoint_code").size()
        .rename("nb_vhs_broken")
    )
    worn = (
        df_pen_t1[df_pen_t1["observed_status"] == "WORN"]
        .groupby("checkpoint_code").size()
        .rename("nb_vhs_worn")
    )
    grp = grp.merge(broken, on="checkpoint_code", how="left")
    grp = grp.merge(worn,   on="checkpoint_code", how="left")
    grp["nb_vhs_broken"] = grp["nb_vhs_broken"].fillna(0).astype(int)
    grp["nb_vhs_worn"]   = grp["nb_vhs_worn"].fillna(0).astype(int)

    return grp.sort_values(["tier", "nb_anomalie_critique"], ascending=[True, False]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Report 2 — t1_value_control_distribution.csv
# ---------------------------------------------------------------------------

def _report_value_control_distribution(df_t1: pd.DataFrame) -> pd.DataFrame:
    grp = (
        df_t1
        .groupby(
            ["checkpoint_code", "checkpoint_libelle", "tier",
             "valeur_controle", "est_anomalie", "est_anomalie_critique"],
            dropna=False,
        )
        .size()
        .reset_index(name="nb_rows")
    )
    return grp.sort_values(
        ["tier", "checkpoint_code", "nb_rows"], ascending=[True, True, False]
    ).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Report 3 — t1_critical_comments_sample.csv
# ---------------------------------------------------------------------------

def _report_critical_comments_sample(df_t1: pd.DataFrame, limit_per_code: int = 20) -> pd.DataFrame:
    """
    For T1 rows where est_anomalie_critique = true, sample up to
    `limit_per_code` examples per checkpoint_code, preferring non-empty comments.
    """
    df_crit = df_t1[df_t1["est_anomalie_critique"].astype(bool)].copy()

    cols = [
        "inspection_key", "immatriculation_norm",
        "checkpoint_code", "checkpoint_libelle", "tier",
        "valeur_controle", "est_anomalie", "est_anomalie_critique",
        "commentaire_zone",
    ]
    df_crit = df_crit[[c for c in cols if c in df_crit.columns]]

    # Sort so non-null/non-empty comments come first
    has_comment = (
        df_crit["commentaire_zone"].notna() &
        (df_crit["commentaire_zone"].astype(str).str.strip() != "")
    )
    df_crit = df_crit.assign(_has_comment=has_comment)
    df_crit = df_crit.sort_values(
        ["checkpoint_code", "_has_comment"], ascending=[True, False]
    ).drop(columns=["_has_comment"])

    # Take up to limit_per_code per checkpoint
    df_sample = (
        df_crit
        .groupby("checkpoint_code", group_keys=False)
        .apply(lambda g: g.head(limit_per_code))
    )
    return df_sample.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Report 4 — t1_broken_to_grade_d_link.csv
# ---------------------------------------------------------------------------

def _report_grade_d_link(
    df_t1: pd.DataFrame,
    df_scores: pd.DataFrame,
) -> pd.DataFrame:
    """
    For Grade-D inspections, show all T1 anomaly checkpoints that contributed.
    Includes both critical (BROKEN) and non-critical (WORN) rows for full picture.
    """
    grade_d_keys = df_scores.loc[df_scores["safety_grade"] == "D", ["inspection_key", "immatriculation_norm", "vhs_final_score", "safety_grade", "decision"]]

    # Keep T1 rows that have an anomaly for Grade D inspections
    df_anom = df_t1[
        df_t1["inspection_key"].isin(grade_d_keys["inspection_key"]) &
        (df_t1["est_anomalie"].astype(bool) | df_t1["est_anomalie_critique"].astype(bool))
    ]

    cols_from_src = [
        "inspection_key", "checkpoint_code", "checkpoint_libelle", "tier",
        "valeur_controle", "est_anomalie", "est_anomalie_critique", "commentaire_zone",
    ]
    df_anom = df_anom[[c for c in cols_from_src if c in df_anom.columns]]

    # Merge with score metadata
    df_result = df_anom.merge(
        grade_d_keys, on="inspection_key", how="inner"
    )

    output_cols = [
        "inspection_key", "immatriculation_norm", "vhs_final_score",
        "safety_grade", "decision",
        "checkpoint_code", "checkpoint_libelle", "tier",
        "valeur_controle", "est_anomalie", "est_anomalie_critique", "commentaire_zone",
    ]
    df_result = df_result[[c for c in output_cols if c in df_result.columns]]
    return df_result.sort_values(
        ["inspection_key", "tier", "checkpoint_code"]
    ).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Report 5 — t1_possible_overcritical_cases.csv
# ---------------------------------------------------------------------------

def _report_overcritical_cases(df_t1: pd.DataFrame) -> pd.DataFrame:
    """
    T1 rows where valeur_controle = 'Intervention conseillée'
    AND est_anomalie_critique = true.
    These may warrant reclassification as WORN instead of BROKEN.
    """
    mask = (
        df_t1["est_anomalie_critique"].astype(bool) &
        (df_t1["valeur_controle"] == _INTERVENTION_VALUE)
    )
    cols = [
        "inspection_key", "immatriculation_norm",
        "checkpoint_code", "checkpoint_libelle", "tier",
        "valeur_controle", "est_anomalie", "est_anomalie_critique",
        "commentaire_zone",
    ]
    df_oc = df_t1[mask][[c for c in cols if c in df_t1.columns]].copy()
    return df_oc.sort_values(["tier", "checkpoint_code", "inspection_key"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Markdown builder
# ---------------------------------------------------------------------------

def _build_markdown(
    df_t1:       pd.DataFrame,
    df_crit_by_cp: pd.DataFrame,
    df_val_dist: pd.DataFrame,
    df_overcrit: pd.DataFrame,
) -> str:
    total_t1      = len(df_t1)
    n_critique    = int(df_t1["est_anomalie_critique"].sum())
    n_non_crit    = int((df_t1["est_anomalie"] & ~df_t1["est_anomalie_critique"]).sum())
    n_ok          = total_t1 - n_critique - n_non_crit
    pct_critique  = _pct(n_critique, total_t1)
    n_overcrit    = len(df_overcrit)

    # Top checkpoints by critical count
    top_cp = df_crit_by_cp.sort_values("nb_anomalie_critique", ascending=False).head(10)
    cp_lines = ["| checkpoint | tier | nb_critique | pct_critique |", "|---|---|---|---|"]
    for r in top_cp.itertuples():
        cp_lines.append(
            f"| {r.checkpoint_libelle} | {r.tier}"
            f" | {r.nb_anomalie_critique} | {r.pct_anomalie_critique:.1f}% |"
        )

    # valeur_controle behavior for T1
    val_grp = (
        df_t1
        .groupby(["valeur_controle", "est_anomalie_critique"], dropna=False)
        .size()
        .reset_index(name="n")
        .sort_values("n", ascending=False)
    )
    val_lines = ["| valeur_controle | est_anomalie_critique | n |", "|---|---|---|"]
    for r in val_grp.itertuples():
        val_lines.append(f"| {r.valeur_controle} | {r.est_anomalie_critique} | {r.n} |")

    # Overcritical breakdown by checkpoint
    if len(df_overcrit) > 0:
        oc_grp = df_overcrit.groupby(["checkpoint_libelle", "tier"]).size().reset_index(name="n").sort_values("n", ascending=False)
        oc_lines = ["| checkpoint | tier | nb_intervention_critique |", "|---|---|---|"]
        for r in oc_grp.itertuples():
            oc_lines.append(f"| {r.checkpoint_libelle} | {r.tier} | {r.n} |")
    else:
        oc_lines = ["No cases found where valeur_controle = 'Intervention conseillée' with est_anomalie_critique = true."]

    md = dedent(f"""
    # T1 Criticality Diagnostic — {TARGET_RUN_ID}

    ---

    ## 1. Context

    VHS_BALANCED_V1 is **technically coherent** (0 business rule audit issues).
    However, the decision distribution is severe:
    - CRITIQUE = 54.9% (157 / 286 inspections)
    - Grade D = 54.9% — CRITIQUE is exclusively safety-grade-driven
    - Grade B = 0 — no inspection has only non-critical T1 anomalies

    This diagnostic investigates whether `est_anomalie_critique = true` in the source
    inspection data is proportionate to the actual vehicle condition.

    The core question:
    > **Is `est_anomalie_critique` over-assigned in the staging data,
    > or do these inspections genuinely reflect critical defects?**

    ---

    ## 2. T1 Criticality Distribution

    | Metric | Value |
    |---|---|
    | T1 checkpoint rows (all observations) | {total_t1} |
    | T1 rows: OK (no anomaly) | {n_ok} |
    | T1 rows: WORN (non-critical anomaly) | {n_non_crit} |
    | T1 rows: BROKEN (critical anomaly) | {n_critique} |
    | % of T1 rows that are critical | {pct_critique:.1f}% |

    ### Top T1 Checkpoints by Critical Anomaly Count

    {chr(10).join(cp_lines)}

    ---

    ## 3. valeur_controle Interpretation for T1 Checkpoints

    The table below shows how `valeur_controle` values map to `est_anomalie_critique`
    for T1 checkpoints only.

    {chr(10).join(val_lines)}

    ### Key observations:

    - **`Intervention conseillée`** — literally means "intervention recommended".
      This is an advisory flag. If `est_anomalie_critique = true` for these rows,
      it means the inspector marked the intervention as urgent/safety-critical.
      This is the most ambiguous case: an "advisory" combined with a "critical" flag
      could indicate either genuine urgency or systematic over-flagging.

    - **`Contrôle non OK`** — control not OK. More likely to reflect a real defect.

    - **`Défectueux`** — defective. Strongest wording; critical flag is most justified here.

    - **`NON`** — negative result, usually non-critical. Appears with est_anomalie=true only.

    - **`Proposition faite` / `PROPOSITION FAITE`** — proposal made (for repair/replacement).
      May or may not be critical depending on inspector assessment.

    ---

    ## 4. Possible Overcriticality — `Intervention conseillée` with est_anomalie_critique = true

    Total cases: **{n_overcrit}**

    These are T1 checkpoints where the valeur_controle says "Intervention conseillée"
    (advisory) but est_anomalie_critique is set to true (critical/BROKEN in VHS).

    {chr(10).join(oc_lines)}

    ### Why this matters:

    In VHS_BALANCED_V1, the normalization rule is:
    - `est_anomalie_critique = true` → `observed_status = BROKEN` → `penalty_broken`

    If "Intervention conseillée" should semantically be WORN (advisory) rather than BROKEN
    (immediate danger), then these {n_overcrit} cases would be over-penalized.

    However, the VHS specification uses `est_anomalie_critique` as the authoritative flag
    regardless of the text label — this is correct if the inspector workflow guarantees
    that `est_anomalie_critique` is only set for genuinely critical defects.

    The question to validate with domain experts:
    > **Can an inspector set `est_anomalie_critique = true` while writing
    > "Intervention conseillée" (advisory), and is that intentional?**

    ---

    ## 5. Recommendations

    Do not change VHS weights, penalties, or tier classifications before answering:

    ### Option A — Keep current mapping (no change)
    If the business confirms that `est_anomalie_critique = true` always reflects a
    genuine safety-critical defect regardless of valeur_controle text, then the
    current scoring is correct.
    The CRITIQUE rate reflects the actual fleet condition.

    ### Option B — Differentiate by valeur_controle text
    Map `est_anomalie_critique = true` + `valeur_controle = 'Intervention conseillée'`
    to a new status `WORN_STRONG` with a penalty between `penalty_worn` and `penalty_broken`.
    This would prevent BROKEN classification for advisory-level critical flags.
    **This requires updating `normalize_observed_status` in `compute_vhs.py`.**

    ### Option C — Tighten the Grade D condition
    Require ≥2 T1_VITAL BROKEN (instead of 1) before assigning Grade D.
    This would reduce Grade D / CRITIQUE counts without changing individual penalties.
    **This requires updating `_compute_grade` in `compute_vhs.py`.**

    ### Recommended sequence:
    1. Share `t1_possible_overcritical_cases.csv` and `t1_broken_to_grade_d_link.csv`
       with the domain expert / inspection data owner.
    2. Validate whether `est_anomalie_critique` is systematically over-assigned
       for `Intervention conseillée` rows.
    3. Decide on Option A, B, or C (or a combination).
    4. Implement as VHS_BALANCED_V2 only after validation.

    ---

    *Generated by etl/mart/audit_vhs_t1_criticality.py — read-only, no DB modifications.*
    """).strip()

    return md


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def audit_vhs_t1_criticality():
    logger = dwh_utils.setup_logging("audit_t1_criticality")
    logger.info("=" * 65)
    logger.info(f"[T1 CRITICALITY AUDIT] {TARGET_RUN_ID}")
    logger.info("  Mode: READ-ONLY — no database modifications")
    logger.info("=" * 65)

    engine = dwh_utils.build_engine(logger)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    run_params = {
        "profile": PROFILE_NAME,
        "version": RULE_VERSION,
        "run_id":  TARGET_RUN_ID,
    }
    run_where = "WHERE profile_name = :profile AND rule_version = :version AND run_id = :run_id"

    # ------------------------------------------------------------------
    # Load data
    # ------------------------------------------------------------------
    with engine.connect() as conn:
        # T1 dim_checkpoint codes
        df_dim_t1 = pd.read_sql(
            text("SELECT checkpoint_code, checkpoint_libelle, tier FROM mart.dim_checkpoint WHERE tier IN ('T1_VITAL', 'T1_IMPORTANT')"),
            conn,
        )
        t1_codes = tuple(df_dim_t1["checkpoint_code"].tolist())

        # All T1 checkpoint observations from source
        df_src = pd.read_sql(
            text("""
                SELECT
                    fic.inspection_key,
                    fic.immatriculation_norm,
                    fic.checkpoint_code,
                    fic.checkpoint_libelle,
                    fic.valeur_controle,
                    fic.est_anomalie,
                    fic.est_anomalie_critique,
                    fic.est_controle_renseigne,
                    fic.commentaire_zone
                FROM dwh.fact_inspection_checkpoint fic
                INNER JOIN mart.dim_checkpoint dc ON dc.checkpoint_code = fic.checkpoint_code
                WHERE dc.tier IN ('T1_VITAL', 'T1_IMPORTANT')
                ORDER BY fic.inspection_key, dc.tier, fic.checkpoint_code
            """),
            conn,
        )
        # Add tier from dim
        df_src = df_src.merge(
            df_dim_t1[["checkpoint_code", "tier"]],
            on="checkpoint_code", how="left",
        )

        # VHS scores
        df_scores = pd.read_sql(
            text(f"SELECT * FROM mart.fact_vhs_score {run_where}"),
            conn, params=run_params,
        )

        # Penalty detail (T1 only)
        df_penalty = pd.read_sql(
            text(f"""
                SELECT * FROM mart.fact_vhs_penalty_detail
                {run_where}
                  AND tier IN ('T1_VITAL', 'T1_IMPORTANT')
            """),
            conn, params=run_params,
        )

    # Ensure boolean columns are plain bool (DB may return nullable object with None)
    for col in ["est_anomalie", "est_anomalie_critique", "est_controle_renseigne"]:
        if col in df_src.columns:
            df_src[col] = df_src[col].fillna(False).astype(bool)

    logger.info(f"  T1 checkpoint observations : {len(df_src)}")
    logger.info(f"  VHS score rows             : {len(df_scores)}")
    logger.info(f"  T1 penalty detail rows     : {len(df_penalty)}")

    # ------------------------------------------------------------------
    # Build reports
    # ------------------------------------------------------------------
    df_crit_by_cp = _report_criticality_by_checkpoint(df_src, df_penalty)
    df_val_dist   = _report_value_control_distribution(df_src)
    df_comments   = _report_critical_comments_sample(df_src)
    df_grade_d    = _report_grade_d_link(df_src, df_scores)
    df_overcrit   = _report_overcritical_cases(df_src)

    # ------------------------------------------------------------------
    # Save CSVs
    # ------------------------------------------------------------------
    files_written: list[Path] = []
    files_written.append(_save(df_crit_by_cp, "t1_criticality_by_checkpoint.csv"))
    files_written.append(_save(df_val_dist,   "t1_value_control_distribution.csv"))
    files_written.append(_save(df_comments,   "t1_critical_comments_sample.csv"))
    files_written.append(_save(df_grade_d,    "t1_broken_to_grade_d_link.csv"))
    files_written.append(_save(df_overcrit,   "t1_possible_overcritical_cases.csv"))

    # ------------------------------------------------------------------
    # Save Markdown
    # ------------------------------------------------------------------
    md_content = _build_markdown(df_src, df_crit_by_cp, df_val_dist, df_overcrit)
    md_path = AUDIT_DIR / "t1_audit_summary.md"
    md_path.write_text(md_content, encoding="utf-8")
    files_written.append(md_path)

    # ------------------------------------------------------------------
    # Log summaries
    # ------------------------------------------------------------------
    total_t1   = len(df_src)
    n_critique = int(df_src["est_anomalie_critique"].sum())
    n_overcrit = len(df_overcrit)

    logger.info("=" * 65)
    logger.info(f"  output folder              : {AUDIT_DIR}")
    logger.info(f"  files generated            : {len(files_written)}")
    logger.info(f"  T1 total rows              : {total_t1}")
    logger.info(f"  T1 critical anomalies      : {n_critique}  ({_pct(n_critique, total_t1):.1f}%)")
    logger.info(f"  possible overcritical cases: {n_overcrit}  (Intervention conseillée + critique)")
    logger.info("  Top 10 T1 checkpoints by critical anomaly count:")
    top10 = df_crit_by_cp.sort_values("nb_anomalie_critique", ascending=False).head(10)
    for r in top10.itertuples():
        logger.info(
            f"    {r.checkpoint_libelle:<45}"
            f"  {r.tier:<16}"
            f"  n_crit={r.nb_anomalie_critique:>4}"
            f"  ({r.pct_anomalie_critique:.1f}%)"
        )
    logger.info("=" * 65)
    for f in files_written:
        logger.info(f"  {f.name}")
    logger.info(f"Done: {len(files_written)} files -> {AUDIT_DIR}")

    # ------------------------------------------------------------------
    # Print
    # ------------------------------------------------------------------
    print("=" * 65)
    print(f"  T1 Criticality Audit: {TARGET_RUN_ID}")
    print(f"  Output folder : {AUDIT_DIR}")
    print(f"  Files written : {len(files_written)}")
    print()
    print(f"  T1 total rows          : {total_t1}")
    print(f"  T1 critical anomalies  : {n_critique}  ({_pct(n_critique, total_t1):.1f}%)")
    print(f"  Possible overcritical  : {n_overcrit}  (Intervention conseillée + est_anomalie_critique=true)")
    print()
    print("  Top 10 T1 checkpoints by critical anomaly count:")
    for i, r in enumerate(top10.itertuples(), 1):
        print(
            f"    [{i:2}] {r.checkpoint_libelle:<43}"
            f"  {r.tier:<16}"
            f"  n_crit={r.nb_anomalie_critique:>4}"
            f"  ({r.pct_anomalie_critique:.1f}%)"
        )
    print("=" * 65)

    return {
        "df_crit_by_cp": df_crit_by_cp,
        "df_overcrit":   df_overcrit,
        "df_grade_d":    df_grade_d,
    }


if __name__ == "__main__":
    audit_vhs_t1_criticality()
