"""
etl/mart/compute_claim_attention_hybrid_ml_score_v1_candidate.py
=================================================================
Combines the validated configurable hybrid score with the calibrated ML anomaly
signal in a separate candidate score version.

This score is a prioritization aid for human review. It is not a fraud proof,
not a legal conclusion, and not an automatic decision. It does not modify VHS,
Claim Attention Score V1, or the base hybrid score version.

Sources:
  mart.fact_claim_attention_score, base hybrid candidate
  mart.fact_claim_attention_signal_detail, base hybrid candidate details
  mart.fact_claim_ml_anomaly_signal

Outputs:
  mart.fact_claim_attention_score
  mart.fact_claim_attention_signal_detail
  data/quality_reports/scoring/claim_attention_hybrid_ml_v1/
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
from etl.mart.compute_claim_attention_hybrid_score_v1_candidate import (
    SCORE_VERSION as BASE_HYBRID_SCORE_VERSION,
    attention_level,
    validate_hybrid_outputs,
    _copy_frame_to_db,
)
from etl.mart.compute_claim_ml_anomaly_signal_v1_candidate import SIGNAL_VERSION as ML_SIGNAL_VERSION


def _load_dwh_utils():
    import dwh_utils
    return dwh_utils


CONFIG_PATH = BASE_DIR / "config" / "scoring" / "claim_attention_hybrid_ml_v1_candidate.json"
REPORT_DIR = BASE_DIR / "data" / "quality_reports" / "scoring" / "claim_attention_hybrid_ml_v1"

SCORE_VERSION = "IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE"
PROFILE_NAME = "CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE"
SOURCE_SYSTEM = "IRIS_CLAIM_ATTENTION_HYBRID_ML"


def load_hybrid_ml_config(path: Path | str = CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    validate_hybrid_ml_config(config)
    return config


def validate_hybrid_ml_config(config: dict[str, Any]) -> None:
    required = ["score_version", "profile_name", "max_score", "base_hybrid_score_version", "ml_signal_version", "ml"]
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"Missing hybrid ML config keys: {missing}")
    if config["score_version"] != SCORE_VERSION:
        raise ValueError(f"Config score_version must be {SCORE_VERSION}")
    if config["base_hybrid_score_version"] != BASE_HYBRID_SCORE_VERSION:
        raise ValueError(f"Base score version must be {BASE_HYBRID_SCORE_VERSION}")
    if config["ml_signal_version"] != ML_SIGNAL_VERSION:
        raise ValueError(f"ML signal version must be {ML_SIGNAL_VERSION}")
    if int(config.get("max_score", 0)) <= 0:
        raise ValueError("max_score must be positive.")
    if int(config["ml"].get("max_points", 0)) < 0:
        raise ValueError("ml.max_points must be non-negative.")


def _severity(points: int) -> str:
    if points >= 8:
        return "HIGH"
    if points >= 4:
        return "MEDIUM"
    if points > 0:
        return "LOW"
    return "INFO"


def _ml_signal_code(points: int) -> str:
    if points >= 8:
        return "ML_ANOMALY_HIGH_PERCENTILE"
    if points >= 4:
        return "ML_ANOMALY_MEDIUM_PERCENTILE"
    if points > 0:
        return "ML_ANOMALY_CONTEXT"
    return "ML_ANOMALY_CONTEXT_ONLY"


def _ml_signal_label(points: int) -> str:
    if points >= 8:
        return "Atypicite ML calibree elevee"
    if points >= 4:
        return "Atypicite ML calibree a examiner"
    if points > 0:
        return "Contexte ML atypique"
    return "Contexte ML documente"


def build_ml_detail_rows(
    ml_signals: pd.DataFrame,
    base_scores: pd.DataFrame,
    score_run_id: str,
    config: dict[str, Any],
    created_at: datetime,
) -> pd.DataFrame:
    if ml_signals.empty or not config["ml"].get("enabled", True):
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    ml_max = int(config["ml"].get("max_points", 10))
    max_score = int(config.get("max_score", 100))
    base = base_scores[["claim_sk", "claim_business_id", "attention_score"]].copy()
    signals = ml_signals.copy()
    signals["ml_attention_points"] = pd.to_numeric(signals["ml_attention_points"], errors="coerce").fillna(0).clip(lower=0, upper=ml_max).astype(int)
    signals = signals.merge(base, on="claim_sk", how="inner", suffixes=("", "_base"))
    signals["remaining_points"] = (max_score - pd.to_numeric(signals["attention_score"], errors="coerce").fillna(0)).clip(lower=0)
    signals["points"] = signals[["ml_attention_points", "remaining_points"]].min(axis=1).astype(int)
    if not config["ml"].get("include_zero_point_context", False):
        signals = signals[signals["points"] > 0].copy()
    if signals.empty:
        return pd.DataFrame(columns=DETAIL_COLUMNS)

    values = signals.apply(lambda row: json.dumps({
        "score_ml": float(row["score_ml"]),
        "raw_anomaly_score": float(row["raw_anomaly_score"]),
        "top_variable_1": row.get("top_variable_1"),
        "top_variable_2": row.get("top_variable_2"),
        "top_variable_3": row.get("top_variable_3"),
    }, ensure_ascii=False, sort_keys=True), axis=1)

    details = pd.DataFrame({
        "claim_sk": signals["claim_sk"],
        "claim_business_id": signals.get("claim_business_id_base", signals.get("claim_business_id")),
        "score_run_id": score_run_id,
        "score_version": SCORE_VERSION,
        "signal_family": config["ml"].get("signal_family", "ML atypicite calibree"),
        "signal_code": signals["points"].map(_ml_signal_code),
        "signal_label": signals["points"].map(_ml_signal_label),
        "signal_value": values,
        "points": signals["points"].astype(int),
        "severity": signals["points"].map(lambda points: _severity(int(points))),
        "business_explanation": "Le dossier presente une atypicite statistique calibree par percentile dans la population du run. Ce signal complete les regles metier et reste soumis a verification humaine.",
        "profile_name": PROFILE_NAME,
        "created_at": created_at,
    })
    return details[DETAIL_COLUMNS].copy()


def compute_claim_attention_hybrid_ml_scores(
    base_scores: pd.DataFrame,
    base_details: pd.DataFrame,
    ml_signals: pd.DataFrame,
    config: dict[str, Any] | None = None,
    score_run_id: str | None = None,
    created_at: datetime | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    config = config or load_hybrid_ml_config()
    validate_hybrid_ml_config(config)
    score_run_id = score_run_id or f"{SCORE_VERSION}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    created_at = created_at or datetime.now(timezone.utc).replace(tzinfo=None)
    max_score = int(config.get("max_score", 100))

    scores = base_scores.copy()
    scores["score_version"] = SCORE_VERSION
    scores["score_run_id"] = score_run_id
    scores["profile_name"] = PROFILE_NAME
    scores["source_system"] = SOURCE_SYSTEM
    scores["created_at"] = created_at

    carried_details = base_details.copy()
    if not carried_details.empty:
        carried_details["score_version"] = SCORE_VERSION
        carried_details["score_run_id"] = score_run_id
        carried_details["created_at"] = created_at

    ml_details = build_ml_detail_rows(ml_signals, base_scores, score_run_id, config, created_at)
    details = pd.concat([carried_details[DETAIL_COLUMNS] if not carried_details.empty else pd.DataFrame(columns=DETAIL_COLUMNS), ml_details], ignore_index=True)
    details["points"] = pd.to_numeric(details["points"], errors="coerce").fillna(0).astype(int)

    positive_points = (
        details.loc[details["points"] > 0].groupby("claim_sk")["points"].sum().rename("attention_score").reset_index()
        if not details.empty else pd.DataFrame(columns=["claim_sk", "attention_score"])
    )
    scores = scores.drop(columns=["attention_score"], errors="ignore").merge(positive_points, on="claim_sk", how="left")
    scores["attention_score"] = pd.to_numeric(scores["attention_score"], errors="coerce").fillna(0).clip(lower=0, upper=max_score).astype(int)
    scores["attention_level"] = scores["attention_score"].map(attention_level)

    positive_details = details[details["points"] > 0].copy()
    if not positive_details.empty:
        positive_details = positive_details.sort_values(["claim_sk", "points", "signal_code"], ascending=[True, False, True])
        positive_details["reason_rank"] = positive_details.groupby("claim_sk").cumcount() + 1
        reasons = positive_details[positive_details["reason_rank"].le(3)].pivot(index="claim_sk", columns="reason_rank", values="signal_label")
        reasons = reasons.rename(columns={1: "main_reason_1", 2: "main_reason_2", 3: "main_reason_3"}).reset_index()
    else:
        reasons = pd.DataFrame(columns=["claim_sk", "main_reason_1", "main_reason_2", "main_reason_3"])
    scores = scores.drop(columns=["main_reason_1", "main_reason_2", "main_reason_3"], errors="ignore").merge(reasons, on="claim_sk", how="left")
    scores["main_reason_1"] = scores["main_reason_1"].fillna("Aucun signal prioritaire hybride ML")
    for col in ["main_reason_2", "main_reason_3"]:
        if col not in scores.columns:
            scores[col] = None
    scores = scores[SCORE_COLUMNS].copy()
    return scores, details[DETAIL_COLUMNS].copy()


def _write_hybrid_ml_reports(scores: pd.DataFrame, details: pd.DataFrame, score_run_id: str, config: dict[str, Any]) -> dict[str, Path]:
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
    path = REPORT_DIR / "hybrid_ml_score_load_summary.csv"
    summary.to_csv(path, index=False)
    paths["load_summary"] = path

    for filename, df in {
        "hybrid_ml_score_distribution.csv": scores["attention_level"].value_counts(dropna=False).rename_axis("attention_level").reset_index(name="rows") if not scores.empty else pd.DataFrame(columns=["attention_level", "rows"]),
        "hybrid_ml_confidence_distribution.csv": scores["confidence_level"].value_counts(dropna=False).rename_axis("confidence_level").reset_index(name="rows") if not scores.empty else pd.DataFrame(columns=["confidence_level", "rows"]),
        "hybrid_ml_signal_family_summary.csv": details.groupby("signal_family", dropna=False).agg(signal_rows=("signal_code", "size"), total_points=("points", "sum")).reset_index() if not details.empty else pd.DataFrame(columns=["signal_family", "signal_rows", "total_points"]),
    }.items():
        path = REPORT_DIR / filename
        df.to_csv(path, index=False)
        paths[filename] = path

    config_path = REPORT_DIR / "hybrid_ml_score_config_snapshot.json"
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    paths["config_snapshot"] = config_path

    validation_csv = REPORT_DIR / "hybrid_ml_score_validation_summary.csv"
    pd.DataFrame([validation]).to_csv(validation_csv, index=False)
    paths["validation_csv"] = validation_csv

    validation_md = REPORT_DIR / "hybrid_ml_score_validation_summary.md"
    lines = [
        "# Claim Attention Hybrid ML V1 candidate validation",
        "",
        f"- **Run ID:** `{score_run_id}`",
        f"- **Score version:** `{SCORE_VERSION}`",
        f"- **Score rows:** {len(scores)}",
        f"- **Signal detail rows:** {len(details)}",
        "",
        "This score combines the base hybrid score with a calibrated ML anomaly signal. It remains a prioritization aid only.",
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


def _read_base_scores(engine, score_run_id: str) -> pd.DataFrame:
    query = text("""
        SELECT *
        FROM mart.fact_claim_attention_score
        WHERE score_version = :version
          AND score_run_id = :run_id
    """)
    with engine.connect() as conn:
        return pd.read_sql(query, conn, params={"version": BASE_HYBRID_SCORE_VERSION, "run_id": score_run_id})


def _read_base_details(engine, score_run_id: str) -> pd.DataFrame:
    query = text("""
        SELECT claim_sk, claim_business_id, score_run_id, score_version, signal_family,
               signal_code, signal_label, signal_value, points, severity,
               business_explanation, profile_name, created_at
        FROM mart.fact_claim_attention_signal_detail
        WHERE score_version = :version
          AND score_run_id = :run_id
    """)
    with engine.connect() as conn:
        return pd.read_sql(query, conn, params={"version": BASE_HYBRID_SCORE_VERSION, "run_id": score_run_id})


def _read_ml_signals(engine, signal_run_id: str) -> pd.DataFrame:
    query = text("""
        SELECT *
        FROM mart.fact_claim_ml_anomaly_signal
        WHERE signal_version = :version
          AND signal_run_id = :run_id
    """)
    with engine.connect() as conn:
        return pd.read_sql(query, conn, params={"version": ML_SIGNAL_VERSION, "run_id": signal_run_id})


def compute_claim_attention_hybrid_ml_score_v1_candidate(
    base_hybrid_score_run_id: str | None = None,
    ml_signal_run_id: str | None = None,
    config_path: Path | str = CONFIG_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if text is None:
        raise RuntimeError("SQLAlchemy is required to write hybrid ML score tables.")

    dwh_utils = _load_dwh_utils()
    config = load_hybrid_ml_config(config_path)
    today = datetime.now(timezone.utc).replace(tzinfo=None)
    score_run_id = f"{SCORE_VERSION}_{today.strftime('%Y%m%d_%H%M%S')}"
    logger = dwh_utils.setup_logging(score_run_id, log_name="compute_claim_attention_hybrid_ml_score_v1_candidate")
    logger.info("=" * 70)
    logger.info(f"[RUN] {score_run_id}")
    logger.info(f"      profile={PROFILE_NAME} version={SCORE_VERSION}")
    logger.info("      hybrid + calibrated ML prioritization score only; no automatic decision")
    logger.info("=" * 70)

    engine = dwh_utils.build_engine(logger)
    with engine.begin() as conn:
        conn.execute(text(DDL_CREATE_SCHEMA))
        conn.execute(text(DDL_FACT_CLAIM_ATTENTION_SCORE))
        conn.execute(text(DDL_FACT_CLAIM_ATTENTION_SIGNAL_DETAIL))

    base_hybrid_score_run_id = base_hybrid_score_run_id or _latest_run_id(
        engine, "mart.fact_claim_attention_score", "score_run_id", "score_version", BASE_HYBRID_SCORE_VERSION
    )
    ml_signal_run_id = ml_signal_run_id or _latest_run_id(
        engine, "mart.fact_claim_ml_anomaly_signal", "signal_run_id", "signal_version", ML_SIGNAL_VERSION
    )
    if base_hybrid_score_run_id is None:
        raise RuntimeError("No base hybrid score run found.")
    if ml_signal_run_id is None:
        raise RuntimeError("No ML anomaly signal run found.")

    base_scores = _read_base_scores(engine, base_hybrid_score_run_id)
    base_details = _read_base_details(engine, base_hybrid_score_run_id)
    ml_signals = _read_ml_signals(engine, ml_signal_run_id)
    logger.info(f"base hybrid scores loaded : {len(base_scores)}")
    logger.info(f"base hybrid details loaded: {len(base_details)}")
    logger.info(f"ML signals loaded         : {len(ml_signals)}")

    scores, details = compute_claim_attention_hybrid_ml_scores(
        base_scores,
        base_details,
        ml_signals,
        config=config,
        score_run_id=score_run_id,
        created_at=today,
    )
    validation = validate_hybrid_outputs(scores, details)
    logger.info(f"hybrid ML score rows: {len(scores)}")
    logger.info(f"hybrid ML detail rows: {len(details)}")
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
        raise RuntimeError(f"Hybrid ML score validation failed: {failed_checks}")

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

    report_paths = _write_hybrid_ml_reports(scores, details, score_run_id, config)
    for name, path in report_paths.items():
        logger.info(f"report {name}: {path}")

    print("=" * 70)
    print(f"  score_run_id              : {score_run_id}")
    print(f"  base_hybrid_score_run_id  : {base_hybrid_score_run_id}")
    print(f"  ml_signal_run_id          : {ml_signal_run_id}")
    print(f"  scored claims             : {len(scores)}")
    print(f"  signal detail rows        : {len(details)}")
    print(f"  validation                : {validation}")
    print(f"  report folder             : {REPORT_DIR}")
    print("=" * 70)
    return scores, details


if __name__ == "__main__":
    compute_claim_attention_hybrid_ml_score_v1_candidate()
