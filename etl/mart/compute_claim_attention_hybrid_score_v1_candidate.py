"""
etl/mart/compute_claim_attention_hybrid_score_v1_candidate.py
=============================================================
Computes the configurable hybrid Claim Attention score candidate.

This score combines deterministic business-rule signals and the validated
post-inspection Scenario A signal. It is a prioritization aid for human review;
it is not a fraud proof, not a legal conclusion, and not an automatic decision.

Important boundaries:
  - Claim Attention Score V1 remains unchanged.
  - VHS remains unchanged.
  - Scenario B remains readiness-only and does not add points.
  - No ML, SHAP, or Isolation Forest is used.

Sources:
  mart.fact_claim_scoring_features
  mart.fact_claim_business_rule_signal
  mart.fact_post_inspection_attention_signal

Outputs:
  mart.fact_claim_attention_score
  mart.fact_claim_attention_signal_detail
  data/quality_reports/scoring/claim_attention_hybrid_v1/
"""
from __future__ import annotations

import json
import sys
from io import StringIO
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from sqlalchemy import text
except ModuleNotFoundError:  # Allows pure unit tests without DB dependencies.
    text = None


BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dwh"))

from etl.mart.compute_claim_attention_score_v1_candidate import (
    DDL_CREATE_SCHEMA,
    DDL_FACT_CLAIM_ATTENTION_SCORE,
    DDL_FACT_CLAIM_ATTENTION_SIGNAL_DETAIL,
    DETAIL_COLUMNS,
    SCORE_COLUMNS,
)
from etl.mart.compute_claim_business_rule_signals_v1_candidate import (
    SIGNAL_VERSION as BUSINESS_RULE_SIGNAL_VERSION,
)
from etl.mart.compute_claim_scoring_features_v1 import FEATURE_VERSION
from etl.mart.compute_post_inspection_attention_signal_v1_candidate import (
    SIGNAL_VERSION as POST_INSPECTION_SIGNAL_VERSION,
)


def _load_dwh_utils():
    import dwh_utils
    return dwh_utils


CONFIG_PATH = BASE_DIR / "config" / "scoring" / "claim_attention_hybrid_v1_candidate.json"
REPORT_DIR = BASE_DIR / "data" / "quality_reports" / "scoring" / "claim_attention_hybrid_v1"

SCORE_VERSION = "IRIS_CLAIM_ATTENTION_HYBRID_V1_CANDIDATE"
PROFILE_NAME = "CLAIM_ATTENTION_HYBRID_V1_CANDIDATE"
SOURCE_SYSTEM = "IRIS_CLAIM_ATTENTION_HYBRID"

NON_ACCUSATORY_BLOCKLIST = (
    "fraud detected",
    "fraudulent",
    "proof of fraud",
    "fraude detectee",
    "fraude confirmee",
    "client fraudeur",
    "fraudeur",
)


def load_score_config(path: Path | str = CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    validate_score_config(config)
    return config


def validate_score_config(config: dict[str, Any]) -> None:
    required = ["score_version", "profile_name", "max_score", "business_rules", "post_inspection"]
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"Missing hybrid score config keys: {missing}")
    if config["score_version"] != SCORE_VERSION:
        raise ValueError(f"Config score_version must be {SCORE_VERSION}")
    max_score = int(config["max_score"])
    if max_score <= 0:
        raise ValueError("Config max_score must be positive.")

    business_config = config["business_rules"]
    post_config = config["post_inspection"]
    business_max = int(business_config.get("max_points", 0))
    post_max = int(post_config.get("max_points", 0))
    if business_max < 0 or post_max < 0:
        raise ValueError("Configured max point values must be non-negative.")
    if business_max + post_max > max_score:
        raise ValueError("Configured family maxima exceed the global max_score.")

    for section_name, weights in [
        ("rule_weights", business_config.get("rule_weights", {})),
        ("family_weights", business_config.get("family_weights", {})),
    ]:
        negative_keys = [key for key, value in weights.items() if float(value) < 0]
        if negative_keys:
            raise ValueError(f"Negative values are not allowed in {section_name}: {negative_keys}")

    family_caps = business_config.get("family_caps", {})
    negative_caps = [key for key, value in family_caps.items() if int(value) < 0]
    if negative_caps:
        raise ValueError(f"Negative family caps are not allowed: {negative_caps}")


