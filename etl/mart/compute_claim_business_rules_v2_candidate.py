"""Configurable candidate business rules for Claim Attention V2."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from etl.utils.business_language import contains_forbidden_business_wording

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BASE_DIR / "config" / "claim_attention" / "rules_v2_candidate.json"
RULE_CATALOG_VERSION = "IRIS_CLAIM_BUSINESS_RULES_V2_CANDIDATE"
SCORE_VERSION = "IRIS_CLAIM_ATTENTION_V2_CANDIDATE"
ALLOWED_OPERATORS = {">=", ">", "<=", "==", "in", "is_true"}
KNOWN_ACTION_CODES = {
    "ACT_VERIFY_CHRONOLOGY",
    "ACT_REVIEW_CLIENT_HISTORY",
    "ACT_COMPARE_ESTIMATE",
    "ACT_REQUEST_REQUIRED_DOCUMENTS",
    "ACT_COMPLETE_INFORMATION",
}

SIGNAL_COLUMNS = [
    "claim_sk",
    "claim_business_id",
    "smart_feature_run_id",
    "source_as_of_date",
    "input_hash",
    "rule_code",
    "rule_family",
    "rule_version",
    "label_business",
    "rule_value",
    "raw_points",
    "points",
    "family_cap",
    "attention_level",
    "business_explanation",
    "suggested_action_code",
    "rule_catalog_version",
    "rule_catalog_hash",
    "created_at",
]


def catalog_hash(catalog: dict[str, Any]) -> str:
    payload = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_rule_catalog(path: Path | str = CONFIG_PATH) -> dict[str, Any]:
    """Load a dependency-free JSON rule catalog."""
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        catalog = json.load(handle)
    validate_rule_catalog(catalog)
    return catalog


def contains_accusatory_wording(value: object) -> bool:
    return contains_forbidden_business_wording(value)


def _as_non_negative_int(value: Any, *, field_name: str, rule_code: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Rule {rule_code} has non-numeric {field_name}") from exc
    if parsed < 0:
        raise ValueError(f"Rule {rule_code} has negative {field_name}")
    return parsed


def _validate_condition(rule: dict[str, Any]) -> None:
    rule_code = str(rule.get("rule_code"))
    condition = rule.get("condition")
    if not isinstance(condition, dict):
        raise ValueError(f"Rule {rule_code} condition must be an object")
    for key in ["field", "operator"]:
        if key not in condition:
            raise ValueError(f"Rule {rule_code} condition missing {key}")
    operator = condition["operator"]
    if operator not in ALLOWED_OPERATORS:
        raise ValueError(f"Rule {rule_code} uses unsupported operator {operator}")
    if operator != "is_true" and "value" not in condition:
        raise ValueError(f"Rule {rule_code} condition missing value")
    required_fields = set(rule["required_fields"])
    if condition["field"] not in required_fields:
        raise ValueError(f"Rule {rule_code} condition field must be declared in required_fields")
    requires = condition.get("requires", {})
    if requires is not None and not isinstance(requires, dict):
        raise ValueError(f"Rule {rule_code} requires must be an object")
    undeclared_requires = sorted(set((requires or {}).keys()) - required_fields)
    if undeclared_requires:
        raise ValueError(f"Rule {rule_code} requires undeclared fields: {undeclared_requires}")


def validate_rule_catalog(catalog: dict[str, Any]) -> None:
    required = {"catalog_version", "score_version", "max_score", "family_caps", "rules"}
    missing = required - set(catalog)
    if missing:
        raise ValueError(f"Missing rule catalog keys: {sorted(missing)}")
    if catalog["catalog_version"] != RULE_CATALOG_VERSION:
        raise ValueError(f"catalog_version must be {RULE_CATALOG_VERSION}")
    if catalog["score_version"] != SCORE_VERSION:
        raise ValueError(f"score_version must be {SCORE_VERSION}")
    max_score = _as_non_negative_int(catalog["max_score"], field_name="max_score", rule_code="<catalog>")
    if max_score != 100:
        raise ValueError("max_score must be 100 for Claim Attention V2 candidate.")
    family_caps = catalog["family_caps"]
    if not isinstance(family_caps, dict) or not family_caps:
        raise ValueError("family_caps must be a non-empty object")
    parsed_caps = {
        family: _as_non_negative_int(cap, field_name="family cap", rule_code=f"<family:{family}>")
        for family, cap in family_caps.items()
    }
    if not isinstance(catalog["rules"], list) or not catalog["rules"]:
        raise ValueError("rules must be a non-empty list")

    seen: set[str] = set()
    for rule in catalog["rules"]:
        for key in [
            "rule_code",
            "rule_family",
            "version",
            "label_business",
            "description",
            "attention_level",
            "required_fields",
            "condition",
            "points",
            "family_cap",
            "is_active",
            "business_explanation",
            "suggested_action_code",
        ]:
            if key not in rule:
                raise ValueError(f"Rule {rule.get('rule_code')} missing {key}")
        rule_code = str(rule["rule_code"])
        if rule_code in seen:
            raise ValueError(f"Duplicate rule_code: {rule_code}")
        seen.add(rule_code)
        if rule["rule_family"] not in parsed_caps:
            raise ValueError(f"Rule {rule_code} family missing from family_caps")
        if not isinstance(rule["is_active"], bool):
            raise ValueError(f"Rule {rule_code} is_active must be bool")
        if not isinstance(rule["required_fields"], list) or not rule["required_fields"]:
            raise ValueError(f"Rule {rule_code} required_fields must be a non-empty list")
        points = _as_non_negative_int(rule["points"], field_name="points", rule_code=rule_code)
        family_cap = _as_non_negative_int(rule["family_cap"], field_name="family_cap", rule_code=rule_code)
        if family_cap > parsed_caps[rule["rule_family"]]:
            raise ValueError(f"Rule {rule_code} family_cap exceeds catalog family cap")
        if points > family_cap and family_cap > 0:
            raise ValueError(f"Rule {rule_code} points exceed rule family_cap")
        if rule["suggested_action_code"] not in KNOWN_ACTION_CODES:
            raise ValueError(f"Rule {rule_code} suggested_action_code is unknown")
        _validate_condition(rule)
        for text_field in ["label_business", "description", "attention_level", "business_explanation"]:
            if contains_forbidden_business_wording(rule[text_field]):
                raise ValueError(f"Rule {rule_code} contains accusatory wording in {text_field}")


def _missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except TypeError:
        pass
    return isinstance(value, str) and value.strip() == ""


def _num(value: Any) -> float:
    if _missing(value):
        return np.nan
    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def _truthy(value: Any) -> bool:
    if _missing(value):
        return False
    if isinstance(value, str):
        return value.strip().upper() in {"TRUE", "T", "YES", "Y", "1", "O", "OUI"}
    return bool(value)


def _condition_matches(row: pd.Series, condition: dict[str, Any]) -> bool:
    for required_field, expected in condition.get("requires", {}).items():
        if row.get(required_field) != expected:
            return False

    field = condition["field"]
    operator = condition["operator"]
    expected = condition.get("value")
    observed = row.get(field)
    if _missing(observed):
        return False
    if operator == ">=":
        return _num(observed) >= float(expected)
    if operator == ">":
        return _num(observed) > float(expected)
    if operator == "<=":
        return _num(observed) <= float(expected)
    if operator == "==":
        return observed == expected
    if operator == "in":
        return observed in set(expected)
    if operator == "is_true":
        return _truthy(observed)
    raise ValueError(f"Unsupported rule operator: {operator}")


def _required_fields_available(row: pd.Series, required_fields: list[str]) -> bool:
    return all(field in row.index and not _missing(row.get(field)) for field in required_fields)


def _series_missing(values: pd.Series) -> pd.Series:
    missing = values.isna()
    if values.dtype == "object" or str(values.dtype).startswith("string"):
        missing = missing | values.astype("string").str.strip().eq("").fillna(True)
    return missing


def _truthy_series(values: pd.Series) -> pd.Series:
    if values.dtype == bool:
        return values.fillna(False)
    if str(values.dtype).lower() == "boolean":
        return values.fillna(False).astype(bool)
    return values.astype("string").str.strip().str.upper().isin({"TRUE", "T", "YES", "Y", "1", "O", "OUI"})


def _condition_mask(frame: pd.DataFrame, condition: dict[str, Any]) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    for required_field, expected in (condition.get("requires") or {}).items():
        if required_field not in frame.columns:
            return pd.Series(False, index=frame.index)
        mask &= frame[required_field].eq(expected)

    field = condition["field"]
    if field not in frame.columns:
        return pd.Series(False, index=frame.index)
    observed = frame[field]
    mask &= ~_series_missing(observed)

    operator = condition["operator"]
    expected = condition.get("value")
    if operator == ">=":
        mask &= pd.to_numeric(observed, errors="coerce").ge(float(expected))
    elif operator == ">":
        mask &= pd.to_numeric(observed, errors="coerce").gt(float(expected))
    elif operator == "<=":
        mask &= pd.to_numeric(observed, errors="coerce").le(float(expected))
    elif operator == "==":
        mask &= observed.eq(expected)
    elif operator == "in":
        mask &= observed.isin(set(expected))
    elif operator == "is_true":
        mask &= _truthy_series(observed)
    else:
        raise ValueError(f"Unsupported rule operator: {operator}")
    return mask.fillna(False)
def compute_claim_business_rules_v2(
    smart_features: pd.DataFrame,
    catalog: dict[str, Any] | None = None,
    *,
    created_at: datetime | None = None,
) -> pd.DataFrame:
    """Evaluate active V2 rules against smart features."""
    catalog = catalog or load_rule_catalog()
    validate_rule_catalog(catalog)
    catalog_digest = catalog_hash(catalog)
    created_at = created_at or datetime.now(timezone.utc)
    if smart_features.empty:
        return pd.DataFrame(columns=SIGNAL_COLUMNS)

    base_columns = [
        "claim_sk",
        "claim_business_id",
        "smart_feature_run_id",
        "source_as_of_date",
        "input_hash",
    ]
    frames: list[pd.DataFrame] = []
    for rule in catalog["rules"]:
        if not rule["is_active"]:
            continue
        required_fields = list(rule["required_fields"])
        if any(field not in smart_features.columns for field in required_fields):
            continue
        available_mask = pd.Series(True, index=smart_features.index)
        for field in required_fields:
            available_mask &= ~_series_missing(smart_features[field])
        mask = available_mask & _condition_mask(smart_features, rule["condition"])
        if not mask.any():
            continue

        condition_field = rule["condition"]["field"]
        available_base_columns = [column for column in base_columns if column in smart_features.columns]
        matched = smart_features.loc[mask, available_base_columns].copy()
        for column in base_columns:
            if column not in matched.columns:
                matched[column] = pd.NA
        matched = matched[base_columns]
        matched["rule_code"] = rule["rule_code"]
        matched["rule_family"] = rule["rule_family"]
        matched["rule_version"] = rule["version"]
        matched["label_business"] = rule["label_business"]
        matched["rule_value"] = smart_features.loc[mask, condition_field].map(lambda value: "" if _missing(value) else str(value))
        matched["raw_points"] = int(rule["points"])
        matched["points"] = int(rule["points"])
        matched["family_cap"] = int(rule["family_cap"])
        matched["attention_level"] = rule["attention_level"]
        matched["business_explanation"] = rule["business_explanation"]
        matched["suggested_action_code"] = rule["suggested_action_code"]
        matched["rule_catalog_version"] = catalog["catalog_version"]
        matched["rule_catalog_hash"] = catalog_digest
        matched["created_at"] = created_at
        frames.append(matched[SIGNAL_COLUMNS])

    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=SIGNAL_COLUMNS)
    if not result.empty:
        for column in ["label_business", "business_explanation", "attention_level"]:
            if result[column].map(contains_forbidden_business_wording).any():
                raise ValueError("Accusatory wording detected in generated business rules.")
        result = result.drop_duplicates(["claim_sk", "rule_code"]).reset_index(drop=True)
    return result