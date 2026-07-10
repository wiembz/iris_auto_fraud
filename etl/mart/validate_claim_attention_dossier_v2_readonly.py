"""Read-only dossier-level validation for Claim Attention V2 candidate."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "etl" / "dwh"))

from etl.mart.compute_claim_attention_dossier_v2_candidate import (
    AGGREGATION_VERSION,
    aggregate_claim_attention_dossier_v2,
    prepare_guarantee_scores,
)
from etl.mart.compute_claim_attention_hybrid_score_v1_candidate import SCORE_VERSION as DEFAULT_V1_SCORE_VERSION
from etl.mart.compute_claim_attention_score_v2_candidate import compute_claim_attention_score_v2
from etl.mart.compute_claim_smart_features_v2_candidate import compute_claim_smart_features_v2
from etl.mart.validate_claim_smart_decision_v2_readonly import read_latest_features, read_v1_scores

REPORT_DIR = BASE_DIR / "data" / "quality_reports" / "scoring" / "claim_dossier_v2_validation"
VALIDATION_PROFILE = "IRIS_CLAIM_DOSSIER_GRAIN_V2_READONLY_VALIDATION"


def _load_dwh_utils():
    import dwh_utils

    return dwh_utils


def _count_distribution(frame: pd.DataFrame, column: str, count_name: str = "rows") -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return pd.DataFrame(columns=[column, count_name])
    return frame[column].value_counts(dropna=False).rename_axis(column).reset_index(name=count_name)


def _score_distribution(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return pd.DataFrame()
    return frame[column].describe(percentiles=[0.25, 0.5, 0.75, 0.9, 0.95]).reset_index(name="value")


def _aggregate_v1_to_dossier(v1_scores: pd.DataFrame) -> pd.DataFrame:
    if v1_scores.empty:
        return pd.DataFrame(columns=["claim_root_id", "attention_score_v1_dossier", "attention_level_v1_dossier"])
    source = v1_scores.rename(columns={
        "attention_score_v1": "attention_score",
        "attention_level_v1": "attention_level",
        "confidence_level_v1": "confidence_level",
        "score_run_id_v1": "score_run_id",
        "score_version_v1": "score_version",
    }).copy()
    source["main_reason_1"] = pd.NA
    source["main_reason_2"] = pd.NA
    source["main_reason_3"] = pd.NA
    dossier, _ = aggregate_claim_attention_dossier_v2(source, pd.DataFrame(), aggregation_run_id="V1_DOSSIER_REFERENCE")
    return dossier[["claim_root_id", "dossier_attention_score", "dossier_attention_level"]].rename(columns={
        "dossier_attention_score": "attention_score_v1_dossier",
        "dossier_attention_level": "attention_level_v1_dossier",
    })


def _dossier_v1_v2_comparison(dossier_v2: pd.DataFrame, v1_scores: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    v1_dossier = _aggregate_v1_to_dossier(v1_scores)
    comparison = dossier_v2.merge(v1_dossier, on="claim_root_id", how="left")
    comparison["score_delta_v2_minus_v1"] = pd.to_numeric(comparison["dossier_attention_score"], errors="coerce") - pd.to_numeric(comparison["attention_score_v1_dossier"], errors="coerce")
    transitions = (
        comparison.groupby(["attention_level_v1_dossier", "dossier_attention_level"], dropna=False)
        .size()
        .reset_index(name="claim_roots")
        .sort_values("claim_roots", ascending=False)
    )
    return comparison, transitions


def _aggregation_change_summary(guarantee_scores: pd.DataFrame, dossier_scores: pd.DataFrame) -> pd.DataFrame:
    prepared = prepare_guarantee_scores(guarantee_scores)
    mixed = prepared.groupby("claim_root_id").agg(
        guarantee_row_count=("claim_sk", "size"),
        distinct_guarantee_scores=("attention_score", "nunique"),
        distinct_guarantee_levels=("attention_level", "nunique"),
    ).reset_index()
    summary = pd.DataFrame([{
        "claim_root_rows": len(dossier_scores),
        "multi_guarantee_claim_roots": int(mixed["guarantee_row_count"].gt(1).sum()),
        "claim_roots_with_multiple_guarantee_scores": int(mixed["distinct_guarantee_scores"].gt(1).sum()),
        "claim_roots_with_multiple_guarantee_levels": int(mixed["distinct_guarantee_levels"].gt(1).sum()),
        "max_guarantee_rows_per_claim_root": int(mixed["guarantee_row_count"].max()) if not mixed.empty else 0,
    }])
    return summary


def _contradictory_motifs(dossier_details: pd.DataFrame) -> pd.DataFrame:
    if dossier_details.empty:
        return pd.DataFrame(columns=["claim_root_id", "rule_family", "distinct_labels", "labels"])
    active = dossier_details[dossier_details["awarded_points"].fillna(0).gt(0)].copy()
    if active.empty:
        return pd.DataFrame(columns=["claim_root_id", "rule_family", "distinct_labels", "labels"])
    grouped = active.groupby(["claim_root_id", "rule_family"], dropna=False).agg(
        distinct_labels=("business_label", "nunique"),
        labels=("business_label", lambda values: ",".join(sorted({str(value) for value in values.dropna()}))),
    ).reset_index()
    return grouped[grouped["distinct_labels"].gt(1)].sort_values(["distinct_labels", "claim_root_id"], ascending=[False, True])


def _stratified_sample(dossier_scores: pd.DataFrame, comparison: pd.DataFrame, sample_size: int) -> pd.DataFrame:
    if dossier_scores.empty:
        return pd.DataFrame()
    enriched = dossier_scores.merge(
        comparison[["claim_root_id", "attention_level_v1_dossier", "score_delta_v2_minus_v1"]],
        on="claim_root_id",
        how="left",
    )
    groups = []
    for column, limit in [("dossier_attention_level", 20), ("guarantee_row_count", 20), ("confidence_level", 10), ("attention_level_v1_dossier", 20)]:
        if column in enriched.columns:
            groups.append(enriched.sort_values(["dossier_attention_score", "claim_root_id"], ascending=[False, True]).groupby(column, dropna=False).head(2).head(limit))
    groups.append(enriched[enriched["dossier_attention_score"].isin([0, 12, 15, 20, 24, 25, 27, 49, 50, 52, 74, 75])].head(30))
    sample = pd.concat(groups, ignore_index=True).drop_duplicates("claim_root_id").head(sample_size).copy()
    for column in [
        "business_review_grain_valid",
        "business_review_priority_valid",
        "business_review_reasons_valid",
        "business_review_comment",
    ]:
        sample[column] = ""
    return sample


def build_dossier_validation_reports(
    guarantee_scores: pd.DataFrame,
    guarantee_details: pd.DataFrame,
    v1_scores: pd.DataFrame,
    *,
    aggregation_run_id: str,
    sample_size: int = 100,
) -> dict[str, pd.DataFrame]:
    dossier_scores, dossier_details = aggregate_claim_attention_dossier_v2(
        guarantee_scores,
        guarantee_details,
        aggregation_run_id=aggregation_run_id,
    )
    comparison, transitions = _dossier_v1_v2_comparison(dossier_scores, v1_scores)
    load_summary = pd.DataFrame([{
        "validation_profile": VALIDATION_PROFILE,
        "aggregation_version": AGGREGATION_VERSION,
        "aggregation_run_id": aggregation_run_id,
        "guarantee_score_rows": len(guarantee_scores),
        "claim_root_rows": len(dossier_scores),
        "source_score_run_id": dossier_scores["source_score_run_id"].iloc[0] if not dossier_scores.empty else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }])
    validation_summary = pd.DataFrame([{
        "duplicate_claim_root_rows": int(dossier_scores.duplicated(["claim_root_id", "aggregation_version", "aggregation_run_id"]).sum()) if not dossier_scores.empty else 0,
        "score_out_of_range_rows": int((~dossier_scores["dossier_attention_score"].between(0, 100)).sum()) if not dossier_scores.empty else 0,
        "null_attention_level_rows": int(dossier_scores["dossier_attention_level"].isna().sum()) if not dossier_scores.empty else 0,
        "aggregation_rule": "MAX_GUARANTEE_SCORE_NO_SUM_NO_MULTI_GUARANTEE_BONUS",
    }])
    return {
        "claim_dossier_v2_load_summary.csv": load_summary,
        "claim_dossier_v2_validation_summary.csv": validation_summary,
        "claim_dossier_v2_score_distribution.csv": _score_distribution(dossier_scores, "dossier_attention_score"),
        "claim_dossier_v2_attention_level_distribution.csv": _count_distribution(dossier_scores, "dossier_attention_level", "claim_roots"),
        "claim_dossier_v2_confidence_distribution.csv": _count_distribution(dossier_scores, "confidence_level", "claim_roots"),
        "claim_dossier_v2_guarantee_count_distribution.csv": _count_distribution(dossier_scores, "guarantee_row_count", "claim_roots"),
        "claim_dossier_v2_aggregation_change_summary.csv": _aggregation_change_summary(guarantee_scores, dossier_scores),
        "claim_dossier_v2_v1_v2_comparison.csv": comparison,
        "claim_dossier_v2_v1_v2_level_transition.csv": transitions,
        "claim_dossier_v2_contradictory_motifs.csv": _contradictory_motifs(dossier_details),
        "claim_dossier_v2_business_validation_sample.csv": _stratified_sample(dossier_scores, comparison, sample_size),
    }


def write_reports(reports: dict[str, pd.DataFrame], output_dir: Path = REPORT_DIR) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for filename, frame in reports.items():
        path = output_dir / filename
        frame.to_csv(path, index=False)
        paths[filename] = path
    summary = reports["claim_dossier_v2_load_summary.csv"].iloc[0].to_dict()
    validation = reports["claim_dossier_v2_validation_summary.csv"].iloc[0].to_dict()
    lines = [
        "# Claim Dossier Grain V2 read-only validation",
        "",
        "This report aggregates guarantee-level V2 outputs to one candidate dossier-level worklist row.",
        "No PostgreSQL write, V1 modification, VHS modification, ML integration, or threshold recalibration is performed.",
        "",
        f"- Guarantee score rows: {summary.get('guarantee_score_rows')}",
        f"- Claim root rows: {summary.get('claim_root_rows')}",
        f"- Aggregation rule: {validation.get('aggregation_rule')}",
        f"- Duplicate dossier rows: {validation.get('duplicate_claim_root_rows')}",
        f"- Score out-of-range rows: {validation.get('score_out_of_range_rows')}",
        f"- Null attention level rows: {validation.get('null_attention_level_rows')}",
        "",
        "Business status: candidate read-only aggregation for BNA validation.",
    ]
    md_path = output_dir / "claim_dossier_v2_validation_summary.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    paths[md_path.name] = md_path
    return paths


def run_readonly_validation(*, sample_size: int = 100, output_dir: Path = REPORT_DIR) -> dict[str, Path]:
    dwh_utils = _load_dwh_utils()
    run_id = f"IRIS_CLAIM_DOSSIER_V2_READONLY_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    logger = dwh_utils.setup_logging(run_id, log_name="validate_claim_attention_dossier_v2_readonly")
    engine = dwh_utils.build_engine(logger)
    source_features, feature_run_id = read_latest_features(engine)
    v1_scores, _ = read_v1_scores(engine, DEFAULT_V1_SCORE_VERSION)
    smart_features = compute_claim_smart_features_v2(
        source_features,
        smart_feature_run_id=run_id,
        source_as_of_date=feature_run_id,
        geo_ready=False,
    )
    guarantee_scores, guarantee_details = compute_claim_attention_score_v2(smart_features, score_run_id=run_id)
    reports = build_dossier_validation_reports(
        guarantee_scores,
        guarantee_details,
        v1_scores,
        aggregation_run_id=run_id,
        sample_size=sample_size,
    )
    paths = write_reports(reports, output_dir)
    print("=" * 72)
    print("IRIS Claim Dossier V2 read-only validation complete")
    print(f"  guarantee rows : {len(guarantee_scores)}")
    print(f"  dossier rows   : {len(reports['claim_dossier_v2_score_distribution.csv']) and reports['claim_dossier_v2_load_summary.csv'].iloc[0]['claim_root_rows']}")
    print(f"  report folder  : {output_dir}")
    print("=" * 72)
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only dossier-level Claim Attention V2 validation")
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--output-dir", default=str(REPORT_DIR))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_readonly_validation(sample_size=args.sample_size, output_dir=Path(args.output_dir))


if __name__ == "__main__":
    main()
