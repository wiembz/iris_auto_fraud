"""
etl/mart/audit_vhs_v2_severe_cases.py
======================================
Read-only audit focused on the remaining CRITIQUE and IMMOBILISE cases
in VHS_BALANCED_V2, and whether they are justified.

Purpose:
  V2 reduced CRITIQUE from 157 to 51 and IMMOBILISE from 5 to 1.
  This script explains the remaining severe cases before V2 validation.

Reads (no writes):
  mart.fact_vhs_score
  mart.fact_vhs_penalty_detail
  mart.dim_checkpoint
  dwh.fact_inspection_checkpoint
  dwh.fact_inspection_vehicule

Writes (CSV + Markdown only):
  data/quality_reports/vhs/audit_vhs_v2_severe_cases/
"""
from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dwh"))
import dwh_utils

BASE_DIR   = Path(__file__).resolve().parent.parent.parent
AUDIT_DIR  = BASE_DIR / "data" / "quality_reports" / "vhs" / "audit_vhs_v2_severe_cases"

RUN_ID       = "VHS_BALANCED_V2_20260630_133318"
PROFILE_NAME = "VHS_BALANCED_V2"
RULE_VERSION = "VHS_BALANCED_V2"

_RUN_PARAMS = {"profile": PROFILE_NAME, "version": RULE_VERSION, "run_id": RUN_ID}
_RUN_WHERE  = "WHERE profile_name = :profile AND rule_version = :version AND run_id = :run_id"


def _save(df: pd.DataFrame, name: str) -> Path:
    p = AUDIT_DIR / name
    df.to_csv(p, index=False, encoding="utf-8-sig")
    return p


def _pct(n: int, total: int) -> str:
    return f"{round(100.0 * n / total, 1):.1f}%" if total else "0.0%"


# ---------------------------------------------------------------------------
# severe_reason builder
# ---------------------------------------------------------------------------

def _build_severe_reason(row: pd.Series, pen_det: pd.DataFrame) -> str:
    """
    Build a human-readable reason for why this inspection is severe.
    pen_det is already filtered to this inspection_key.
    """
    parts: list[str] = []
    decision    = row["decision"]
    grade       = row["safety_grade"]
    drivable    = row["is_drivable"]
    score       = float(row["vhs_final_score"]) if pd.notna(row["vhs_final_score"]) else 100.0
    cap_type    = row.get("hard_cap_type")

    if len(pen_det) == 0:
        if not drivable:
            return "Immobilized (no penalty detail rows)"
        return "Very low score (no penalties logged)"

    # Grade D logic
    if grade == "D":
        vital_broken = pen_det[
            (pen_det["tier"] == "T1_VITAL") &
            (pen_det["observed_status"] == "BROKEN")
        ]
        imp_broken = pen_det[
            (pen_det["tier"] == "T1_IMPORTANT") &
            (pen_det["observed_status"] == "BROKEN")
        ]
        if len(vital_broken) > 0:
            cp_names = vital_broken["checkpoint_libelle"].dropna().unique()[:2]
            parts.append(
                "Grade D from T1_VITAL BROKEN: " + ", ".join(f"'{c}'" for c in cp_names)
            )
        elif len(imp_broken) >= 3:
            parts.append(f"Grade D from {len(imp_broken)} T1_IMPORTANT BROKEN checkpoints")
        else:
            parts.append("Critical decision from safety grade D")

    # Immobilized
    if not drivable:
        immo_rows = pen_det[
            pen_det["is_immobilizing"].astype(bool) &
            (pen_det["observed_status"] == "BROKEN")
        ]
        if len(immo_rows) > 0:
            cp = immo_rows.iloc[0]["checkpoint_libelle"]
            parts.append(f"Immobilized from '{cp}' (is_immobilizing BROKEN)")
        else:
            parts.append("Not drivable (immobilizing checkpoint BROKEN)")

    # Low score
    if score < 40:
        parts.append(f"Very low score ({score:.1f} < 40)")

    return "; ".join(parts) if parts else f"Severe: decision={decision} grade={grade}"