def _num(value: Any, default: float = np.nan) -> float:
    try:
        if value is None or pd.isna(value):
            return default
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    number = _num(value, np.nan)
    if np.isnan(number):
        return default
    return int(round(number))


def _text(value: Any) -> str | None:
    try:
        if value is None or pd.isna(value):
            return None
    except TypeError:
        pass
    text_value = str(value).strip()
    return text_value or None


def _is_true(value: Any) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except TypeError:
        pass
    if isinstance(value, str):
        return value.strip().upper() in {"TRUE", "T", "YES", "Y", "1", "O", "OUI"}
    return bool(value)


def attention_level(score: int | float) -> str:
    score_int = int(max(0, min(100, round(float(score)))))
    if score_int <= 24:
        return "Analyse standard"
    if score_int <= 49:
        return "Points a verifier"
    if score_int <= 74:
        return "Examen renforce suggere"
    return "Examen prioritaire suggere"


def _severity(points: int) -> str:
    if points >= 15:
        return "HIGH"
    if points >= 8:
        return "MEDIUM"
    if points > 0:
        return "LOW"
    return "INFO"


def contains_accusatory_wording(text_value: object) -> bool:
    lowered = str(text_value or "").lower()
    return any(term in lowered for term in NON_ACCUSATORY_BLOCKLIST)


def _detail(
    *,
    claim_sk: Any,
    claim_business_id: Any,
    score_run_id: str,
    family: str,
    code: str,
    label: str,
    value: Any,
    points: int,
    explanation: str,
    created_at: datetime,
) -> dict[str, Any]:
    return {
        "claim_sk": claim_sk,
        "claim_business_id": _text(claim_business_id),
        "score_run_id": score_run_id,
        "score_version": SCORE_VERSION,
        "signal_family": family,
        "signal_code": code,
        "signal_label": label,
        "signal_value": "" if value is None else str(value),
        "points": int(points),
        "severity": _severity(int(points)),
        "business_explanation": explanation,
        "profile_name": PROFILE_NAME,
        "created_at": created_at,
    }


def _weighted_business_points(row: pd.Series, config: dict[str, Any]) -> int:
    business_config = config["business_rules"]
    rule_weights = business_config.get("rule_weights", {})
    family_weights = business_config.get("family_weights", {})
    default_weight = float(business_config.get("default_rule_weight", 1.0))
    rule_weight = float(rule_weights.get(str(row.get("rule_code")), default_weight))
    family_weight = float(family_weights.get(str(row.get("rule_family")), 1.0))
    candidate_points = _num(row.get("candidate_points"), 0.0)
    return max(0, int(round(candidate_points * rule_weight * family_weight)))


def _business_rule_details_for_claim(
    claim_signals: pd.DataFrame,
    score_run_id: str,
    config: dict[str, Any],
    created_at: datetime,
) -> list[dict[str, Any]]:
    if claim_signals.empty or not config["business_rules"].get("enabled", True):
        return []

    business_config = config["business_rules"]
    family_caps = business_config.get("family_caps", {})
    max_points = int(business_config.get("max_points", 70))
    exclude_quality = bool(business_config.get("exclude_data_quality_signals", True))

    signals = claim_signals.copy()
    if exclude_quality and "is_data_quality_signal" in signals.columns:
        signals = signals[~signals["is_data_quality_signal"].map(_is_true)].copy()
    signals = signals[pd.to_numeric(signals["candidate_points"], errors="coerce").fillna(0) > 0].copy()
    if signals.empty:
        return []

    signals["weighted_points"] = signals.apply(lambda row: _weighted_business_points(row, config), axis=1)
    signals = signals[signals["weighted_points"] > 0].copy()
    if signals.empty:
        return []

    signals = signals.sort_values(["weighted_points", "rule_severity_rank", "rule_code"], ascending=[False, False, True])
    details: list[dict[str, Any]] = []
    family_remaining = {
        family: int(family_caps.get(family, max_points))
        for family in signals["rule_family"].dropna().astype(str).unique()
    }
    total_remaining = max_points

    for _, signal in signals.iterrows():
        if total_remaining <= 0:
            break
        family = str(signal.get("rule_family"))
        remaining = min(total_remaining, family_remaining.get(family, max_points))
        points = min(int(signal["weighted_points"]), remaining)
        if points <= 0:
            continue
        details.append(_detail(
            claim_sk=signal.get("claim_sk"),
            claim_business_id=signal.get("claim_business_id"),
            score_run_id=score_run_id,
            family=f"Regles metier - {family}",
            code=str(signal.get("rule_code")),
            label=str(signal.get("rule_label")),
            value=signal.get("rule_observed_value"),
            points=points,
            explanation=str(signal.get("business_explanation")),
            created_at=created_at,
        ))
        total_remaining -= points
        family_remaining[family] = family_remaining.get(family, max_points) - points

    return details


