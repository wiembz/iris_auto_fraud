"""Dossier-level Claim Attention V2 candidate aggregation.

This module aggregates existing guarantee-level V2 outputs to a claim dossier
worklist grain. It does not write to PostgreSQL, does not modify V1, and does
not add ML or post-inspection points.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from etl.mart.compute_claim_attention_score_v2_candidate import attention_level
from etl.utils.business_language import contains_forbidden_business_wording

AGGREGATION_VERSION = "IRIS_CLAIM_ATTENTION_DOSSIER_V2_CANDIDATE"
DEFAULT_AGGREGATION_RUN_ID = "TEST_DOSSIER_V2_RUN"

DOSSIER_COLUMNS = [
    "claim_root_id",
    "guarantee_row_count",
    "guarantee_codes",
    "dossier_attention_score",
    "dossier_attention_level",
    "distinct_rule_count",
    "main_reason_1",
    "main_reason_2",
    "main_reason_3",
    "evaluation_status",
    "confidence_level",
    "source_score_run_id",
    "source_score_version",
    "aggregation_version",
    "aggregation_run_id",
    "root_key_strategy",
    "root_key_quality",
    "created_at",
]

DETAIL_COLUMNS = [
    "claim_root_id",
    "claim_sk",
    "claim_business_id",
    "guarantee_code",
    "guarantee_attention_score",
    "guarantee_attention_level",
    "rule_code",
    "rule_family",
    "awarded_points",
    "business_label",
    "business_explanation",
    "source_score_run_id",
    "aggregation_run_id",
]


def derive_claim_root_id(value: Any) -> tuple[str, str]:
    """Return a cautious root id and a quality flag from a business id."""
    if value is None or pd.isna(value):
        return "", "MISSING_BUSINESS_ID"
    text = str(value).strip()
    if not text:
        return "", "MISSING_BUSINESS_ID"
    if "|" not in text:
        return text, "NO_SEPARATOR_USED_AS_ROOT"
    root, _ = text.split("|", 1)
    root = root.strip()
    if not root:
        return text, "EMPTY_ROOT_USED_FULL_ID"
    return root, "PIPE_SEPARATED_ROOT"


def _guarantee_code(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if "|" in text:
        return text.rsplit("|", 1)[-1].strip()
    return ""


def _join_unique(values: pd.Series) -> str:
    unique = sorted({str(value).strip() for value in values.dropna() if str(value).strip()})
    return ",".join(unique)


def _highest_confidence(values: pd.Series) -> str:
    order = {"HIGH": 4, "MEDIUM": 3, "LOW": 2, "NOT_EVALUABLE": 1}
    clean = [str(value) for value in values.dropna()]
    if not clean:
        return "NOT_EVALUABLE"
    return max(clean, key=lambda value: order.get(value, 0))


def _evaluation_status(values: pd.Series) -> str:
    statuses = {str(value) for value in values.dropna() if str(value)}
    if "FULLY_EVALUABLE" in statuses and len(statuses) == 1:
        return "FULLY_EVALUABLE"
    if statuses and statuses != {"NOT_EVALUABLE"}:
        return "PARTIALLY_EVALUABLE"
    return "NOT_EVALUABLE"


def _reason_columns_from_scores(scores: pd.DataFrame) -> pd.DataFrame:
    reason_columns = [column for column in ["main_reason_1", "main_reason_2", "main_reason_3"] if column in scores.columns]
    if not reason_columns:
        return pd.DataFrame(columns=["claim_root_id", "business_label", "awarded_points"])
    rows = []
    for _, row in scores.iterrows():
        for rank, column in enumerate(reason_columns, start=1):
            reason = row.get(column)
            if reason is not None and not pd.isna(reason) and str(reason).strip():
                rows.append({
                    "claim_root_id": row["claim_root_id"],
                    "business_label": str(reason).strip(),
                    "awarded_points": max(1, 4 - rank),
                })
    return pd.DataFrame(rows)


def _reason_summary(scores: pd.DataFrame, details: pd.DataFrame) -> pd.DataFrame:
    if not details.empty and {"claim_root_id", "business_label", "awarded_points"}.issubset(details.columns):
        reason_source = details[details["awarded_points"].fillna(0).gt(0)][["claim_root_id", "business_label", "awarded_points"]].copy()
    else:
        reason_source = _reason_columns_from_scores(scores)
    if reason_source.empty:
        return pd.DataFrame(columns=["claim_root_id", "main_reason_1", "main_reason_2", "main_reason_3"])
    reason_source = reason_source.dropna(subset=["business_label"])
    reason_source["business_label"] = reason_source["business_label"].astype(str).str.strip()
    grouped = (
        reason_source.groupby(["claim_root_id", "business_label"], as_index=False)["awarded_points"]
        .max()
        .sort_values(["claim_root_id", "awarded_points", "business_label"], ascending=[True, False, True])
    )
    rows = []
    for claim_root_id, group in grouped.groupby("claim_root_id", sort=False):
        reasons = group["business_label"].head(3).tolist()
        while len(reasons) < 3:
            reasons.append(None)
        rows.append({
            "claim_root_id": claim_root_id,
            "main_reason_1": reasons[0],
            "main_reason_2": reasons[1],
            "main_reason_3": reasons[2],
        })
    return pd.DataFrame(rows)


def prepare_guarantee_scores(scores: pd.DataFrame) -> pd.DataFrame:
    required = {"claim_sk", "claim_business_id", "attention_score", "attention_level"}
    missing = required - set(scores.columns)
    if missing:
        raise ValueError(f"Missing required score columns: {sorted(missing)}")
    out = scores.copy()
    roots = out["claim_business_id"].map(derive_claim_root_id)
    out["claim_root_id"] = roots.map(lambda item: item[0])
    out["root_key_quality"] = roots.map(lambda item: item[1])
    out["guarantee_code"] = out["claim_business_id"].map(_guarantee_code)
    out["attention_score"] = pd.to_numeric(out["attention_score"], errors="coerce").fillna(0).clip(0, 100).astype(int)
    return out


def prepare_dossier_details(scores: pd.DataFrame, details: pd.DataFrame, *, aggregation_run_id: str) -> pd.DataFrame:
    if details is None or details.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS)
    prepared_scores = scores[["claim_sk", "claim_root_id", "guarantee_code", "attention_score", "attention_level"]].copy()
    merged = details.merge(prepared_scores, on="claim_sk", how="left")
    merged["source_score_run_id"] = merged.get("score_run_id")
    merged["aggregation_run_id"] = aggregation_run_id
    merged = merged.rename(columns={
        "attention_score": "guarantee_attention_score",
        "attention_level": "guarantee_attention_level",
    })
    for column in DETAIL_COLUMNS:
        if column not in merged.columns:
            merged[column] = pd.NA
    return merged[DETAIL_COLUMNS].copy()


def aggregate_claim_attention_dossier_v2(
    guarantee_scores: pd.DataFrame,
    guarantee_details: pd.DataFrame | None = None,
    *,
    aggregation_run_id: str = DEFAULT_AGGREGATION_RUN_ID,
    aggregation_version: str = AGGREGATION_VERSION,
    created_at: datetime | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aggregate guarantee-level V2 rows to one dossier row per claim root."""
    created_at = created_at or datetime.now(timezone.utc)
    scores = prepare_guarantee_scores(guarantee_scores)
    if scores.empty:
        return pd.DataFrame(columns=DOSSIER_COLUMNS), pd.DataFrame(columns=DETAIL_COLUMNS)

    source_score_run_id = _join_unique(scores.get("score_run_id", pd.Series(dtype="object")))
    source_score_version = _join_unique(scores.get("score_version", pd.Series(dtype="object")))
    details = prepare_dossier_details(scores, guarantee_details if guarantee_details is not None else pd.DataFrame(), aggregation_run_id=aggregation_run_id)
    reason_summary = _reason_summary(scores, details)

    grouped = scores.groupby("claim_root_id", dropna=False).agg(
        guarantee_row_count=("claim_sk", "size"),
        guarantee_codes=("guarantee_code", _join_unique),
        dossier_attention_score=("attention_score", "max"),
        confidence_level=("confidence_level", _highest_confidence) if "confidence_level" in scores.columns else ("claim_sk", lambda _: "NOT_EVALUABLE"),
        root_key_quality=("root_key_quality", _join_unique),
    ).reset_index()
    grouped["dossier_attention_level"] = grouped["dossier_attention_score"].map(attention_level)

    if not details.empty:
        distinct_rules = details.dropna(subset=["rule_code"]).groupby("claim_root_id")["rule_code"].nunique().reset_index(name="distinct_rule_count")
    else:
        distinct_rules = pd.DataFrame(columns=["claim_root_id", "distinct_rule_count"])
    grouped = grouped.merge(distinct_rules, on="claim_root_id", how="left")
    grouped["distinct_rule_count"] = grouped["distinct_rule_count"].fillna(0).astype(int)
    grouped = grouped.merge(reason_summary, on="claim_root_id", how="left")
    grouped["evaluation_status"] = "PARTIALLY_EVALUABLE"
    grouped["source_score_run_id"] = source_score_run_id
    grouped["source_score_version"] = source_score_version
    grouped["aggregation_version"] = aggregation_version
    grouped["aggregation_run_id"] = aggregation_run_id
    grouped["root_key_strategy"] = "CLAIM_BUSINESS_ID_PREFIX_BEFORE_PIPE_WITH_QUALITY_FLAG"
    grouped["created_at"] = created_at

    for column in ["main_reason_1", "main_reason_2", "main_reason_3"]:
        if column not in grouped.columns:
            grouped[column] = pd.NA
    dossier = grouped[DOSSIER_COLUMNS].sort_values(["dossier_attention_score", "claim_root_id"], ascending=[False, True]).reset_index(drop=True)

    for frame in [dossier, details]:
        for column in frame.columns:
            if frame[column].astype(str).map(contains_forbidden_business_wording).any():
                raise ValueError(f"Accusatory wording detected in {column}")
    return dossier, details