# ---------------------------------------------------------------------------
# Report 1 — v2_severe_cases_summary.csv
# ---------------------------------------------------------------------------

def _report_severe_summary(
    df_scores: pd.DataFrame,
    df_penalty_all: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.Index]:
    severe = df_scores[
        df_scores["decision"].isin(["CRITIQUE", "IMMOBILISE"]) |
        (df_scores["safety_grade"] == "D") |
        df_scores["hard_cap_type"].isin(["GRADE_D", "IMMOBILIZED"])
    ].copy()

    reasons = []
    for _, row in severe.iterrows():
        pen_det = df_penalty_all[df_penalty_all["inspection_key"] == row["inspection_key"]]
        reasons.append(_build_severe_reason(row, pen_det))
    severe["severe_reason"] = reasons

    cols = [
        "inspection_key", "immatriculation_norm", "kilometrage",
        "vhs_raw_score", "kilometrage_penalty", "vhs_before_cap", "vhs_final_score",
        "safety_grade", "decision", "is_drivable", "hard_cap_applied", "hard_cap_type",
        "nb_anomalies_total", "nb_anomalies_critiques", "nb_penalties_applied",
        "severe_reason",
    ]
    df_out = severe[[c for c in cols if c in severe.columns]].reset_index(drop=True)
    return df_out, severe["inspection_key"]


# ---------------------------------------------------------------------------
# Report 2 — v2_severe_penalty_details.csv
# ---------------------------------------------------------------------------

def _report_severe_penalty_details(
    df_penalty_all: pd.DataFrame,
    severe_keys: pd.Index,
    df_scores: pd.DataFrame,
) -> pd.DataFrame:
    df = df_penalty_all[df_penalty_all["inspection_key"].isin(severe_keys)].copy()
    immat_map = df_scores.set_index("inspection_key")["immatriculation_norm"].to_dict()
    df["immatriculation_norm"] = df["inspection_key"].map(immat_map)

    cols = [
        "inspection_key", "immatriculation_norm",
        "checkpoint_code", "checkpoint_libelle", "zone_controle",
        "tier", "observed_value", "observed_status",
        "penalty_applied", "penalty_reason",
        "is_vital", "is_important", "is_critical_functional", "is_immobilizing",
        "is_hard_cap_trigger", "hard_cap_type",
    ]
    df_out = df[[c for c in cols if c in df.columns]].copy()
    df_out = df_out.sort_values(
        ["inspection_key", "is_hard_cap_trigger", "penalty_applied"],
        ascending=[True, False, False],
    ).reset_index(drop=True)
    return df_out


# ---------------------------------------------------------------------------
# Report 3 — v2_grade_d_drivers.csv
# ---------------------------------------------------------------------------