def _post_inspection_detail_for_claim(
    claim_signals: pd.DataFrame,
    claim_row: pd.Series,
    score_run_id: str,
    config: dict[str, Any],
    created_at: datetime,
) -> dict[str, Any] | None:
    post_config = config["post_inspection"]
    if claim_signals.empty or not post_config.get("enabled", True):
        return None

    scenario_code = post_config.get("scenario_code", "A_INSPECTION_TO_CLAIM")
    signals = claim_signals[claim_signals["scenario_code"].eq(scenario_code)].copy()
    if signals.empty:
        return None

    confidence_points = post_config.get("confidence_points", {"HIGH": 25, "MEDIUM": 15, "LOW": 0})
    signals["configured_points"] = signals["confidence_level"].map(lambda level: int(confidence_points.get(str(level), 0)))
    signals["delay_sort"] = pd.to_numeric(signals.get("days_inspection_to_claim"), errors="coerce").fillna(999999)
    signals = signals.sort_values(["configured_points", "delay_sort"], ascending=[False, True])
    strongest = signals.iloc[0]
    points = min(int(strongest["configured_points"]), int(post_config.get("max_points", 25)))

    if points <= 0 and not post_config.get("include_zero_point_context", True):
        return None

    if points >= 25:
        code = "POST_INSPECTION_HIGH"
        label = "Verification post-inspection prioritaire suggeree"
    elif points > 0:
        code = "POST_INSPECTION_MEDIUM"
        label = "Signal post-inspection a examiner"
    else:
        code = "POST_INSPECTION_CONTEXT_ONLY"
        label = "Contexte technique post-inspection documente"

    zones = ", ".join(sorted(str(value) for value in signals["defective_zone"].dropna().unique()))
    value = {
        "signal_count": int(len(signals)),
        "strongest_confidence": strongest.get("confidence_level"),
        "min_delay_days": int(signals["delay_sort"].min()) if len(signals) else None,
        "zones": zones,
    }
    explanation = (
        "Un signal post-inspection Scenario A est disponible pour ce dossier. "
        "Il documente un sinistre survenu apres une inspection STAFFIM du meme vehicule et sert uniquement a prioriser la verification."
    )
    return _detail(
        claim_sk=claim_row.get("claim_sk"),
        claim_business_id=claim_row.get("claim_business_id"),
        score_run_id=score_run_id,
        family="Post-inspection",
        code=code,
        label=label,
        value=json.dumps(value, ensure_ascii=False, sort_keys=True),
        points=points,
        explanation=explanation,
        created_at=created_at,
    )


