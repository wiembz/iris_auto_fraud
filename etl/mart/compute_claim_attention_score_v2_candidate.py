"""Claim Attention Score V2 candidate.

The V2 score combines configurable deterministic business rules for worklist
prioritization. It is not a fraud probability and does not replace V1.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from etl.mart.compute_claim_business_rules_v2_candidate import (
    compute_claim_business_rules_v2,
    contains_accusatory_wording,
    load_rule_catalog,
)

SCORE_VERSION = "IRIS_CLAIM_ATTENTION_V2_CANDIDATE"
PROFILE_NAME = "CLAIM_ATTENTION_V2_CANDIDATE"
SCORE_COLUMNS = [
    "claim_sk",
    "claim_business_id",
    "attention_score",
    "attention_level",
    "priority_rank",
    "confidence_level",
    "main_reason_1",
    "main_reason_2",
    "main_reason_3",
    "score_version",
    "score_run_id",
    "smart_feature_run_id",
    "created_at",
]
DETAIL_COLUMNS = [
    "claim_sk",
    "claim_business_id",
    "score_run_id",
    "score_version",
    "rule_code",
    "rule_family",
    "rule_version",
    "rule_catalog_version",
    "rule_catalog_hash",
    "rule_value",
    "raw_points",
    "awarded_points",
    "points",
    "family_cap",
    "business_label",
    "business_explanation",
    "suggested_action_code",
    "smart_feature_run_id",
    "source_as_of_date",
    "input_hash",
    "created_at",
]


def _missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except TypeError:
        return False


def _coalesce(*values: Any, default: Any = None) -> Any:
    for value in values:
        if not _missing(value):
            return value
    return default


def attention_level(score: int | float) -> str:
    score_int = max(0, min(100, int(round(float(score)))))
    if score_int <= 24:
        return "Analyse standard"
    if score_int <= 49:
        return "Points a verifier"
    if score_int <= 74:
        return "Examen renforce suggere"
    return "Examen prioritaire suggere"


def _apply_family_caps(signals: pd.DataFrame, family_caps: dict[str, Any]) -> pd.DataFrame:
    if signals.empty:
        return signals.copy()
    capped = signals.copy()
    capped["raw_points"] = pd.to_numeric(capped["raw_points"], errors="coerce").fillna(0).clip(lower=0).astype(int)
    fallback_caps = capped.groupby("rule_family")["family_cap"].transform("max") if "family_cap" in capped else 0
    capped["_family_cap_effective"] = (
        capped["rule_family"].astype(str).map(family_caps).fillna(fallback_caps).fillna(0).astype(int)
    )
    ordered = capped.sort_values(
        ["claim_sk", "rule_family", "raw_points", "rule_code"],
        ascending=[True, True, False, True],
    ).copy()
    cumulative_before = ordered.groupby(["claim_sk", "rule_family"], dropna=False)["raw_points"].cumsum() - ordered["raw_points"]
    remaining = (ordered["_family_cap_effective"] - cumulative_before).clip(lower=0)
    ordered["awarded_points"] = pd.concat([ordered["raw_points"], remaining], axis=1).min(axis=1).astype(int)
    capped["awarded_points"] = 0
    capped.loc[ordered.index, "awarded_points"] = ordered["awarded_points"]
    capped["points"] = capped["awarded_points"]
    return capped.drop(columns=["_family_cap_effective"])


def _top_reasons(details: pd.DataFrame) -> list[str | None]:
    if details.empty:
        return [None, None, None]
    reasons = (
        details[details["awarded_points"].gt(0)]
        .sort_values(["awarded_points", "business_label"], ascending=[False, True])["business_label"]
        .dropna()
        .astype(str)
        .head(3)
        .tolist()
    )
    while len(reasons) < 3:
        reasons.append(None)
    return reasons


def _top_reasons_by_claim(details: pd.DataFrame) -> dict[Any, list[str | None]]:
    if details.empty:
        return {}
    ranked = details[details["awarded_points"].gt(0)].sort_values(
        ["claim_sk", "awarded_points", "business_label"],
        ascending=[True, False, True],
    )
    reasons_by_claim: dict[Any, list[str | None]] = {}
    for claim_sk, group in ranked.groupby("claim_sk", sort=False):
        reasons = group["business_label"].dropna().astype(str).head(3).tolist()
        while len(reasons) < 3:
            reasons.append(None)
        reasons_by_claim[claim_sk] = reasons
    return reasons_by_claim


def compute_claim_attention_score_v2(
    smart_features: pd.DataFrame,
    catalog: dict[str, Any] | None = None,
    *,
    score_run_id: str = "TEST_SCORE_V2_RUN",
    created_at: datetime | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return score rows and explanation detail rows for V2 candidate."""
    catalog = catalog or load_rule_catalog()
    created_at = created_at or datetime.now(timezone.utc)
    raw_signals = compute_claim_business_rules_v2(smart_features, catalog, created_at=created_at)
    capped = _apply_family_caps(raw_signals, catalog.get("family_caps", {}))

    detail_rows: list[dict[str, Any]] = []
    if not capped.empty:
        for _, row in capped.iterrows():
            awarded = int(row.get("awarded_points", row.get("points", 0)))
            if awarded == 0 and row.get("rule_family") != "DATA_QUALITY":
                continue
            detail_rows.append({
                "claim_sk": row["claim_sk"],
                "claim_business_id": row.get("claim_business_id"),
                "score_run_id": score_run_id,
                "score_version": SCORE_VERSION,
                "rule_code": row["rule_code"],
                "rule_family": row["rule_family"],
                "rule_version": row.get("rule_version"),
                "rule_catalog_version": row.get("rule_catalog_version"),
                "rule_catalog_hash": row.get("rule_catalog_hash"),
                "rule_value": row.get("rule_value"),
                "raw_points": int(row.get("raw_points", 0)),
                "awarded_points": awarded,
                "points": awarded,
                "family_cap": int(row.get("family_cap", 0)),
                "business_label": row["label_business"],
                "business_explanation": row["business_explanation"],
                "suggested_action_code": row["suggested_action_code"],
                "smart_feature_run_id": row.get("smart_feature_run_id"),
                "source_as_of_date": row.get("source_as_of_date"),
                "input_hash": row.get("input_hash"),
                "created_at": created_at,
            })
    details = pd.DataFrame(detail_rows, columns=DETAIL_COLUMNS)
    points_by_claim = (
        details.groupby("claim_sk")["awarded_points"].sum().astype(int).to_dict()
        if not details.empty
        else {}
    )
    reasons_by_claim = _top_reasons_by_claim(details)

    score_rows: list[dict[str, Any]] = []
    for _, feature in smart_features.iterrows():
        claim_sk = feature.get("claim_sk")
        attention_points = int(points_by_claim.get(claim_sk, 0))
        attention_score = min(100, max(0, attention_points))
        reasons = reasons_by_claim.get(claim_sk, [None, None, None])
        score_rows.append({
            "claim_sk": claim_sk,
            "claim_business_id": feature.get("claim_business_id"),
            "attention_score": attention_score,
            "attention_level": attention_level(attention_score),
            "priority_rank": None,
            "confidence_level": _coalesce(feature.get("confidence_level"), feature.get("data_quality_level"), default="NOT_EVALUABLE"),
            "main_reason_1": reasons[0],
            "main_reason_2": reasons[1],
            "main_reason_3": reasons[2],
            "score_version": SCORE_VERSION,
            "score_run_id": score_run_id,
            "smart_feature_run_id": feature.get("smart_feature_run_id"),
            "created_at": created_at,
        })

    scores = pd.DataFrame(score_rows, columns=SCORE_COLUMNS)
    if not scores.empty:
        scores = scores.sort_values(["attention_score", "claim_sk"], ascending=[False, True]).reset_index(drop=True)
        scores["priority_rank"] = range(1, len(scores) + 1)
        scores = scores.sort_values("claim_sk").reset_index(drop=True)

    for frame in [scores, details]:
        for column in frame.columns:
            if frame[column].astype(str).map(contains_accusatory_wording).any():
                raise ValueError(f"Accusatory wording detected in {column}")
    return scores, details