def _report_grade_d_drivers(
    df_penalty_all: pd.DataFrame,
    df_scores: pd.DataFrame,
) -> pd.DataFrame:
    grade_d_keys = df_scores.loc[df_scores["safety_grade"] == "D", "inspection_key"]

    # Filter: is_hard_cap_trigger GRADE_D rows OR T1_VITAL BROKEN in Grade D inspections
    mask = (
        ((df_penalty_all["is_hard_cap_trigger"].astype(bool)) &
         (df_penalty_all["hard_cap_type"] == "GRADE_D"))
        |
        (
            df_penalty_all["inspection_key"].isin(grade_d_keys) &
            (df_penalty_all["tier"] == "T1_VITAL") &
            (df_penalty_all["observed_status"] == "BROKEN")
        )
    )
    df_d = df_penalty_all[mask].copy()

    grp = (
        df_d.groupby(["checkpoint_code", "checkpoint_libelle", "tier", "observed_status"])
        .agg(
            nb_occurrences=("inspection_key", "count"),
            total_penalty=("penalty_applied", "sum"),
            avg_penalty=("penalty_applied", "mean"),
        )
        .reset_index()
    )
    grp["total_penalty"] = grp["total_penalty"].round(2)
    grp["avg_penalty"]   = grp["avg_penalty"].round(2)
    return grp.sort_values("nb_occurrences", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Report 4 — v2_immobilized_driver.csv
# ---------------------------------------------------------------------------

def _report_immobilized_driver(
    df_scores: pd.DataFrame,
    df_penalty_all: pd.DataFrame,
) -> pd.DataFrame:
    immo_keys = df_scores.loc[df_scores["decision"] == "IMMOBILISE", "inspection_key"]
    if len(immo_keys) == 0:
        return pd.DataFrame(columns=[
            "inspection_key", "immatriculation_norm", "kilometrage",
            "vhs_final_score", "safety_grade", "decision",
            "checkpoint_code", "checkpoint_libelle", "tier",
            "observed_value", "observed_status", "penalty_applied",
            "is_immobilizing", "hard_cap_type", "penalty_reason",
        ])

    df_pen = df_penalty_all[df_penalty_all["inspection_key"].isin(immo_keys)].copy()
    score_cols = df_scores.loc[
        df_scores["inspection_key"].isin(immo_keys),
        ["inspection_key", "immatriculation_norm", "kilometrage", "vhs_final_score", "safety_grade", "decision"],
    ]

    df_out = df_pen.merge(score_cols, on="inspection_key", how="left")

    cols = [
        "inspection_key", "immatriculation_norm", "kilometrage",
        "vhs_final_score", "safety_grade", "decision",
        "checkpoint_code", "checkpoint_libelle", "tier",
        "observed_value", "observed_status", "penalty_applied",
        "is_immobilizing", "hard_cap_type", "penalty_reason",
    ]
    return df_out[[c for c in cols if c in df_out.columns]].sort_values(
        ["inspection_key", "penalty_applied"], ascending=[True, False]
    ).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Report 5 — v2_critical_case_explanations.csv
# ---------------------------------------------------------------------------

def _build_explanation(key: str, row: pd.Series, pen_det: pd.DataFrame) -> dict:
    grade    = row["safety_grade"]
    decision = row["decision"]
    cap_type = row.get("hard_cap_type", None)
    score    = float(row["vhs_final_score"]) if pd.notna(row["vhs_final_score"]) else 0.0

    if len(pen_det) == 0:
        top_cp = top_val = top_st = ""
        top_pen = 0.0
    else:
        # Top trigger = highest penalty among is_hard_cap_trigger=True, fallback to all
        triggers = pen_det[pen_det["is_hard_cap_trigger"].astype(bool)]
        top_pool = triggers if len(triggers) > 0 else pen_det
        top_row  = top_pool.sort_values("penalty_applied", ascending=False).iloc[0]
        top_cp   = top_row.get("checkpoint_libelle", "")
        top_val  = top_row.get("observed_value", "")
        top_st   = top_row.get("observed_status", "")
        top_pen  = float(top_row.get("penalty_applied", 0.0))

    t1v_broken = int(
        ((pen_det["tier"] == "T1_VITAL") & (pen_det["observed_status"] == "BROKEN")).sum()
    ) if len(pen_det) else 0
    t1i_broken = int(
        ((pen_det["tier"] == "T1_IMPORTANT") & (pen_det["observed_status"] == "BROKEN")).sum()
    ) if len(pen_det) else 0
    nb_ws      = int((pen_det["observed_status"] == "WORN_STRONG").sum()) if len(pen_det) else 0
    nb_broken  = int((pen_det["observed_status"] == "BROKEN").sum())      if len(pen_det) else 0
    nb_worn    = int((pen_det["observed_status"] == "WORN").sum())         if len(pen_det) else 0

    # Build explanation text
    if grade == "D":
        if t1v_broken >= 1:
            text = f"CRITIQUE because T1_VITAL checkpoint '{top_cp}' is BROKEN."
        elif t1i_broken >= 3:
            text = f"CRITIQUE because {t1i_broken} T1_IMPORTANT checkpoints are BROKEN."
        else:
            text = f"CRITIQUE due to Grade D safety rule (grade={grade}, score={score:.1f})."
    elif decision == "CRITIQUE":
        text = f"CRITIQUE due to Grade D safety rule (score={score:.1f})."
    else:
        text = f"Severe due to hard cap {cap_type} (score={score:.1f})."

    return {
        "inspection_key":         key,
        "immatriculation_norm":   row.get("immatriculation_norm"),
        "vhs_final_score":        score,
        "safety_grade":           grade,
        "decision":               decision,
        "hard_cap_type":          cap_type,
        "top_trigger_checkpoint": top_cp,
        "top_trigger_value":      top_val,
        "top_trigger_status":     top_st,
        "top_trigger_penalty":    round(top_pen, 2),
        "nb_t1_vital_broken":     t1v_broken,
        "nb_t1_important_broken": t1i_broken,
        "nb_worn_strong":         nb_ws,
        "nb_broken":              nb_broken,
        "nb_worn":                nb_worn,
        "explanation_text":       text,
    }


def _report_critical_explanations(
    df_scores: pd.DataFrame,
    df_penalty_all: pd.DataFrame,
) -> pd.DataFrame:
    critique_rows = df_scores[df_scores["decision"] == "CRITIQUE"]
    records = []
    for _, row in critique_rows.iterrows():
        key     = row["inspection_key"]
        pen_det = df_penalty_all[df_penalty_all["inspection_key"] == key]
        records.append(_build_explanation(key, row, pen_det))
    return pd.DataFrame(records) if records else pd.DataFrame()


# ---------------------------------------------------------------------------
# Report 6 — v2_worn_strong_effect_on_severe_cases.csv
# ---------------------------------------------------------------------------

def _report_worn_strong_effect(
    df_scores: pd.DataFrame,
    df_penalty_all: pd.DataFrame,
    severe_keys: pd.Index,
) -> pd.DataFrame:
    df_sev = df_scores[df_scores["inspection_key"].isin(severe_keys)].copy()
    df_pen_sev = df_penalty_all[
        df_penalty_all["inspection_key"].isin(severe_keys) &
        (df_penalty_all["observed_status"] == "WORN_STRONG")
    ]

    if len(df_pen_sev) > 0:
        ws_count = df_pen_sev.groupby("inspection_key").size().rename("nb_worn_strong")
        ws_pen   = df_pen_sev.groupby("inspection_key")["penalty_applied"].sum().rename("total_worn_strong_penalty")
        ws_cps   = df_pen_sev.groupby("inspection_key")["checkpoint_libelle"].apply(
            lambda x: "; ".join(x.dropna().unique()[:5])
        ).rename("worn_strong_checkpoints")
        ws_df = pd.concat([ws_count, ws_pen, ws_cps], axis=1).reset_index()
    else:
        ws_df = pd.DataFrame(columns=["inspection_key", "nb_worn_strong",
                                       "total_worn_strong_penalty", "worn_strong_checkpoints"])

    df_out = df_sev[["inspection_key", "immatriculation_norm", "decision", "safety_grade"]].merge(
        ws_df, on="inspection_key", how="left"
    )
    df_out["nb_worn_strong"]           = df_out["nb_worn_strong"].fillna(0).astype(int)
    df_out["total_worn_strong_penalty"] = df_out["total_worn_strong_penalty"].fillna(0.0).round(2)
    df_out["worn_strong_checkpoints"]  = df_out["worn_strong_checkpoints"].fillna("")

    return df_out.sort_values(["nb_worn_strong", "decision"], ascending=[False, True]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Markdown builder
# ---------------------------------------------------------------------------

def _build_markdown(
    df_severe: pd.DataFrame,
    df_grade_d: pd.DataFrame,
    df_immo: pd.DataFrame,
    df_expl: pd.DataFrame,
    df_ws_effect: pd.DataFrame,
) -> str:
    n_severe   = len(df_severe)
    n_critique = int((df_severe["decision"] == "CRITIQUE").sum())
    n_immo     = int((df_severe["decision"] == "IMMOBILISE").sum())
    n_grade_d  = int((df_severe["safety_grade"] == "D").sum())

    scores = df_severe["vhs_final_score"].dropna()
    avg_s  = round(scores.mean(), 2) if len(scores) else 0.0
    min_s  = round(scores.min(), 2)  if len(scores) else 0.0
    max_s  = round(scores.max(), 2)  if len(scores) else 0.0

    # Top Grade D drivers
    if len(df_grade_d) > 0:
        d_lines = ["| Checkpoint | Tier | Status | Occurrences | Total Penalty |", "|---|---|---|---|---|"]
        for r in df_grade_d.head(10).itertuples():
            d_lines.append(
                f"| {r.checkpoint_libelle} | {r.tier} | {r.observed_status}"
                f" | {r.nb_occurrences} | {r.total_penalty:.2f} |"
            )
    else:
        d_lines = ["No Grade D driver rows found."]

    # IMMOBILISE driver
    if len(df_immo) > 0:
        immo_keys = df_immo["inspection_key"].unique()
        immo_rows = df_immo[df_immo["is_immobilizing"].astype(bool)]
        if len(immo_rows) > 0:
            immo_line = "; ".join(
                f"'{r['checkpoint_libelle']}' ({r['observed_status']})"
                for _, r in immo_rows.drop_duplicates("checkpoint_code").iterrows()
            )
        else:
            immo_line = "No immobilizing BROKEN rows (drivability from compound logic)"
        immo_detail = (
            f"- Inspection key(s): {', '.join(str(k) for k in immo_keys)}\n"
            f"- Immobilizing checkpoint(s): {immo_line}"
        )
    else:
        immo_detail = "No IMMOBILISE cases found in V2 (count = 0)."

    # CRITIQUE analysis
    if len(df_expl) > 0:
        nb_from_vital_broken   = int((df_expl["nb_t1_vital_broken"] >= 1).sum())
        nb_from_import_broken  = int((df_expl["nb_t1_important_broken"] >= 3).sum())
        nb_with_ws_in_critique = int((df_ws_effect[df_ws_effect["decision"] == "CRITIQUE"]["nb_worn_strong"] > 0).sum()) if len(df_ws_effect) else 0
        nb_ws_only_in_critique = int(
            (df_ws_effect[df_ws_effect["decision"] == "CRITIQUE"]["nb_worn_strong"] > 0).sum() if len(df_ws_effect) else 0
        )

        critique_breakdown = (
            f"- {nb_from_vital_broken} / {n_critique} CRITIQUE cases driven by T1_VITAL BROKEN\n"
            f"- {nb_from_import_broken} / {n_critique} CRITIQUE cases driven by T1_IMPORTANT BROKEN (≥3)\n"
            f"- {nb_with_ws_in_critique} / {n_critique} CRITIQUE cases still contain WORN_STRONG rows\n"
        )
    else:
        critique_breakdown = "No CRITIQUE cases to analyze."
        nb_from_vital_broken = 0
        nb_with_ws_in_critique = 0

    # Recommendation logic
    if n_critique > 0:
        pct_vital_driven = round(100.0 * nb_from_vital_broken / n_critique, 1) if n_critique else 0
        if pct_vital_driven >= 70:
            recommendation = (
                "**A — V2 is acceptable as candidate.**\n\n"
                f"{pct_vital_driven:.0f}% of CRITIQUE cases are driven by confirmed T1_VITAL BROKEN defects. "
                "These represent genuinely dangerous vehicles. V2 scoring is justified."
            )
        elif nb_with_ws_in_critique > n_critique * 0.4:
            recommendation = (
                "**B — Prepare V3 with refined WORN_STRONG scope.**\n\n"
                f"{nb_with_ws_in_critique} / {n_critique} remaining CRITIQUE cases still contain WORN_STRONG rows. "
                "Consider tightening the Grade D condition (e.g., require ≥2 T1_VITAL BROKEN) in V3."
            )
        else:
            recommendation = (
                "**A — V2 is likely acceptable, pending domain expert review.**\n\n"
                f"Most CRITIQUE cases appear justified. {nb_with_ws_in_critique} cases have residual WORN_STRONG "
                "rows but are primarily driven by confirmed BROKEN defects."
            )
    else:
        recommendation = "**No CRITIQUE cases. V2 appears appropriate.**"

    immo_recommendation = ""
    if n_immo > 0 and len(df_immo) > 0:
        immo_ws_rows = df_immo[df_immo.get("observed_status", pd.Series(dtype=str)) == "WORN_STRONG"] if "observed_status" in df_immo.columns else pd.DataFrame()
        if len(immo_ws_rows) > 0:
            immo_recommendation = (
                "\n\n**C — Review immobilization logic separately.**\n\n"
                "The remaining IMMOBILISE case involves WORN_STRONG rows. "
                "If the immobilizing checkpoint was marked 'Intervention conseillée', "
                "consider whether advisory wording should be exempt from immobilization in V3."
            )
        else:
            immo_recommendation = (
                "\n\n**IMMOBILISE case is driven by confirmed BROKEN on an immobilizing checkpoint.** "
                "This is justified under current V2 logic."
            )

    md = dedent(f"""
    # VHS_BALANCED_V2 — Severe Cases Audit

    ---

    ## 1. Context

    VHS_BALANCED_V1 produced CRITIQUE=157 (54.9%) and IMMOBILISE=5, which were considered too severe.
    VHS_BALANCED_V2 introduced the `WORN_STRONG` status to downgrade advisory critical anomalies
    (`Intervention conseillée` + `est_anomalie_critique=true`) from BROKEN to an intermediate state.

    V2 results:
    - CRITIQUE reduced from **157 → 51** (−67%)
    - IMMOBILISE reduced from **5 → 1** (−80%)
    - 269 WORN_STRONG rows created

    This audit validates whether the remaining {n_severe} severe cases are justified.

    Run ID audited: `{RUN_ID}`

    ---

    ## 2. Severe Case Overview

    | Metric | Value |
    |---|---|
    | Total severe cases | {n_severe} |
    | CRITIQUE | {n_critique} |
    | IMMOBILISE | {n_immo} |
    | Safety Grade D | {n_grade_d} |
    | Average VHS score | {avg_s} |
    | Min VHS score | {min_s} |
    | Max VHS score | {max_s} |

    All CRITIQUE cases have safety_grade = D in V2.

    ---

    ## 3. Main Grade D Drivers

    These checkpoints are responsible for Grade D assignments in V2.

    {chr(10).join(d_lines)}

    ---

    ## 4. Remaining IMMOBILISE Case

    {immo_detail}

    An IMMOBILISE decision means the vehicle has at least one `is_immobilizing = true` checkpoint
    with `observed_status = BROKEN`. WORN_STRONG rows do NOT trigger immobilization.

    ---

    ## 5. CRITIQUE Case Interpretation

    {critique_breakdown}

    ### V2 CRITIQUE analysis:
    - A vehicle reaches CRITIQUE if and only if safety_grade = D.
    - Grade D is triggered by: **≥1 T1_VITAL BROKEN** OR **≥3 T1_IMPORTANT BROKEN**.
    - WORN_STRONG rows (advisory criticals) are NOT a Grade D trigger — they lead to Grade C at most.
    - Therefore, all remaining CRITIQUE cases have at least one **confirmed** BROKEN T1 checkpoint.

    The question is whether `observed_status = BROKEN` reflects a genuinely critical defect.
    In V2, BROKEN is only assigned when `valeur_controle` uses wording like
    `Défectueux`, `Contrôle non OK`, or `Proposition faite` — not advisory language.

    ---

    ## 6. Recommendation

    {recommendation}{immo_recommendation}

    ### Next steps:
    1. Share `v2_critical_case_explanations.csv` and `v2_grade_d_drivers.csv`
       with the domain expert / inspection data owner.
    2. Confirm that `Défectueux` / `Contrôle non OK` on T1_VITAL checkpoints
       always represents a confirmed dangerous defect (not an advisory).
    3. If accepted, proceed to formal V2 validation.
    4. If residual ambiguity remains, define V3 refinements (tighter Grade D condition
       or additional WORN_STRONG-like mapping for other advisory values).

    ---

    *Generated by etl/mart/audit_vhs_v2_severe_cases.py — read-only, no DB modifications.*
    """).strip()

    return md


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def audit_vhs_v2_severe_cases():
    logger = dwh_utils.setup_logging("audit_vhs_v2_severe")
    logger.info("=" * 65)
    logger.info(f"[V2 SEVERE CASES AUDIT] {RUN_ID}")
    logger.info("  Mode: READ-ONLY — no database modifications")
    logger.info("=" * 65)

    engine = dwh_utils.build_engine(logger)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Load data
    # ------------------------------------------------------------------
    with engine.connect() as conn:
        df_scores = pd.read_sql(
            text(f"SELECT * FROM mart.fact_vhs_score {_RUN_WHERE}"),
            conn, params=_RUN_PARAMS,
        )
        df_penalty = pd.read_sql(
            text(f"SELECT * FROM mart.fact_vhs_penalty_detail {_RUN_WHERE}"),
            conn, params=_RUN_PARAMS,
        )

    # Cast boolean columns
    for col in ["is_vital", "is_important", "is_critical_functional",
                "is_immobilizing", "is_hard_cap_trigger", "hard_cap_applied", "is_drivable"]:
        for df in [df_scores, df_penalty]:
            if col in df.columns:
                df[col] = df[col].fillna(False).astype(bool)

    logger.info(f"  VHS V2 score rows loaded     : {len(df_scores)}")
    logger.info(f"  penalty detail rows loaded   : {len(df_penalty)}")

    # ------------------------------------------------------------------
    # Build reports
    # ------------------------------------------------------------------
    df_summary, severe_keys  = _report_severe_summary(df_scores, df_penalty)
    df_pen_det               = _report_severe_penalty_details(df_penalty, severe_keys, df_scores)
    df_grade_d               = _report_grade_d_drivers(df_penalty, df_scores)
    df_immo                  = _report_immobilized_driver(df_scores, df_penalty)
    df_expl                  = _report_critical_explanations(df_scores, df_penalty)
    df_ws_effect             = _report_worn_strong_effect(df_scores, df_penalty, severe_keys)
    md_content               = _build_markdown(df_summary, df_grade_d, df_immo, df_expl, df_ws_effect)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    files: list[Path] = []
    files.append(_save(df_summary,  "v2_severe_cases_summary.csv"))
    files.append(_save(df_pen_det,  "v2_severe_penalty_details.csv"))
    files.append(_save(df_grade_d,  "v2_grade_d_drivers.csv"))
    files.append(_save(df_immo,     "v2_immobilized_driver.csv"))
    files.append(_save(df_expl,     "v2_critical_case_explanations.csv"))
    files.append(_save(df_ws_effect,"v2_worn_strong_effect_on_severe_cases.csv"))
    md_path = AUDIT_DIR / "v2_severe_cases_audit_summary.md"
    md_path.write_text(md_content, encoding="utf-8")
    files.append(md_path)

    # ------------------------------------------------------------------
    # Compute summary stats for console
    # ------------------------------------------------------------------
    n_severe   = len(df_summary)
    n_critique = int((df_summary["decision"] == "CRITIQUE").sum())
    n_immo     = int((df_summary["decision"] == "IMMOBILISE").sum())
    n_grade_d  = int((df_summary["safety_grade"] == "D").sum())
    n_sev_with_ws = int((df_ws_effect["nb_worn_strong"] > 0).sum())

    # Top 10 Grade D driver checkpoints
    top10_d = df_grade_d.head(10)

    # Immobilized driver checkpoint(s)
    immo_cps = []
    if len(df_immo) > 0 and "checkpoint_libelle" in df_immo.columns:
        immo_cps = df_immo[df_immo["is_immobilizing"].astype(bool)]["checkpoint_libelle"].dropna().unique().tolist()

    # Recommendation
    if len(df_expl) > 0 and n_critique > 0:
        pct_vital = round(100.0 * (df_expl["nb_t1_vital_broken"] >= 1).sum() / n_critique, 1)
        rec_short = f"~{pct_vital:.0f}% of CRITIQUE cases from T1_VITAL BROKEN"
    else:
        rec_short = "0 CRITIQUE cases"

    # ------------------------------------------------------------------
    # Log
    # ------------------------------------------------------------------
    logger.info("=" * 65)
    logger.info(f"  output folder                : {AUDIT_DIR}")
    logger.info(f"  files generated              : {len(files)}")
    logger.info(f"  total severe cases           : {n_severe}")
    logger.info(f"  CRITIQUE                     : {n_critique}")
    logger.info(f"  IMMOBILISE                   : {n_immo}")
    logger.info(f"  Grade D                      : {n_grade_d}")
    logger.info(f"  severe cases with WORN_STRONG: {n_sev_with_ws}")
    logger.info("  Top 10 Grade D driver checkpoints:")
    for r in top10_d.itertuples():
        logger.info(
            f"    {r.checkpoint_libelle:<43}"
            f"  {r.tier:<16}"
            f"  {r.observed_status:<12}"
            f"  n={r.nb_occurrences}"
        )
    if immo_cps:
        logger.info(f"  IMMOBILISE driver: {'; '.join(immo_cps)}")
    else:
        logger.info("  IMMOBILISE driver: none")
    logger.info(f"  Recommendation summary       : {rec_short}")
    logger.info("=" * 65)
    for f in files:
        logger.info(f"  {f.name}")
    logger.info(f"Done: {len(files)} files -> {AUDIT_DIR}")

    # ------------------------------------------------------------------
    # Print
    # ------------------------------------------------------------------
    print("=" * 65)
    print(f"  V2 Severe Cases Audit: {RUN_ID}")
    print(f"  Output : {AUDIT_DIR}")
    print(f"  Files  : {len(files)}")
    print()
    print(f"  Total severe cases    : {n_severe}")
    print(f"  CRITIQUE              : {n_critique}")
    print(f"  IMMOBILISE            : {n_immo}")
    print(f"  Grade D               : {n_grade_d}")
    print(f"  Severe with WORN_STRONG: {n_sev_with_ws}")
    print()
    print("  Top 10 Grade D driver checkpoints:")
    for i, r in enumerate(top10_d.itertuples(), 1):
        print(
            f"    [{i:2}] {r.checkpoint_libelle:<41}"
            f"  {r.tier:<16}"
            f"  {r.observed_status:<12}"
            f"  n={r.nb_occurrences}"
        )
    print()
    if immo_cps:
        print(f"  IMMOBILISE driver checkpoint(s): {'; '.join(immo_cps)}")
    else:
        print("  IMMOBILISE driver checkpoint(s): none")
    print()
    print(f"  Recommendation: {rec_short}")
    print("=" * 65)

    return df_summary, df_expl, df_ws_effect


if __name__ == "__main__":
    audit_vhs_v2_severe_cases()