def _build_business_rule_detail_df(
    business_rule_signals: pd.DataFrame,
    score_run_id: str,
    config: dict[str, Any],
    created_at: datetime,
) -> pd.DataFrame:
    if business_rule_signals.empty or not config["business_rules"].get("enabled", True):
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    business_config = config["business_rules"]
    signals = business_rule_signals.copy()
    if business_config.get("exclude_data_quality_signals", True) and "is_data_quality_signal" in signals.columns:
        signals = signals[~signals["is_data_quality_signal"].map(_is_true)].copy()
    signals["candidate_points"] = pd.to_numeric(signals["candidate_points"], errors="coerce").fillna(0)
    signals = signals[signals["candidate_points"] > 0].copy()
    if signals.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    rule_weights = business_config.get("rule_weights", {})
    family_weights = business_config.get("family_weights", {})
    default_weight = float(business_config.get("default_rule_weight", 1.0))
    family_caps = business_config.get("family_caps", {})
    max_points = int(business_config.get("max_points", 70))

    signals["rule_weight"] = signals["rule_code"].astype(str).map(lambda code: float(rule_weights.get(code, default_weight)))
    signals["family_weight"] = signals["rule_family"].astype(str).map(lambda family: float(family_weights.get(family, 1.0)))
    signals["weighted_points"] = (signals["candidate_points"] * signals["rule_weight"] * signals["family_weight"]).round().astype(int)
    signals = signals[signals["weighted_points"] > 0].copy()
    if signals.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    signals["family_cap"] = signals["rule_family"].astype(str).map(lambda family: int(family_caps.get(family, max_points)))
    signals["rule_severity_rank"] = pd.to_numeric(signals.get("rule_severity_rank"), errors="coerce").fillna(0).astype(int)
    signals = signals.sort_values(
        ["claim_sk", "rule_family", "weighted_points", "rule_severity_rank", "rule_code"],
        ascending=[True, True, False, False, True],
    ).copy()
    signals["family_points_before"] = signals.groupby(["claim_sk", "rule_family"])["weighted_points"].cumsum() - signals["weighted_points"]
    signals["family_remaining"] = (signals["family_cap"] - signals["family_points_before"]).clip(lower=0)
    signals["family_capped_points"] = signals[["weighted_points", "family_remaining"]].min(axis=1).astype(int)
    signals = signals[signals["family_capped_points"] > 0].copy()
    if signals.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    signals = signals.sort_values(
        ["claim_sk", "family_capped_points", "rule_severity_rank", "rule_code"],
        ascending=[True, False, False, True],
    ).copy()
    signals["total_points_before"] = signals.groupby("claim_sk")["family_capped_points"].cumsum() - signals["family_capped_points"]
    signals["total_remaining"] = (max_points - signals["total_points_before"]).clip(lower=0)
    signals["points"] = signals[["family_capped_points", "total_remaining"]].min(axis=1).astype(int)
    signals = signals[signals["points"] > 0].copy()
    if signals.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    details = pd.DataFrame({
        "claim_sk": signals["claim_sk"],
        "claim_business_id": signals.get("claim_business_id"),
        "score_run_id": score_run_id,
        "score_version": SCORE_VERSION,
        "signal_family": "Regles metier - " + signals["rule_family"].astype(str),
        "signal_code": signals["rule_code"].astype(str),
        "signal_label": signals["rule_label"].astype(str),
        "signal_value": signals.get("rule_observed_value", pd.Series(index=signals.index, dtype="object")).fillna("").astype(str),
        "points": signals["points"].astype(int),
        "severity": signals["points"].map(lambda points: _severity(int(points))),
        "business_explanation": signals["business_explanation"].astype(str),
        "profile_name": PROFILE_NAME,
        "created_at": created_at,
    })
    return details[DETAIL_COLUMNS].copy()


def _build_post_inspection_detail_df(
    post_inspection_signals: pd.DataFrame,
    features: pd.DataFrame,
    score_run_id: str,
    config: dict[str, Any],
    created_at: datetime,
) -> pd.DataFrame:
    post_config = config["post_inspection"]
    if post_inspection_signals.empty or not post_config.get("enabled", True):
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    scenario_code = post_config.get("scenario_code", "A_INSPECTION_TO_CLAIM")
    signals = post_inspection_signals[post_inspection_signals["scenario_code"].eq(scenario_code)].copy()
    if signals.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    confidence_points = post_config.get("confidence_points", {"HIGH": 25, "MEDIUM": 15, "LOW": 0})
    signals["points"] = signals["confidence_level"].astype(str).map(lambda level: int(confidence_points.get(level, 0)))
    signals["points"] = signals["points"].clip(upper=int(post_config.get("max_points", 25)))
    if not post_config.get("include_zero_point_context", True):
        signals = signals[signals["points"] > 0].copy()
    if signals.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    signals["delay_sort"] = pd.to_numeric(signals.get("days_inspection_to_claim"), errors="coerce").fillna(999999)
    signals = signals.sort_values(["claim_sk", "points", "delay_sort"], ascending=[True, False, True]).copy()
    strongest = signals.drop_duplicates("claim_sk", keep="first").copy()
    zones = signals.groupby("claim_sk")["defective_zone"].apply(lambda values: ", ".join(sorted(set(str(value) for value in values.dropna()))))
    counts = signals.groupby("claim_sk").size().rename("signal_count")
    strongest = strongest.merge(zones.rename("zones"), on="claim_sk", how="left").merge(counts, on="claim_sk", how="left")
    strongest = strongest.merge(features[["claim_sk", "claim_business_id"]], on="claim_sk", how="left")

    def _post_code(points: int) -> str:
        if points >= 25:
            return "POST_INSPECTION_HIGH"
        if points > 0:
            return "POST_INSPECTION_MEDIUM"
        return "POST_INSPECTION_CONTEXT_ONLY"

    def _post_label(points: int) -> str:
        if points >= 25:
            return "Verification post-inspection prioritaire suggeree"
        if points > 0:
            return "Signal post-inspection a examiner"
        return "Contexte technique post-inspection documente"

    values = strongest.apply(lambda row: json.dumps({
        "signal_count": int(row.get("signal_count", 0)),
        "strongest_confidence": row.get("confidence_level"),
        "min_delay_days": None if pd.isna(row.get("delay_sort")) else int(row.get("delay_sort")),
        "zones": row.get("zones"),
    }, ensure_ascii=False, sort_keys=True), axis=1)

    details = pd.DataFrame({
        "claim_sk": strongest["claim_sk"],
        "claim_business_id": strongest.get("claim_business_id"),
        "score_run_id": score_run_id,
        "score_version": SCORE_VERSION,
        "signal_family": "Post-inspection",
        "signal_code": strongest["points"].astype(int).map(_post_code),
        "signal_label": strongest["points"].astype(int).map(_post_label),
        "signal_value": values,
        "points": strongest["points"].astype(int),
        "severity": strongest["points"].astype(int).map(_severity),
        "business_explanation": "Un signal post-inspection Scenario A est disponible pour ce dossier. Il documente un sinistre survenu apres une inspection STAFFIM du meme vehicule et sert uniquement a prioriser la verification.",
        "profile_name": PROFILE_NAME,
        "created_at": created_at,
    })
    return details[DETAIL_COLUMNS].copy()


