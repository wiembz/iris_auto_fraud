"""Read-only validation for IRIS Smart Decision Support V2 candidate.

This script reads the existing DWH/mart outputs, computes Smart Decision Support
V2 in memory, and exports validation reports. It does not write to PostgreSQL,
does not define DWH tables, and does not modify Claim Attention V1, VHS, ML, or the
frontend.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "etl" / "dwh"))

from etl.mart.compute_claim_attention_hybrid_score_v1_candidate import SCORE_VERSION as DEFAULT_V1_SCORE_VERSION
from etl.mart.compute_claim_attention_score_v2_candidate import (
    SCORE_VERSION as V2_SCORE_VERSION,
    compute_claim_attention_score_v2,
)
from etl.mart.compute_claim_scoring_features_v1 import FEATURE_VERSION
from etl.mart.compute_claim_smart_features_v2_candidate import (
    SMART_FEATURE_VERSION,
    compute_claim_smart_features_v2,
)
from etl.utils.business_language import contains_forbidden_business_wording

REPORT_DIR = BASE_DIR / "data" / "quality_reports" / "scoring" / "smart_decision_v2_validation"
VALIDATION_PROFILE = "IRIS_SMART_DECISION_SUPPORT_V2_READONLY_VALIDATION"

READ_FEATURE_COLUMNS = [
    "claim_sk",
    "claim_business_id",
    "feature_run_id",
    "claim_date",
    "contract_start_date",
    "claim_amount",
    "code_garantie",
    "days_claim_to_declaration",
    "days_contract_start_to_claim",
    "claim_before_contract_start_flag",
    "contract_start_ready_flag",
    "client_claim_count_12m",
    "client_claim_count_24m",
    "days_since_previous_claim",
    "missing_client_flag",
    "missing_contract_flag",
    "missing_vehicle_flag",
    "missing_guarantee_flag",
    "missing_geo_flag",
    "invalid_claim_date_flag",
    "invalid_declaration_date_flag",
    "migration_2019_flag",
    "confidence_level",
]

FAMILY_FLAG_MAP = {
    "HISTORY": "history_evaluable_flag",
    "CHRONOLOGY": "chronology_evaluable_flag",
    "COMPLETENESS": "document_completeness_evaluable_flag",
    "DATA_QUALITY": "data_quality_evaluable_flag",
    "GEOGRAPHY": "geo_evaluable_flag",
}
COMPARISON_FAMILY = "COMPARISON"
COMPARISON_DISPLAYABLE = "DISPLAYABLE"


def _load_dwh_utils():
    import dwh_utils

    return dwh_utils


def _latest_run_id(engine, table_name: str, run_column: str, version_column: str, version: str) -> str | None:
    query = text(f"""
        SELECT {run_column}
        FROM {table_name}
        WHERE {version_column} = :version
        ORDER BY created_at DESC, {run_column} DESC
        LIMIT 1
    """)
    with engine.connect() as conn:
        return conn.execute(query, {"version": version}).scalar_one_or_none()


def read_latest_features(engine, feature_run_id: str | None = None) -> tuple[pd.DataFrame, str | None]:
    selected_run = feature_run_id or _latest_run_id(
        engine,
        "mart.fact_claim_scoring_features",
        "feature_run_id",
        "scoring_feature_version",
        FEATURE_VERSION,
    )
    if not selected_run:
        return pd.DataFrame(columns=READ_FEATURE_COLUMNS), None
    columns_sql = ",\n                    ".join(READ_FEATURE_COLUMNS)
    query = text(f"""
        SELECT
            {columns_sql}
        FROM mart.fact_claim_scoring_features
        WHERE scoring_feature_version = :feature_version
          AND feature_run_id = :feature_run_id
    """)
    with engine.connect() as conn:
        frame = pd.read_sql(
            query,
            conn,
            params={"feature_version": FEATURE_VERSION, "feature_run_id": selected_run},
        )
    return frame, selected_run


def read_v1_scores(engine, score_version: str = DEFAULT_V1_SCORE_VERSION, score_run_id: str | None = None) -> tuple[pd.DataFrame, str | None]:
    selected_run = score_run_id or _latest_run_id(
        engine,
        "mart.fact_claim_attention_score",
        "score_run_id",
        "score_version",
        score_version,
    )
    if not selected_run:
        return pd.DataFrame(columns=["claim_sk", "attention_score", "attention_level", "confidence_level"]), None
    query = text("""
        SELECT
            claim_sk,
            claim_business_id,
            attention_score AS attention_score_v1,
            attention_level AS attention_level_v1,
            confidence_level AS confidence_level_v1,
            score_version AS score_version_v1,
            score_run_id AS score_run_id_v1
        FROM mart.fact_claim_attention_score
        WHERE score_version = :score_version
          AND score_run_id = :score_run_id
    """)
    with engine.connect() as conn:
        frame = pd.read_sql(query, conn, params={"score_version": score_version, "score_run_id": selected_run})
    return frame, selected_run


def _count_distribution(frame: pd.DataFrame, column: str, count_name: str = "rows") -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return pd.DataFrame(columns=[column, count_name])
    return frame[column].value_counts(dropna=False).rename_axis(column).reset_index(name=count_name)



def _claim_root_series(values: pd.Series) -> pd.Series:
    return values.astype("string").str.split("|", n=1).str[0].fillna("")


def _period_bucket_from_date(values: pd.Series) -> pd.Series:
    dates = pd.to_datetime(values, errors="coerce")
    years = dates.dt.year
    result = pd.Series("MISSING_DATE", index=values.index, dtype="object")
    result = result.mask(years.lt(2019), "PRE_2019")
    result = result.mask(years.eq(2019), "YEAR_2019")
    result = result.mask(years.gt(2019), "POST_2019")
    return result


def _evaluation_family_status(smart_features: pd.DataFrame) -> tuple[str, list[str], list[str]]:
    if smart_features.empty:
        return "NO_ROWS", [], list(FAMILY_FLAG_MAP) + [COMPARISON_FAMILY]
    evaluable: list[str] = []
    non_evaluable: list[str] = []
    for family, column in FAMILY_FLAG_MAP.items():
        if column in smart_features.columns and bool(smart_features[column].fillna(False).astype(bool).any()):
            evaluable.append(family)
        else:
            non_evaluable.append(family)
    if "comparison_reliability" in smart_features.columns and smart_features["comparison_reliability"].eq(COMPARISON_DISPLAYABLE).any():
        evaluable.append(COMPARISON_FAMILY)
    else:
        non_evaluable.append(COMPARISON_FAMILY)
    if not non_evaluable:
        status = "FULLY_EVALUABLE"
    elif evaluable:
        status = "PARTIALLY_EVALUABLE"
    else:
        status = "NOT_EVALUABLE"
    return status, sorted(evaluable), sorted(non_evaluable)

def _non_evaluation_causes(smart_features: pd.DataFrame) -> pd.DataFrame:
    causes = []
    flag_causes = {
        "history_evaluable_flag": "history_not_evaluable",
        "chronology_evaluable_flag": "chronology_not_evaluable",
        "document_completeness_evaluable_flag": "document_completeness_not_evaluable",
        "data_quality_evaluable_flag": "data_quality_not_evaluable",
        "geo_evaluable_flag": "geo_not_evaluable",
    }
    for column, cause in flag_causes.items():
        if column in smart_features.columns:
            causes.append({"cause": cause, "rows": int((~smart_features[column].fillna(False).astype(bool)).sum())})
    if "comparison_status_reason" in smart_features.columns:
        comparison = smart_features["comparison_status_reason"].value_counts(dropna=False).reset_index()
        comparison.columns = ["cause", "rows"]
        comparison["cause"] = "comparison_" + comparison["cause"].astype(str)
        causes.extend(comparison.to_dict("records"))
    return pd.DataFrame(causes).sort_values("rows", ascending=False).reset_index(drop=True)


def _v1_v2_comparison(v1_scores: pd.DataFrame, v2_scores: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if v1_scores.empty:
        comparison = v2_scores[["claim_sk", "claim_business_id", "attention_score", "attention_level", "confidence_level"]].copy()
        comparison = comparison.rename(columns={
            "attention_score": "attention_score_v2",
            "attention_level": "attention_level_v2",
            "confidence_level": "confidence_level_v2",
        })
        comparison["attention_score_v1"] = pd.NA
        comparison["attention_level_v1"] = pd.NA
        comparison["score_delta_v2_minus_v1"] = pd.NA
    else:
        comparison = v2_scores.merge(v1_scores, on=["claim_sk", "claim_business_id"], how="left")
        comparison = comparison.rename(columns={
            "attention_score": "attention_score_v2",
            "attention_level": "attention_level_v2",
            "confidence_level": "confidence_level_v2",
        })
        comparison["score_delta_v2_minus_v1"] = pd.to_numeric(comparison["attention_score_v2"], errors="coerce") - pd.to_numeric(comparison["attention_score_v1"], errors="coerce")
    comparison["claim_root_id"] = _claim_root_series(comparison["claim_business_id"])
    transitions = (
        comparison.groupby(["attention_level_v1", "attention_level_v2"], dropna=False)
        .size()
        .reset_index(name="rows")
        .sort_values("rows", ascending=False)
    )
    return comparison, transitions



def _grain_audit(comparison: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if comparison.empty:
        return pd.DataFrame([{"score_rows": 0, "distinct_claim_root_ids": 0, "grain_decision_needed": True}]), pd.DataFrame()
    grouped = comparison.groupby("claim_root_id", dropna=False).agg(
        score_rows=("claim_sk", "size"),
        distinct_v2_scores=("attention_score_v2", "nunique"),
        distinct_v2_levels=("attention_level_v2", "nunique"),
        max_v2_score=("attention_score_v2", "max"),
        min_v2_score=("attention_score_v2", "min"),
    ).reset_index()
    summary = pd.DataFrame([{
        "score_rows": int(len(comparison)),
        "distinct_claim_root_ids": int(grouped["claim_root_id"].nunique()),
        "multi_guarantee_claim_roots": int(grouped["score_rows"].gt(1).sum()),
        "claim_roots_with_multiple_v2_scores": int(grouped["distinct_v2_scores"].gt(1).sum()),
        "claim_roots_with_multiple_v2_levels": int(grouped["distinct_v2_levels"].gt(1).sum()),
        "max_rows_per_claim_root": int(grouped["score_rows"].max()),
        "grain_decision_needed": bool(grouped["score_rows"].gt(1).any()),
        "recommended_business_grain": "DOSSIER_SINISTRE_TO_BE_CONFIRMED",
    }])
    distribution = grouped["score_rows"].value_counts().rename_axis("guarantee_rows_per_claim_root").reset_index(name="claim_roots")
    return summary, distribution.sort_values("guarantee_rows_per_claim_root")


def _cohort_size_distribution(smart_features: pd.DataFrame) -> pd.DataFrame:
    if smart_features.empty or "similar_claim_count" not in smart_features.columns:
        return pd.DataFrame()
    series = pd.to_numeric(smart_features["similar_claim_count"], errors="coerce")
    return series.describe(percentiles=[0.25, 0.5, 0.75, 0.9, 0.95]).reset_index(name="similar_claim_count")


def _cohort_status_by_year(source_features: pd.DataFrame, smart_features: pd.DataFrame) -> pd.DataFrame:
    if source_features.empty or smart_features.empty:
        return pd.DataFrame()
    audit = source_features.reindex(columns=["claim_sk", "claim_date", "code_garantie"]).merge(
        smart_features.reindex(columns=["claim_sk", "comparison_reliability", "comparison_status_reason", "similar_claim_cohort_level", "similar_claim_count"]),
        on="claim_sk",
        how="left",
    )
    audit["claim_year"] = pd.to_datetime(audit["claim_date"], errors="coerce").dt.year.fillna(0).astype(int)
    audit["period_bucket"] = _period_bucket_from_date(audit["claim_date"])
    return (
        audit.groupby(["period_bucket", "claim_year", "code_garantie", "comparison_status_reason"], dropna=False)
        .agg(rows=("claim_sk", "size"), median_cohort_size=("similar_claim_count", "median"))
        .reset_index()
        .sort_values("rows", ascending=False)
    )


def _amount_rule_activation_by_guarantee_year(source_features: pd.DataFrame, details: pd.DataFrame) -> pd.DataFrame:
    if source_features.empty:
        return pd.DataFrame()
    base = source_features.reindex(columns=["claim_sk", "claim_date", "code_garantie"]).copy()
    base["claim_year"] = pd.to_datetime(base["claim_date"], errors="coerce").dt.year.fillna(0).astype(int)
    if details.empty:
        amount_claims = pd.DataFrame(columns=["claim_sk", "amount_rule_active"])
    else:
        amount_claims = details[details["rule_code"].eq("COMP_AMOUNT_ABOVE_SIMILAR_MEDIAN")][["claim_sk"]].drop_duplicates()
        amount_claims["amount_rule_active"] = True
    audit = base.merge(amount_claims, on="claim_sk", how="left")
    audit["amount_rule_active"] = audit["amount_rule_active"].fillna(False)
    grouped = audit.groupby(["claim_year", "code_garantie"], dropna=False).agg(
        rows=("claim_sk", "size"),
        amount_rule_activations=("amount_rule_active", "sum"),
    ).reset_index()
    grouped["activation_rate"] = grouped["amount_rule_activations"] / grouped["rows"].where(grouped["rows"].ne(0), pd.NA)
    return grouped.sort_values(["amount_rule_activations", "rows"], ascending=False)


def _chronology_rule_audit(source_features: pd.DataFrame, details: pd.DataFrame) -> pd.DataFrame:
    if source_features.empty:
        return pd.DataFrame()
    columns = ["claim_sk", "claim_date", "contract_start_date", "code_garantie", "days_claim_to_declaration", "days_contract_start_to_claim"]
    base = source_features.reindex(columns=columns).copy()
    base["period_bucket"] = _period_bucket_from_date(base["claim_date"])
    if details.empty:
        active = pd.DataFrame(columns=["claim_sk", "rule_code"])
    else:
        active = details[details["rule_code"].isin(["CHR_DECLARATION_DELAY_HIGH", "CHR_CLAIM_BEFORE_CONTRACT_START"])][["claim_sk", "rule_code"]].drop_duplicates()
    audit = base.merge(active, on="claim_sk", how="left")
    audit["rule_code"] = audit["rule_code"].fillna("NO_CHRONOLOGY_RULE")
    return (
        audit.groupby(["rule_code", "period_bucket", "code_garantie"], dropna=False)
        .agg(
            rows=("claim_sk", "size"),
            median_declaration_delay=("days_claim_to_declaration", "median"),
            median_contract_to_claim_days=("days_contract_start_to_claim", "median"),
            min_contract_to_claim_days=("days_contract_start_to_claim", "min"),
        )
        .reset_index()
        .sort_values(["rule_code", "rows"], ascending=[True, False])
    )

def _business_sample(scores: pd.DataFrame, details: pd.DataFrame, smart_features: pd.DataFrame, sample_size: int) -> pd.DataFrame:
    if scores.empty:
        return pd.DataFrame()
    top = scores.sort_values(["attention_score", "claim_sk"], ascending=[False, True]).head(max(1, sample_size // 2))
    low_confidence = scores[scores["confidence_level"].isin(["LOW", "NOT_EVALUABLE"])].head(max(1, sample_size // 4))
    non_displayable_claims = smart_features[smart_features["comparison_reliability"].ne("DISPLAYABLE")][["claim_sk"]].head(max(1, sample_size // 4))
    selected = pd.concat([top[["claim_sk"]], low_confidence[["claim_sk"]], non_displayable_claims], ignore_index=True).drop_duplicates().head(sample_size)
    sample = scores[scores["claim_sk"].isin(selected["claim_sk"])].copy()
    if details.empty:
        sample["top_rules"] = ""
    else:
        top_rules = (
            details[details["awarded_points"].gt(0)]
            .sort_values(["claim_sk", "awarded_points"], ascending=[True, False])
            .groupby("claim_sk")["rule_code"]
            .apply(lambda values: ",".join(values.head(3)))
            .reset_index(name="top_rules")
        )
        sample = sample.merge(top_rules, on="claim_sk", how="left")
    return sample.sort_values(["attention_score", "claim_sk"], ascending=[False, True])



def _stratified_business_sample(
    source_features: pd.DataFrame,
    smart_features: pd.DataFrame,
    scores: pd.DataFrame,
    details: pd.DataFrame,
    comparison: pd.DataFrame,
    sample_size: int,
) -> pd.DataFrame:
    if scores.empty:
        return pd.DataFrame()
    enriched = scores.merge(
        source_features.reindex(columns=["claim_sk", "claim_date", "code_garantie"]),
        on="claim_sk",
        how="left",
    ).merge(
        smart_features.reindex(columns=["claim_sk", "comparison_reliability", "comparison_status_reason"]),
        on="claim_sk",
        how="left",
    )
    enriched["period_bucket"] = _period_bucket_from_date(enriched["claim_date"])
    enriched["claim_root_id"] = _claim_root_series(enriched["claim_business_id"])
    if details.empty:
        rule_sets = pd.DataFrame(columns=["claim_sk", "active_rules"])
    else:
        rule_sets = (
            details[details["awarded_points"].gt(0)]
            .sort_values(["claim_sk", "rule_code"])
            .groupby("claim_sk")["rule_code"]
            .apply(lambda values: ",".join(values))
            .reset_index(name="active_rules")
        )
    enriched = enriched.merge(rule_sets, on="claim_sk", how="left")
    enriched["active_rules"] = enriched["active_rules"].fillna("NO_RULE")
    if not comparison.empty:
        transitions = comparison[["claim_sk", "attention_level_v1", "attention_level_v2"]].copy()
        transitions["v1_v2_transition"] = transitions["attention_level_v1"].astype(str) + " -> " + transitions["attention_level_v2"].astype(str)
        enriched = enriched.merge(transitions[["claim_sk", "v1_v2_transition"]], on="claim_sk", how="left")
    else:
        enriched["v1_v2_transition"] = "NO_V1_REFERENCE"

    groups: list[pd.DataFrame] = []
    for column, limit in [
        ("attention_level", 20),
        ("active_rules", 30),
        ("v1_v2_transition", 25),
        ("period_bucket", 12),
        ("code_garantie", 15),
        ("comparison_status_reason", 12),
    ]:
        if column in enriched.columns:
            groups.append(enriched.sort_values(["attention_score", "claim_sk"], ascending=[False, True]).groupby(column, dropna=False).head(2).head(limit))
    groups.append(enriched[enriched["attention_score"].isin([0, 12, 15, 20, 24, 25, 27, 49, 50, 52, 74, 75])].sort_values(["attention_score", "claim_sk"], ascending=[False, True]).head(20))
    sample = pd.concat(groups, ignore_index=True).drop_duplicates("claim_sk").head(sample_size).copy()
    for column in [
        "business_review_signal_relevant",
        "business_review_signal_not_relevant",
        "business_review_data_insufficient",
        "business_review_data_quality_issue",
        "business_review_useful_additional_check",
        "business_review_comment",
    ]:
        sample[column] = ""
    columns = [
        "claim_sk", "claim_business_id", "claim_root_id", "claim_date", "period_bucket", "code_garantie",
        "attention_score", "attention_level", "confidence_level", "main_reason_1", "main_reason_2", "main_reason_3",
        "active_rules", "comparison_reliability", "comparison_status_reason", "v1_v2_transition",
        "business_review_signal_relevant", "business_review_signal_not_relevant", "business_review_data_insufficient",
        "business_review_data_quality_issue", "business_review_useful_additional_check", "business_review_comment",
    ]
    return sample[[column for column in columns if column in sample.columns]]

def build_validation_reports(
    source_features: pd.DataFrame,
    smart_features: pd.DataFrame,
    scores_v2: pd.DataFrame,
    details_v2: pd.DataFrame,
    v1_scores: pd.DataFrame,
    *,
    feature_run_id: str | None,
    v1_score_run_id: str | None,
    v1_score_version: str,
    score_run_id_v2: str,
    sample_size: int = 100,
) -> dict[str, pd.DataFrame | str]:
    comparison, transitions = _v1_v2_comparison(v1_scores, scores_v2)
    grain_summary, grain_distribution = _grain_audit(comparison)
    evaluation_status, evaluable_families, non_evaluable_families = _evaluation_family_status(smart_features)
    evaluable_flags = [
        "history_evaluable_flag",
        "chronology_evaluable_flag",
        "document_completeness_evaluable_flag",
        "data_quality_evaluable_flag",
    ]
    fully_evaluable = int(smart_features[evaluable_flags].fillna(False).all(axis=1).sum()) if not smart_features.empty else 0
    partially_evaluable = int(smart_features[evaluable_flags].fillna(False).any(axis=1).sum()) if not smart_features.empty else 0
    comparable_displayable = int(smart_features["comparison_reliability"].eq("DISPLAYABLE").sum()) if not smart_features.empty else 0
    total = int(len(source_features))

    load_summary = pd.DataFrame([{
        "validation_profile": VALIDATION_PROFILE,
        "feature_version": FEATURE_VERSION,
        "feature_run_id": feature_run_id,
        "smart_feature_version": SMART_FEATURE_VERSION,
        "v2_score_version": V2_SCORE_VERSION,
        "v2_score_run_id": score_run_id_v2,
        "v1_score_version": v1_score_version,
        "v1_score_run_id": v1_score_run_id,
        "loaded_claim_rows": total,
        "v2_score_rows": len(scores_v2),
        "evaluation_status": evaluation_status,
        "evaluable_rule_families": ",".join(evaluable_families),
        "non_evaluable_rule_families": ",".join(non_evaluable_families),
        "fully_evaluable_claims": fully_evaluable,
        "partially_evaluable_claims": partially_evaluable,
        "displayable_comparison_claims": comparable_displayable,
        "displayable_comparison_rate": comparable_displayable / total if total else 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }])

    evaluation_summary = pd.DataFrame([{
        "evaluation_status": evaluation_status,
        "score_calculable": bool(len(scores_v2) == total and total > 0),
        "business_evaluation_complete": evaluation_status == "FULLY_EVALUABLE",
        "evaluable_rule_families": ",".join(evaluable_families),
        "non_evaluable_rule_families": ",".join(non_evaluable_families),
        "recommended_status_wording": "Score calculable, evaluation metier partielle" if evaluation_status == "PARTIALLY_EVALUABLE" else evaluation_status,
    }])

    raw_awarded_by_rule = (
        details_v2.groupby(["rule_family", "rule_code"], dropna=False)
        .agg(
            activation_count=("claim_sk", "size"),
            raw_points_total=("raw_points", "sum"),
            awarded_points_total=("awarded_points", "sum"),
        )
        .reset_index()
        .sort_values(["activation_count", "rule_code"], ascending=[False, True])
        if not details_v2.empty else pd.DataFrame(columns=["rule_family", "rule_code", "activation_count", "raw_points_total", "awarded_points_total"])
    )
    by_family = (
        details_v2.groupby("rule_family", dropna=False)
        .agg(raw_points_total=("raw_points", "sum"), awarded_points_total=("awarded_points", "sum"), rows=("claim_sk", "size"))
        .reset_index()
        if not details_v2.empty else pd.DataFrame(columns=["rule_family", "raw_points_total", "awarded_points_total", "rows"])
    )

    if not details_v2.empty:
        text_columns = ["business_label", "business_explanation"]
        accusatory_rows = int(details_v2[text_columns].astype(str).apply(lambda col: col.map(contains_forbidden_business_wording)).any(axis=1).sum())
    else:
        accusatory_rows = 0
    validation_summary = pd.DataFrame([{
        "score_out_of_range_rows": int((~scores_v2["attention_score"].between(0, 100)).sum()) if not scores_v2.empty else 0,
        "duplicate_v2_score_claim_rows": int(scores_v2.duplicated(["claim_sk", "score_version", "score_run_id"]).sum()) if not scores_v2.empty else 0,
        "null_attention_level_rows": int(scores_v2["attention_level"].isna().sum()) if not scores_v2.empty else 0,
        "accusatory_wording_rows": accusatory_rows,
        "v1_missing_comparison_rows": int(comparison["attention_score_v1"].isna().sum()) if "attention_score_v1" in comparison else len(comparison),
        "grain_decision_needed": bool(grain_summary.iloc[0].get("grain_decision_needed", False)) if not grain_summary.empty else True,
        "business_validation_status": "TECHNICAL_VALIDATION_OK_BUSINESS_VALIDATION_PARTIAL",
    }])

    return {
        "smart_v2_load_summary.csv": load_summary,
        "smart_v2_evaluation_status_summary.csv": evaluation_summary,
        "smart_v2_score_distribution.csv": scores_v2["attention_score"].describe(percentiles=[0.25, 0.5, 0.75, 0.9, 0.95]).reset_index(name="value") if not scores_v2.empty else pd.DataFrame(),
        "smart_v2_attention_level_distribution.csv": _count_distribution(scores_v2, "attention_level"),
        "smart_v2_confidence_distribution.csv": _count_distribution(scores_v2, "confidence_level"),
        "smart_v2_rule_activation_frequency.csv": raw_awarded_by_rule[["rule_family", "rule_code", "activation_count"]],
        "smart_v2_points_raw_awarded_by_rule.csv": raw_awarded_by_rule,
        "smart_v2_points_raw_awarded_by_family.csv": by_family,
        "smart_v2_comparable_cohort_summary.csv": _count_distribution(smart_features, "comparison_reliability"),
        "smart_v2_cohort_size_distribution.csv": _cohort_size_distribution(smart_features),
        "smart_v2_cohort_status_by_year_guarantee.csv": _cohort_status_by_year(source_features, smart_features),
        "smart_v2_amount_rule_activation_by_guarantee_year.csv": _amount_rule_activation_by_guarantee_year(source_features, details_v2),
        "smart_v2_chronology_rule_audit_by_period.csv": _chronology_rule_audit(source_features, details_v2),
        "smart_v2_non_evaluation_causes.csv": _non_evaluation_causes(smart_features),
        "smart_v2_grain_audit_summary.csv": grain_summary,
        "smart_v2_grain_multi_guarantee_summary.csv": grain_distribution,
        "smart_v2_v1_v2_score_comparison.csv": comparison,
        "smart_v2_v1_v2_level_transition.csv": transitions,
        "smart_v2_business_validation_sample.csv": _business_sample(scores_v2, details_v2, smart_features, sample_size),
        "smart_v2_stratified_business_validation_sample.csv": _stratified_business_sample(source_features, smart_features, scores_v2, details_v2, comparison, sample_size),
        "smart_v2_validation_summary.csv": validation_summary,
    }


def write_validation_reports(reports: dict[str, pd.DataFrame | str], output_dir: Path = REPORT_DIR) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for filename, payload in reports.items():
        path = output_dir / filename
        if isinstance(payload, pd.DataFrame):
            payload.to_csv(path, index=False)
        else:
            path.write_text(str(payload), encoding="utf-8")
        paths[filename] = path

    summary = reports.get("smart_v2_load_summary.csv")
    validation = reports.get("smart_v2_validation_summary.csv")
    grain = reports.get("smart_v2_grain_audit_summary.csv")
    lines = [
        "# Smart Decision Support V2 read-only validation",
        "",
        "This validation reads existing DWH/mart data and computes V2 candidate outputs in memory only.",
        "No PostgreSQL write, ETL load, table creation, or score replacement is performed.",
        "",
    ]
    if isinstance(summary, pd.DataFrame) and not summary.empty:
        row = summary.iloc[0].to_dict()
        lines.extend([
            f"- Loaded claim rows: {row.get('loaded_claim_rows')}",
            f"- V2 score rows: {row.get('v2_score_rows')}",
            f"- Evaluation status: {row.get('evaluation_status')}",
            f"- Evaluable families: {row.get('evaluable_rule_families')}",
            f"- Non-evaluable families: {row.get('non_evaluable_rule_families')}",
            f"- Fully evaluable claims: {row.get('fully_evaluable_claims')}",
            f"- Partially evaluable claims: {row.get('partially_evaluable_claims')}",
            f"- Displayable comparison rate: {row.get('displayable_comparison_rate')}",
        ])
    if isinstance(grain, pd.DataFrame) and not grain.empty:
        row = grain.iloc[0].to_dict()
        lines.extend(["", "## Grain audit"])
        lines.append(f"- Distinct claim root ids: {row.get('distinct_claim_root_ids')}")
        lines.append(f"- Multi-guarantee claim roots: {row.get('multi_guarantee_claim_roots')}")
        lines.append(f"- Claim roots with multiple V2 scores: {row.get('claim_roots_with_multiple_v2_scores')}")
        lines.append(f"- Claim roots with multiple V2 levels: {row.get('claim_roots_with_multiple_v2_levels')}")
        lines.append("- Business decision required: dossier-level worklist vs sinistre-garantie grain.")

    if isinstance(validation, pd.DataFrame) and not validation.empty:
        lines.extend(["", "## Validation checks"])
        for key, value in validation.iloc[0].to_dict().items():
            lines.append(f"- {key}: {value}")
    lines.extend([
        "",
        "## Business interpretation",
        "V2 is technically calculable on the DWH volume, but remains a candidate parallel score.",
        "It must not replace V1 until the business grain, missing V2 families, confidence rules, and thresholds are validated.",
    ])
    md_path = output_dir / "smart_v2_validation_summary.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    paths["smart_v2_validation_summary.md"] = md_path
    return paths


def run_readonly_validation(
    *,
    feature_run_id: str | None = None,
    v1_score_version: str = DEFAULT_V1_SCORE_VERSION,
    v1_score_run_id: str | None = None,
    min_cohort_size: int = 20,
    sample_size: int = 100,
    output_dir: Path = REPORT_DIR,
) -> dict[str, Path]:
    dwh_utils = _load_dwh_utils()
    validation_run_id = f"IRIS_SMART_DECISION_V2_READONLY_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    logger = dwh_utils.setup_logging(validation_run_id, log_name="validate_claim_smart_decision_v2_readonly")
    engine = dwh_utils.build_engine(logger)

    source_features, selected_feature_run_id = read_latest_features(engine, feature_run_id)
    v1_scores, selected_v1_score_run_id = read_v1_scores(engine, v1_score_version, v1_score_run_id)
    smart_features = compute_claim_smart_features_v2(
        source_features,
        smart_feature_run_id=validation_run_id,
        source_as_of_date=selected_feature_run_id,
        min_cohort_size=min_cohort_size,
        geo_ready=False,
    )
    scores_v2, details_v2 = compute_claim_attention_score_v2(
        smart_features,
        score_run_id=validation_run_id,
    )
    reports = build_validation_reports(
        source_features,
        smart_features,
        scores_v2,
        details_v2,
        v1_scores,
        feature_run_id=selected_feature_run_id,
        v1_score_run_id=selected_v1_score_run_id,
        v1_score_version=v1_score_version,
        score_run_id_v2=validation_run_id,
        sample_size=sample_size,
    )
    paths = write_validation_reports(reports, output_dir)
    print("=" * 72)
    print("IRIS Smart Decision Support V2 read-only validation complete")
    print(f"  loaded claim rows : {len(source_features)}")
    print(f"  v2 score rows     : {len(scores_v2)}")
    print(f"  v2 detail rows    : {len(details_v2)}")
    print(f"  report folder     : {output_dir}")
    print("=" * 72)
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only Smart Decision Support V2 validation")
    parser.add_argument("--feature-run-id", default=None)
    parser.add_argument("--v1-score-version", default=DEFAULT_V1_SCORE_VERSION)
    parser.add_argument("--v1-score-run-id", default=None)
    parser.add_argument("--min-cohort-size", type=int, default=20)
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--output-dir", default=str(REPORT_DIR))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_readonly_validation(
        feature_run_id=args.feature_run_id,
        v1_score_version=args.v1_score_version,
        v1_score_run_id=args.v1_score_run_id,
        min_cohort_size=args.min_cohort_size,
        sample_size=args.sample_size,
        output_dir=Path(args.output_dir),
    )


if __name__ == "__main__":
    main()

