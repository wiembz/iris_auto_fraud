"""Candidate smart claim features for IRIS Decision Support V2.

This module is additive. It does not modify Claim Attention V1, VHS, or any
PostgreSQL table when imported or unit-tested. The functions operate on
DataFrames so the business logic can be validated before an ETL run is approved.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

SMART_FEATURE_VERSION = "IRIS_CLAIM_SMART_FEATURES_V2_CANDIDATE"
PROFILE_NAME = "CLAIM_SMART_FEATURES_V2_CANDIDATE"
DEFAULT_MIN_COHORT_SIZE = 20
COHORT_COLUMNS = ["code_garantie", "claim_type", "vehicle_category"]
HASH_SOURCE_COLUMNS = [
    "claim_sk",
    "claim_business_id",
    "feature_run_id",
    "claim_date",
    "claim_amount",
    "code_garantie",
    "claim_type",
    "vehicle_category",
    "expected_document_count",
    "available_document_count",
    "critical_document_missing_count",
    "days_claim_to_declaration",
    "claim_before_contract_start_flag",
    "client_claim_count_12m",
    "client_claim_count_24m",
    "vehicle_claim_count_12m",
    "vehicle_claim_count_24m",
    "days_since_previous_claim",
    "missing_client_flag",
    "missing_contract_flag",
    "missing_vehicle_flag",
    "missing_guarantee_flag",
    "missing_geo_flag",
    "unmapped_code_count",
    "invalid_claim_date_flag",
    "invalid_declaration_date_flag",
]

SMART_FEATURE_COLUMNS = [
    "claim_sk",
    "claim_business_id",
    "smart_feature_run_id",
    "smart_feature_version",
    "source_feature_run_id",
    "source_as_of_date",
    "calculated_at",
    "input_hash",
    "history_evaluable_flag",
    "chronology_evaluable_flag",
    "document_completeness_evaluable_flag",
    "data_quality_evaluable_flag",
    "expected_document_count",
    "available_document_count",
    "missing_document_count",
    "completeness_rate",
    "critical_document_missing_count",
    "declaration_delay_days",
    "claim_before_contract_start_flag",
    "declaration_before_claim_flag",
    "chronology_signal_count",
    "client_claim_count_12m",
    "client_claim_count_24m",
    "vehicle_claim_count_12m",
    "vehicle_claim_count_24m",
    "days_since_previous_claim",
    "comparison_reference_date",
    "similar_claim_count",
    "similar_claim_cohort_level",
    "comparison_reliability",
    "comparison_status_reason",
    "amount_median_similar",
    "amount_p75_similar",
    "amount_p90_similar",
    "amount_ratio_to_median",
    "geo_evaluable_flag",
    "geo_mapping_quality",
    "required_field_completeness_rate",
    "unknown_field_count",
    "unmapped_code_count",
    "invalid_date_count",
    "data_quality_level",
    "confidence_level",
]


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except TypeError:
        pass
    if isinstance(value, str):
        return value.strip().upper() in {"", "NULL", "NONE", "NAN", "UNKNOWN", "N/A"}
    return False


def _canonical_value(value: Any) -> Any:
    if _is_missing(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, float) and np.isnan(value):
        return None
    return value


def _hash_inputs(row: pd.Series, columns: list[str]) -> str:
    payload = {column: _canonical_value(row.get(column)) for column in sorted(columns)}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _num(value: Any, default: float = np.nan) -> float:
    if _is_missing(value):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    if _is_missing(value):
        return False
    if isinstance(value, str):
        return value.strip().upper() in {"TRUE", "T", "YES", "Y", "1", "O", "OUI"}
    return bool(value)


def _series_or_na(frame: pd.DataFrame, column: str) -> pd.Series:
    if column in frame.columns:
        return frame[column]
    return pd.Series([pd.NA] * len(frame), index=frame.index, dtype="object")


def _quality_level(required_rate: Any, unknown_count: Any, unmapped_count: Any, invalid_date_count: Any) -> str:
    if _is_missing(required_rate) or _is_missing(unknown_count) or _is_missing(unmapped_count) or _is_missing(invalid_date_count):
        return "NOT_EVALUABLE"
    required = float(required_rate)
    unknown = int(unknown_count)
    unmapped = int(unmapped_count)
    invalid = int(invalid_date_count)
    if required >= 0.95 and unknown == 0 and unmapped == 0 and invalid == 0:
        return "HIGH"
    if required >= 0.80 and unknown <= 1 and unmapped <= 1 and invalid <= 1:
        return "MEDIUM"
    return "LOW"


def _comparison_reliability(sample_size: int, min_cohort_size: int) -> str:
    if sample_size >= min_cohort_size:
        return "DISPLAYABLE"
    if sample_size > 0:
        return "INSUFFICIENT_SAMPLE"
    return "NOT_AVAILABLE"


def _cohort_level(available_columns: list[str]) -> str:
    if set(["code_garantie", "claim_type", "vehicle_category"]).issubset(available_columns):
        return "PRECISE"
    if set(["code_garantie", "claim_type"]).issubset(available_columns):
        return "BROAD"
    if "code_garantie" in available_columns:
        return "GENERAL"
    return "NOT_AVAILABLE"


def _to_datetime_series(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce")


def add_similar_claim_statistics(
    frame: pd.DataFrame,
    *,
    min_cohort_size: int = DEFAULT_MIN_COHORT_SIZE,
) -> pd.DataFrame:
    """Add point-in-time cohort statistics, excluding current claim by claim_sk."""
    out = frame.copy()
    if out.empty:
        return out

    for column in [
        "similar_claim_count",
        "amount_median_similar",
        "amount_p75_similar",
        "amount_p90_similar",
        "amount_ratio_to_median",
    ]:
        out[column] = np.nan
    out["similar_claim_cohort_level"] = "NOT_AVAILABLE"
    out["comparison_reliability"] = "NOT_AVAILABLE"
    out["comparison_status_reason"] = "NOT_AVAILABLE"
    out["comparison_reference_date"] = pd.NaT

    required_base = {"claim_sk", "claim_amount", "claim_date"}
    if not required_base.issubset(out.columns):
        out["comparison_status_reason"] = "MISSING_REFERENCE_DATE" if "claim_date" not in out.columns else "NOT_AVAILABLE"
        return out

    available_cohort_columns = [column for column in COHORT_COLUMNS if column in out.columns]
    if not available_cohort_columns:
        out["comparison_status_reason"] = "MISSING_COHORT_ATTRIBUTES"
        return out

    amounts = pd.to_numeric(out["claim_amount"], errors="coerce")
    claim_dates = _to_datetime_series(out["claim_date"])
    out["comparison_reference_date"] = claim_dates

    for idx, row in out.iterrows():
        current_claim_sk = row.get("claim_sk")
        current_date = claim_dates.loc[idx]
        current_amount = _num(row.get("claim_amount"), np.nan)
        if pd.isna(current_date):
            out.at[idx, "comparison_status_reason"] = "MISSING_REFERENCE_DATE"
            continue
        if np.isnan(current_amount):
            out.at[idx, "comparison_status_reason"] = "NOT_AVAILABLE"
            continue

        row_cohort_columns = [column for column in available_cohort_columns if not _is_missing(row.get(column))]
        if not row_cohort_columns:
            out.at[idx, "comparison_status_reason"] = "MISSING_COHORT_ATTRIBUTES"
            continue

        mask = pd.Series(True, index=out.index)
        for column in row_cohort_columns:
            mask &= out[column].map(lambda value: not _is_missing(value))
            mask &= out[column].eq(row.get(column))
        mask &= out["claim_sk"].ne(current_claim_sk)
        mask &= claim_dates.lt(current_date)
        mask &= amounts.notna()
        mask &= amounts.ge(0)

        cohort = out.loc[mask, ["claim_sk"]].copy()
        cohort["amount"] = amounts[mask]
        cohort = cohort.drop_duplicates("claim_sk", keep="last")
        cohort_amounts = cohort["amount"].dropna()
        sample_size = int(len(cohort_amounts))
        out.at[idx, "similar_claim_count"] = sample_size
        out.at[idx, "similar_claim_cohort_level"] = _cohort_level(row_cohort_columns)
        out.at[idx, "comparison_reliability"] = _comparison_reliability(sample_size, min_cohort_size)
        out.at[idx, "comparison_status_reason"] = out.at[idx, "comparison_reliability"]
        if sample_size >= min_cohort_size:
            median = float(cohort_amounts.median())
            out.at[idx, "amount_median_similar"] = median
            out.at[idx, "amount_p75_similar"] = float(cohort_amounts.quantile(0.75))
            out.at[idx, "amount_p90_similar"] = float(cohort_amounts.quantile(0.90))
            if median > 0:
                out.at[idx, "amount_ratio_to_median"] = current_amount / median
            else:
                out.at[idx, "comparison_reliability"] = "NOT_AVAILABLE"
                out.at[idx, "comparison_status_reason"] = "ZERO_MEDIAN"
    return out


def compute_claim_smart_features_v2(
    source_features: pd.DataFrame,
    *,
    smart_feature_run_id: str = "TEST_SMART_FEATURE_RUN",
    source_as_of_date: str | None = None,
    calculated_at: datetime | None = None,
    min_cohort_size: int = DEFAULT_MIN_COHORT_SIZE,
    geo_ready: bool = False,
) -> pd.DataFrame:
    """Build candidate smart features from existing claim-level features."""
    calculated_at = calculated_at or datetime.now(timezone.utc)
    frame = source_features.copy()
    if frame.empty:
        return pd.DataFrame(columns=SMART_FEATURE_COLUMNS)

    frame = add_similar_claim_statistics(frame, min_cohort_size=min_cohort_size)
    out = pd.DataFrame(index=frame.index)
    out["claim_sk"] = frame["claim_sk"]
    out["claim_business_id"] = _series_or_na(frame, "claim_business_id")
    out["smart_feature_run_id"] = smart_feature_run_id
    out["smart_feature_version"] = SMART_FEATURE_VERSION
    out["source_feature_run_id"] = _series_or_na(frame, "feature_run_id")
    out["source_as_of_date"] = source_as_of_date
    out["calculated_at"] = calculated_at
    input_columns = [column for column in HASH_SOURCE_COLUMNS if column in frame.columns]
    out["input_hash"] = frame.apply(lambda row: _hash_inputs(row, input_columns), axis=1)

    document_columns_present = {"expected_document_count", "available_document_count"}.issubset(frame.columns)
    expected = pd.to_numeric(_series_or_na(frame, "expected_document_count"), errors="coerce")
    available = pd.to_numeric(_series_or_na(frame, "available_document_count"), errors="coerce")
    critical_missing = pd.to_numeric(_series_or_na(frame, "critical_document_missing_count"), errors="coerce")
    out["document_completeness_evaluable_flag"] = bool(document_columns_present) & expected.notna() & available.notna() & expected.gt(0)
    out["expected_document_count"] = expected.astype("Int64")
    out["available_document_count"] = available.astype("Int64")
    out["missing_document_count"] = (expected - available).where(out["document_completeness_evaluable_flag"]).clip(lower=0).astype("Int64")
    out["completeness_rate"] = (available / expected).where(out["document_completeness_evaluable_flag"]).clip(upper=1.0)
    out["critical_document_missing_count"] = critical_missing.astype("Int64")

    delay_present = "days_claim_to_declaration" in frame.columns
    contract_flag_present = "claim_before_contract_start_flag" in frame.columns
    delay = pd.to_numeric(_series_or_na(frame, "days_claim_to_declaration"), errors="coerce")
    out["declaration_delay_days"] = delay
    out["chronology_evaluable_flag"] = (bool(delay_present) & delay.notna()) | bool(contract_flag_present)
    out["claim_before_contract_start_flag"] = _series_or_na(frame, "claim_before_contract_start_flag").map(_bool) if contract_flag_present else False
    out["declaration_before_claim_flag"] = delay.lt(0).where(delay.notna(), False)
    out["chronology_signal_count"] = (
        out["claim_before_contract_start_flag"].astype(int) + out["declaration_before_claim_flag"].astype(int)
    ).where(out["chronology_evaluable_flag"], pd.NA).astype("Int64")

    history_columns = [
        "client_claim_count_12m",
        "client_claim_count_24m",
        "vehicle_claim_count_12m",
        "vehicle_claim_count_24m",
        "days_since_previous_claim",
    ]
    present_history_columns = [column for column in history_columns if column in frame.columns]
    out["history_evaluable_flag"] = bool(present_history_columns)
    for column in history_columns:
        out[column] = pd.to_numeric(_series_or_na(frame, column), errors="coerce")

    for column in [
        "comparison_reference_date",
        "similar_claim_count",
        "similar_claim_cohort_level",
        "comparison_reliability",
        "comparison_status_reason",
        "amount_median_similar",
        "amount_p75_similar",
        "amount_p90_similar",
        "amount_ratio_to_median",
    ]:
        out[column] = frame[column]

    out["geo_evaluable_flag"] = bool(geo_ready)
    out["geo_mapping_quality"] = "READY" if geo_ready else "PARTIAL"

    quality_flags = [
        "missing_client_flag",
        "missing_contract_flag",
        "missing_vehicle_flag",
        "missing_guarantee_flag",
        "missing_geo_flag",
    ]
    known_quality_columns = [column for column in quality_flags if column in frame.columns]
    out["data_quality_evaluable_flag"] = bool(known_quality_columns)
    if known_quality_columns:
        missing_counts = frame[known_quality_columns].apply(lambda col: col.map(_bool)).sum(axis=1).astype(int)
        out["unknown_field_count"] = missing_counts
        out["required_field_completeness_rate"] = 1 - (missing_counts / len(known_quality_columns))
    else:
        out["unknown_field_count"] = pd.Series([pd.NA] * len(frame), index=frame.index, dtype="Int64")
        out["required_field_completeness_rate"] = np.nan

    unmapped_present = "unmapped_code_count" in frame.columns
    invalid_date_flags = [column for column in ["invalid_claim_date_flag", "invalid_declaration_date_flag"] if column in frame.columns]
    out["unmapped_code_count"] = pd.to_numeric(_series_or_na(frame, "unmapped_code_count"), errors="coerce").astype("Int64")
    if invalid_date_flags:
        out["invalid_date_count"] = frame[invalid_date_flags].apply(lambda col: col.map(_bool)).sum(axis=1).astype("Int64")
    else:
        out["invalid_date_count"] = pd.Series([pd.NA] * len(frame), index=frame.index, dtype="Int64")
    out["data_quality_evaluable_flag"] = out["data_quality_evaluable_flag"] & bool(unmapped_present) & bool(invalid_date_flags)

    out["data_quality_level"] = [
        _quality_level(rate, unknown, unmapped, invalid)
        for rate, unknown, unmapped, invalid in zip(
            out["required_field_completeness_rate"],
            out["unknown_field_count"],
            out["unmapped_code_count"],
            out["invalid_date_count"],
        )
    ]
    out["confidence_level"] = out["data_quality_level"]

    return out[SMART_FEATURE_COLUMNS].reset_index(drop=True)