def compute_claim_attention_hybrid_scores(
    features: pd.DataFrame,
    business_rule_signals: pd.DataFrame,
    post_inspection_signals: pd.DataFrame | None = None,
    config: dict[str, Any] | None = None,
    score_run_id: str | None = None,
    created_at: datetime | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    config = config or load_score_config()
    validate_score_config(config)
    score_run_id = score_run_id or f"{SCORE_VERSION}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    created_at = created_at or datetime.now(timezone.utc).replace(tzinfo=None)
    max_score = int(config.get("max_score", 100))

    post_inspection_signals = post_inspection_signals if post_inspection_signals is not None else pd.DataFrame()
    base = features.copy()
    if "claim_business_id" not in base.columns:
        base["claim_business_id"] = pd.NA
    if "feature_run_id" not in base.columns:
        base["feature_run_id"] = pd.NA
    if "confidence_level" not in base.columns:
        base["confidence_level"] = "LOW"

    business_details = _build_business_rule_detail_df(business_rule_signals, score_run_id, config, created_at)
    post_details = _build_post_inspection_detail_df(post_inspection_signals, base, score_run_id, config, created_at)
    details = pd.concat([business_details, post_details], ignore_index=True)
    if not details.empty:
        details["points"] = pd.to_numeric(details["points"], errors="coerce").fillna(0).astype(int)

    if not details.empty and (details["points"] > 0).any():
        positive_points = (
            details.loc[details["points"] > 0]
            .groupby("claim_sk")["points"]
            .sum()
            .rename("attention_score")
            .reset_index()
        )
    else:
        positive_points = pd.DataFrame(columns=["claim_sk", "attention_score"])
    scores = base[["claim_sk", "claim_business_id", "feature_run_id", "confidence_level"]].copy()
    scores = scores.merge(positive_points, on="claim_sk", how="left")
    scores["attention_score"] = pd.to_numeric(scores["attention_score"], errors="coerce").fillna(0).clip(lower=0, upper=max_score).astype(int)

    positive_details = details[details["points"] > 0].copy() if not details.empty else pd.DataFrame(columns=DETAIL_COLUMNS)
    if not positive_details.empty:
        positive_details = positive_details.sort_values(["claim_sk", "points", "signal_code"], ascending=[True, False, True])
        positive_details["reason_rank"] = positive_details.groupby("claim_sk").cumcount() + 1
        reasons = positive_details[positive_details["reason_rank"].le(3)].pivot(index="claim_sk", columns="reason_rank", values="signal_label")
        reasons = reasons.rename(columns={1: "main_reason_1", 2: "main_reason_2", 3: "main_reason_3"}).reset_index()
    else:
        reasons = pd.DataFrame(columns=["claim_sk", "main_reason_1", "main_reason_2", "main_reason_3"])
    scores = scores.merge(reasons, on="claim_sk", how="left")
    scores["main_reason_1"] = scores["main_reason_1"].fillna("Aucun signal prioritaire hybride")
    for col in ["main_reason_2", "main_reason_3"]:
        if col not in scores.columns:
            scores[col] = None
    scores["score_version"] = SCORE_VERSION
    scores["score_run_id"] = score_run_id
    scores["attention_level"] = scores["attention_score"].map(attention_level)
    scores["confidence_level"] = scores["confidence_level"].fillna("LOW")
    scores["profile_name"] = PROFILE_NAME
    scores["source_system"] = SOURCE_SYSTEM
    scores["created_at"] = created_at
    scores = scores[SCORE_COLUMNS].copy()

    return scores, details[DETAIL_COLUMNS].copy() if not details.empty else pd.DataFrame(columns=DETAIL_COLUMNS)

def validate_hybrid_outputs(scores: pd.DataFrame, details: pd.DataFrame) -> dict[str, int]:
    if scores.empty:
        return {
            "score_rows": 0,
            "detail_rows": int(len(details)),
            "duplicate_score_rows": 0,
            "score_out_of_range_rows": 0,
            "null_level_rows": 0,
            "detail_point_mismatch_rows": 0,
            "accusatory_wording_rows": 0,
        }

    positive_detail_points = (
        details.loc[pd.to_numeric(details["points"], errors="coerce") > 0]
        .groupby("claim_sk")["points"].sum()
        if not details.empty
        else pd.Series(dtype="int64")
    )
    comparison = scores.set_index("claim_sk")["attention_score"].subtract(positive_detail_points, fill_value=0)
    text_to_check = pd.concat([
        details.get("business_explanation", pd.Series(dtype="object")).fillna(""),
        scores.get("main_reason_1", pd.Series(dtype="object")).fillna(""),
        scores.get("main_reason_2", pd.Series(dtype="object")).fillna(""),
        scores.get("main_reason_3", pd.Series(dtype="object")).fillna(""),
    ], ignore_index=True)

    return {
        "score_rows": int(len(scores)),
        "detail_rows": int(len(details)),
        "duplicate_score_rows": int(scores.duplicated(["claim_sk", "score_version", "score_run_id"]).sum()),
        "score_out_of_range_rows": int((~scores["attention_score"].between(0, 100)).sum()),
        "null_level_rows": int(scores["attention_level"].isna().sum() + scores["confidence_level"].isna().sum()),
        "detail_point_mismatch_rows": int(comparison.ne(0).sum()),
        "accusatory_wording_rows": int(text_to_check.map(contains_accusatory_wording).sum()),
    }


def _write_hybrid_reports(scores: pd.DataFrame, details: pd.DataFrame, score_run_id: str, config: dict[str, Any]) -> dict[str, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    validation = validate_hybrid_outputs(scores, details)

    summary = pd.DataFrame([{
        "score_run_id": score_run_id,
        "score_version": SCORE_VERSION,
        "score_rows": len(scores),
        "detail_rows": len(details),
        "distinct_scored_claims": int(scores["claim_sk"].nunique()) if not scores.empty else 0,
        "positive_score_claims": int((scores["attention_score"] > 0).sum()) if not scores.empty else 0,
        "config_path": str(CONFIG_PATH),
    }])
    path = REPORT_DIR / "hybrid_score_load_summary.csv"
    summary.to_csv(path, index=False)
    paths["load_summary"] = path

    for filename, df in {
        "hybrid_score_distribution.csv": scores["attention_level"].value_counts(dropna=False).rename_axis("attention_level").reset_index(name="rows") if not scores.empty else pd.DataFrame(columns=["attention_level", "rows"]),
        "hybrid_confidence_distribution.csv": scores["confidence_level"].value_counts(dropna=False).rename_axis("confidence_level").reset_index(name="rows") if not scores.empty else pd.DataFrame(columns=["confidence_level", "rows"]),
        "hybrid_signal_family_summary.csv": details.groupby("signal_family", dropna=False).agg(signal_rows=("signal_code", "size"), total_points=("points", "sum")).reset_index() if not details.empty else pd.DataFrame(columns=["signal_family", "signal_rows", "total_points"]),
    }.items():
        path = REPORT_DIR / filename
        df.to_csv(path, index=False)
        paths[filename] = path

    config_path = REPORT_DIR / "hybrid_score_config_snapshot.json"
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    paths["config_snapshot"] = config_path

    validation_csv = REPORT_DIR / "hybrid_score_validation_summary.csv"
    pd.DataFrame([validation]).to_csv(validation_csv, index=False)
    paths["validation_csv"] = validation_csv

    validation_md = REPORT_DIR / "hybrid_score_validation_summary.md"
    lines = [
        "# Claim Attention Hybrid V1 candidate validation",
        "",
        f"- **Run ID:** `{score_run_id}`",
        f"- **Score version:** `{SCORE_VERSION}`",
        f"- **Score rows:** {len(scores)}",
        f"- **Signal detail rows:** {len(details)}",
        "",
        "Rules and weights are loaded from the JSON configuration snapshot.",
        "This score is a prioritization aid and does not modify Claim Attention Score V1 or VHS.",
        "",
        "## Validation",
        "",
        "| Check | Rows |",
        "|---|---:|",
    ]
    for key, value in validation.items():
        lines.append(f"| {key} | {value} |")
    validation_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    paths["validation_md"] = validation_md
    return paths


def _copy_frame_to_db(engine, df: pd.DataFrame, table_name: str, columns: list[str], chunksize: int = 100000) -> None:
    if df.empty:
        return

    columns_sql = ", ".join(columns)
    copy_sql = f"""
        COPY mart.{table_name} ({columns_sql})
        FROM STDIN WITH (FORMAT CSV, HEADER FALSE, DELIMITER E'\\t', NULL '\\N')
    """
    export = df[columns].copy()
    if "created_at" in export.columns:
        export["created_at"] = pd.to_datetime(export["created_at"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")

    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cursor:
            for start in range(0, len(export), chunksize):
                chunk = export.iloc[start:start + chunksize]
                buffer = StringIO()
                chunk.to_csv(
                    buffer,
                    sep="\t",
                    header=False,
                    index=False,
                    na_rep="\\N",
                    lineterminator="\n",
                )
                buffer.seek(0)
                cursor.copy_expert(copy_sql, buffer)
        raw_conn.commit()
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        raw_conn.close()

def _latest_run_id(engine, table_name: str, run_column: str, version_column: str, version: str) -> str | None:
    query = text(f"""
        SELECT {run_column}
        FROM {table_name}
        WHERE {version_column} = :version
        GROUP BY {run_column}
        ORDER BY MAX(created_at) DESC
        LIMIT 1
    """)
    with engine.connect() as conn:
        row = conn.execute(query, {"version": version}).fetchone()
    return None if row is None else str(row[0])


def _read_features(engine, feature_run_id: str) -> pd.DataFrame:
    query = text("""
        SELECT claim_sk, claim_business_id, feature_run_id, confidence_level
        FROM mart.fact_claim_scoring_features
        WHERE scoring_feature_version = :version
          AND feature_run_id = :run_id
    """)
    with engine.connect() as conn:
        return pd.read_sql(query, conn, params={"version": FEATURE_VERSION, "run_id": feature_run_id})


def _read_business_rule_signals(engine, signal_run_id: str | None) -> pd.DataFrame:
    if not signal_run_id:
        return pd.DataFrame()
    query = text("""
        SELECT *
        FROM mart.fact_claim_business_rule_signal
        WHERE signal_version = :version
          AND signal_run_id = :run_id
    """)
    with engine.connect() as conn:
        return pd.read_sql(query, conn, params={"version": BUSINESS_RULE_SIGNAL_VERSION, "run_id": signal_run_id})


def _read_post_inspection_signals(engine, signal_run_id: str | None) -> pd.DataFrame:
    if not signal_run_id:
        return pd.DataFrame()
    query = text("""
        SELECT *
        FROM mart.fact_post_inspection_attention_signal
        WHERE signal_version = :version
          AND signal_run_id = :run_id
    """)
    with engine.connect() as conn:
        return pd.read_sql(query, conn, params={"version": POST_INSPECTION_SIGNAL_VERSION, "run_id": signal_run_id})


def compute_claim_attention_hybrid_score_v1_candidate(
    feature_run_id: str | None = None,
    business_rule_signal_run_id: str | None = None,
    post_inspection_signal_run_id: str | None = None,
    config_path: Path | str = CONFIG_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if text is None:
        raise RuntimeError("SQLAlchemy is required to write hybrid claim attention score tables.")

    dwh_utils = _load_dwh_utils()
    config = load_score_config(config_path)
    today = datetime.now(timezone.utc).replace(tzinfo=None)
    score_run_id = f"{SCORE_VERSION}_{today.strftime('%Y%m%d_%H%M%S')}"
    logger = dwh_utils.setup_logging(score_run_id, log_name="compute_claim_attention_hybrid_score_v1_candidate")
    logger.info("=" * 70)
    logger.info(f"[RUN] {score_run_id}")
    logger.info(f"      profile={PROFILE_NAME} version={SCORE_VERSION}")
    logger.info("      hybrid configurable prioritization score only; no automatic decision")
    logger.info("=" * 70)

    engine = dwh_utils.build_engine(logger)
    with engine.begin() as conn:
        conn.execute(text(DDL_CREATE_SCHEMA))
        conn.execute(text(DDL_FACT_CLAIM_ATTENTION_SCORE))
        conn.execute(text(DDL_FACT_CLAIM_ATTENTION_SIGNAL_DETAIL))

    feature_run_id = feature_run_id or _latest_run_id(
        engine,
        "mart.fact_claim_scoring_features",
        "feature_run_id",
        "scoring_feature_version",
        FEATURE_VERSION,
    )
    if feature_run_id is None:
        raise RuntimeError("No feature run found in mart.fact_claim_scoring_features.")
    business_rule_signal_run_id = business_rule_signal_run_id or _latest_run_id(
        engine,
        "mart.fact_claim_business_rule_signal",
        "signal_run_id",
        "signal_version",
        BUSINESS_RULE_SIGNAL_VERSION,
    )
    post_inspection_signal_run_id = post_inspection_signal_run_id or _latest_run_id(
        engine,
        "mart.fact_post_inspection_attention_signal",
        "signal_run_id",
        "signal_version",
        POST_INSPECTION_SIGNAL_VERSION,
    )

    features = _read_features(engine, feature_run_id)
    business_rules = _read_business_rule_signals(engine, business_rule_signal_run_id)
    post_inspection = _read_post_inspection_signals(engine, post_inspection_signal_run_id)
    logger.info(f"features loaded              : {len(features)}")
    logger.info(f"business rule signals loaded : {len(business_rules)}")
    logger.info(f"post-inspection signals loaded: {len(post_inspection)}")

    scores, details = compute_claim_attention_hybrid_scores(
        features,
        business_rules,
        post_inspection,
        config=config,
        score_run_id=score_run_id,
        created_at=today,
    )
    validation = validate_hybrid_outputs(scores, details)
    logger.info(f"hybrid score rows: {len(scores)}")
    logger.info(f"hybrid detail rows: {len(details)}")
    logger.info(f"validation: {validation}")

    blocking_checks = [
        "duplicate_score_rows",
        "score_out_of_range_rows",
        "null_level_rows",
        "detail_point_mismatch_rows",
        "accusatory_wording_rows",
    ]
    failed_checks = {key: validation[key] for key in blocking_checks if validation.get(key, 0) > 0}
    if failed_checks:
        raise RuntimeError(f"Hybrid score validation failed: {failed_checks}")

    with engine.begin() as conn:
        conn.execute(text("""
            DELETE FROM mart.fact_claim_attention_score
            WHERE score_version = :version
              AND score_run_id = :run_id
        """), {"version": SCORE_VERSION, "run_id": score_run_id})
        conn.execute(text("""
            DELETE FROM mart.fact_claim_attention_signal_detail
            WHERE score_version = :version
              AND score_run_id = :run_id
        """), {"version": SCORE_VERSION, "run_id": score_run_id})
    _copy_frame_to_db(engine, scores, "fact_claim_attention_score", SCORE_COLUMNS)
    _copy_frame_to_db(engine, details, "fact_claim_attention_signal_detail", DETAIL_COLUMNS)

    report_paths = _write_hybrid_reports(scores, details, score_run_id, config)
    for name, path in report_paths.items():
        logger.info(f"report {name}: {path}")

    print("=" * 70)
    print(f"  score_run_id                 : {score_run_id}")
    print(f"  feature_run_id               : {feature_run_id}")
    print(f"  business_rule_signal_run_id  : {business_rule_signal_run_id}")
    print(f"  post_inspection_signal_run_id: {post_inspection_signal_run_id}")
    print(f"  scored claims                : {len(scores)}")
    print(f"  signal detail rows           : {len(details)}")
    print(f"  validation                   : {validation}")
    print(f"  report folder                : {REPORT_DIR}")
    print("=" * 70)
    return scores, details


if __name__ == "__main__":
    compute_claim_attention_hybrid_score_v1_candidate()