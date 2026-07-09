"""
etl/mart/compute_claim_ml_anomaly_signal_v1_candidate.py
=========================================================
Builds a calibrated unsupervised ML anomaly signal for claim prioritization.

This module trains an Isolation Forest candidate on validated claim scoring
features, calibrates raw anomaly scores into population percentiles, and stores
explainable ML context for human review. It does not prove fraud, does not make
an automatic decision, does not modify VHS, and does not modify Claim Attention
Score V1.

Sources:
  mart.fact_claim_scoring_features
  mart.fact_post_inspection_attention_signal, optional Scenario A context

Output:
  mart.fact_claim_ml_anomaly_signal
  data/quality_reports/scoring/claim_ml_anomaly_v1/
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

try:
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
except ModuleNotFoundError:  # Allows config and helper tests to fail clearly.
    IsolationForest = None
    StandardScaler = None

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dwh"))

from etl.mart.compute_claim_business_rule_signals_v1_candidate import enrich_features_for_business_rules
from etl.mart.compute_claim_scoring_features_v1 import FEATURE_VERSION
from etl.mart.compute_post_inspection_attention_signal_v1_candidate import SIGNAL_VERSION as POST_INSPECTION_SIGNAL_VERSION


def _load_dwh_utils():
    import dwh_utils
    return dwh_utils


CONFIG_PATH = BASE_DIR / "config" / "scoring" / "claim_attention_ml_anomaly_v1_candidate.json"
REPORT_DIR = BASE_DIR / "data" / "quality_reports" / "scoring" / "claim_ml_anomaly_v1"

SIGNAL_VERSION = "IRIS_CLAIM_ML_ANOMALY_SIGNAL_V1_CANDIDATE"
PROFILE_NAME = "CLAIM_ML_ANOMALY_SIGNAL_V1_CANDIDATE"
SOURCE_SYSTEM = "IRIS_CLAIM_ML_ANOMALY"
SCENARIO_A_CODE = "A_INSPECTION_TO_CLAIM"

NON_ACCUSATORY_BLOCKLIST = (
    "fraud detected",
    "fraudulent",
    "proof of fraud",
    "fraude detectee",
    "fraude confirmee",
    "client fraudeur",
    "fraudeur",
)

DDL_CREATE_SCHEMA = "CREATE SCHEMA IF NOT EXISTS mart;"

DDL_FACT_CLAIM_ML_ANOMALY_SIGNAL = """
CREATE TABLE IF NOT EXISTS mart.fact_claim_ml_anomaly_signal (
    ml_anomaly_signal_sk      BIGSERIAL PRIMARY KEY,
    signal_run_id             TEXT NOT NULL,
    signal_version            TEXT NOT NULL,
    source_feature_run_id     TEXT,
    claim_sk                  BIGINT NOT NULL,
    claim_business_id         TEXT,
    raw_anomaly_score         NUMERIC(18,8) NOT NULL,
    anomaly_percentile_score  NUMERIC(10,8) NOT NULL,
    score_ml                  NUMERIC(10,8) NOT NULL,
    ml_attention_points       INTEGER NOT NULL,
    ml_attention_level        TEXT NOT NULL,
    top_variable_1            TEXT,
    top_variable_2            TEXT,
    top_variable_3            TEXT,
    feature_value_json        TEXT NOT NULL,
    feature_percentile_json   TEXT NOT NULL,
    feature_list_json         TEXT NOT NULL,
    model_params_json         TEXT NOT NULL,
    imputation_json           TEXT NOT NULL,
    profile_name              TEXT NOT NULL,
    source_system             TEXT DEFAULT 'IRIS_CLAIM_ML_ANOMALY',
    created_at                TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_claim_ml_anomaly_signal_run UNIQUE
        (signal_run_id, signal_version, claim_sk)
);
"""

ML_SIGNAL_COLUMNS = [
    "signal_run_id",
    "signal_version",
    "source_feature_run_id",
    "claim_sk",
    "claim_business_id",
    "raw_anomaly_score",
    "anomaly_percentile_score",
    "score_ml",
    "ml_attention_points",
    "ml_attention_level",
    "top_variable_1",
    "top_variable_2",
    "top_variable_3",
    "feature_value_json",
    "feature_percentile_json",
    "feature_list_json",
    "model_params_json",
    "imputation_json",
    "profile_name",
    "source_system",
    "created_at",
]


def _text(value: Any) -> str | None:
    try:
        if value is None or pd.isna(value):
            return None
    except TypeError:
        pass
    text_value = str(value).strip()
    return text_value or None


def _json_payload(payload: dict[str, Any] | list[Any]) -> str:
    def clean(value: Any) -> Any:
        if isinstance(value, (np.integer, np.floating)):
            value = value.item()
        if isinstance(value, float) and np.isnan(value):
            return None
        if isinstance(value, dict):
            return {str(k): clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value
    return json.dumps(clean(payload), ensure_ascii=False, sort_keys=True)


def contains_accusatory_wording(text_value: object) -> bool:
    lowered = str(text_value or "").lower()
    return any(term in lowered for term in NON_ACCUSATORY_BLOCKLIST)


def load_ml_config(path: Path | str = CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    validate_ml_config(config)
    return config


def validate_ml_config(config: dict[str, Any]) -> None:
    required = ["signal_version", "profile_name", "model", "features", "preprocessing", "calibration", "points"]
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"Missing ML anomaly config keys: {missing}")
    if config["signal_version"] != SIGNAL_VERSION:
        raise ValueError(f"Config signal_version must be {SIGNAL_VERSION}")
    if config["model"].get("type") != "IsolationForest":
        raise ValueError("Only IsolationForest is enabled for this candidate module.")
    features = config.get("features", [])
    if not isinstance(features, list) or not features:
        raise ValueError("Config features must be a non-empty list.")
    point_config = config["points"]
    max_points = int(point_config.get("max_points", 0))
    if max_points < 0:
        raise ValueError("ML max_points must be non-negative.")
    thresholds = [
        float(point_config.get("low_percentile", 0)),
        float(point_config.get("medium_percentile", 0)),
        float(point_config.get("high_percentile", 0)),
    ]
    if thresholds != sorted(thresholds) or thresholds[0] < 0 or thresholds[-1] > 1:
        raise ValueError("ML percentile thresholds must be ordered between 0 and 1.")


def _add_post_inspection_context(features: pd.DataFrame, post_inspection: pd.DataFrame | None) -> pd.DataFrame:
    out = features.copy()
    out["post_inspection_signal_flag"] = 0
    out["post_inspection_signal_count"] = 0
    if post_inspection is None or post_inspection.empty or "claim_sk" not in post_inspection.columns:
        return out

    signals = post_inspection.copy()
    if "scenario_code" in signals.columns:
        signals = signals[signals["scenario_code"].eq(SCENARIO_A_CODE)].copy()
    if signals.empty:
        return out

    counts = signals.groupby("claim_sk").size().rename("post_inspection_signal_count").reset_index()
    out = out.merge(counts, on="claim_sk", how="left", suffixes=("", "_from_signal"))
    if "post_inspection_signal_count_from_signal" in out.columns:
        out["post_inspection_signal_count"] = out["post_inspection_signal_count_from_signal"].fillna(0).astype(int)
        out = out.drop(columns=["post_inspection_signal_count_from_signal"])
    else:
        out["post_inspection_signal_count"] = out["post_inspection_signal_count"].fillna(0).astype(int)
    out["post_inspection_signal_flag"] = out["post_inspection_signal_count"].gt(0).astype(int)
    return out


def _clip_numeric_frame(frame: pd.DataFrame, quantiles: list[float]) -> pd.DataFrame:
    if len(quantiles) != 2:
        return frame
    low_q, high_q = float(quantiles[0]), float(quantiles[1])
    clipped = frame.copy()
    for column in clipped.columns:
        values = clipped[column].dropna()
        if values.empty:
            continue
        low = values.quantile(low_q)
        high = values.quantile(high_q)
        clipped[column] = clipped[column].clip(lower=low, upper=high)
    return clipped


def prepare_ml_feature_matrix(
    features: pd.DataFrame,
    post_inspection: pd.DataFrame | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float]]:
    config = config or load_ml_config()
    feature_names = list(config["features"])

    enriched = enrich_features_for_business_rules(features)
    enriched = _add_post_inspection_context(enriched, post_inspection)
    for feature_name in feature_names:
        if feature_name not in enriched.columns:
            enriched[feature_name] = np.nan

    numeric = enriched[feature_names].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    numeric = _clip_numeric_frame(numeric, config.get("preprocessing", {}).get("clip_quantiles", []))
    imputation_values: dict[str, float] = {}
    for column in feature_names:
        median = numeric[column].median(skipna=True)
        if pd.isna(median):
            median = 0.0
        imputation_values[column] = float(median)
        numeric[column] = numeric[column].fillna(float(median))

    return enriched, numeric.astype(float), imputation_values


def percentile_scores(raw_scores: pd.Series | np.ndarray) -> pd.Series:
    scores = pd.Series(raw_scores, dtype="float64")
    if scores.empty:
        return scores
    return scores.rank(method="average", pct=True).clip(lower=0, upper=1)


def _attention_points(score_ml: float, config: dict[str, Any]) -> int:
    point_config = config["points"]
    if score_ml >= float(point_config["high_percentile"]):
        return min(int(point_config["high_points"]), int(point_config["max_points"]))
    if score_ml >= float(point_config["medium_percentile"]):
        return min(int(point_config["medium_points"]), int(point_config["max_points"]))
    if score_ml >= float(point_config["low_percentile"]):
        return min(int(point_config["low_points"]), int(point_config["max_points"]))
    return 0


def _ml_attention_level(points: int, score_ml: float) -> str:
    if points >= 10:
        return "Atypicite ML elevee a examiner"
    if points >= 7:
        return "Atypicite ML moderee a examiner"
    if points > 0:
        return "Contexte ML a verifier"
    return "Contexte ML documente"


def _feature_percentiles(matrix: pd.DataFrame) -> pd.DataFrame:
    return matrix.rank(method="average", pct=True).clip(lower=0, upper=1)


def _top_variable_labels(row_values: pd.Series, row_percentiles: pd.Series, limit: int = 3) -> list[str]:
    atypicality = (row_percentiles - 0.5).abs().sort_values(ascending=False)
    labels: list[str] = []
    for feature_name in atypicality.index[:limit]:
        labels.append(
            f"{feature_name}: value={row_values[feature_name]:.4f}, percentile={row_percentiles[feature_name]:.4f}"
        )
    return labels


def compute_ml_anomaly_signals(
    features: pd.DataFrame,
    post_inspection: pd.DataFrame | None = None,
    config: dict[str, Any] | None = None,
    signal_run_id: str | None = None,
    created_at: datetime | None = None,
) -> pd.DataFrame:
    if IsolationForest is None or StandardScaler is None:
        raise RuntimeError("scikit-learn is required for Isolation Forest ML anomaly scoring.")
    config = config or load_ml_config()
    validate_ml_config(config)
    signal_run_id = signal_run_id or f"{SIGNAL_VERSION}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    created_at = created_at or datetime.now(timezone.utc).replace(tzinfo=None)

    if features.empty:
        return pd.DataFrame(columns=ML_SIGNAL_COLUMNS)

    enriched, matrix, imputation_values = prepare_ml_feature_matrix(features, post_inspection, config)
    scaler = StandardScaler()
    scaled = scaler.fit_transform(matrix)
    model_config = config["model"]
    model = IsolationForest(
        n_estimators=int(model_config.get("n_estimators", 200)),
        contamination=model_config.get("contamination", "auto"),
        max_samples=model_config.get("max_samples", "auto"),
        random_state=int(model_config.get("random_state", 42)),
        n_jobs=int(model_config.get("n_jobs", -1)),
    )
    model.fit(scaled)
    raw_scores = pd.Series(-model.score_samples(scaled), index=matrix.index, dtype="float64")
    score_ml = percentile_scores(raw_scores)
    feature_percentiles = _feature_percentiles(matrix)
    feature_list_json = _json_payload(list(matrix.columns))
    model_params_json = _json_payload(model_config)
    imputation_json = _json_payload(imputation_values)

    top_count = int(config.get("explanation", {}).get("top_variable_count", 3))
    top_count = max(1, min(top_count, len(matrix.columns)))
    atypicality = (feature_percentiles.to_numpy(dtype="float64") - 0.5)
    atypicality = np.abs(atypicality)
    top_indices = np.argpartition(-atypicality, kth=top_count - 1, axis=1)[:, :top_count]
    ordered_top_indices = []
    for row_number, candidate_indices in enumerate(top_indices):
        ordered = candidate_indices[np.argsort(-atypicality[row_number, candidate_indices])]
        ordered_top_indices.append(ordered)

    feature_names = np.array(matrix.columns)
    value_array = matrix.to_numpy(dtype="float64")
    percentile_array = feature_percentiles.to_numpy(dtype="float64")
    top_labels: list[list[str]] = []
    top_value_json: list[str] = []
    top_percentile_json: list[str] = []
    for row_number, ordered in enumerate(ordered_top_indices):
        labels: list[str] = []
        value_payload: dict[str, float] = {}
        percentile_payload: dict[str, float] = {}
        for column_index in ordered:
            feature_name = str(feature_names[column_index])
            value = float(value_array[row_number, column_index])
            percentile = float(percentile_array[row_number, column_index])
            labels.append(f"{feature_name}: value={value:.4f}, percentile={percentile:.4f}")
            value_payload[feature_name] = round(value, 6)
            percentile_payload[feature_name] = round(percentile, 6)
        top_labels.append(labels)
        top_value_json.append(_json_payload(value_payload))
        top_percentile_json.append(_json_payload(percentile_payload))

    points = score_ml.map(lambda value: _attention_points(float(value), config)).astype(int)
    signals = pd.DataFrame({
        "signal_run_id": signal_run_id,
        "signal_version": SIGNAL_VERSION,
        "source_feature_run_id": enriched.get("feature_run_id"),
        "claim_sk": enriched.get("claim_sk"),
        "claim_business_id": enriched.get("claim_business_id"),
        "raw_anomaly_score": raw_scores.to_numpy(dtype="float64"),
        "anomaly_percentile_score": score_ml.to_numpy(dtype="float64"),
        "score_ml": score_ml.to_numpy(dtype="float64"),
        "ml_attention_points": points.to_numpy(dtype="int64"),
        "ml_attention_level": [_ml_attention_level(int(point), float(score)) for point, score in zip(points, score_ml)],
        "top_variable_1": [labels[0] if len(labels) > 0 else None for labels in top_labels],
        "top_variable_2": [labels[1] if len(labels) > 1 else None for labels in top_labels],
        "top_variable_3": [labels[2] if len(labels) > 2 else None for labels in top_labels],
        "feature_value_json": top_value_json,
        "feature_percentile_json": top_percentile_json,
        "feature_list_json": feature_list_json,
        "model_params_json": model_params_json,
        "imputation_json": imputation_json,
        "profile_name": PROFILE_NAME,
        "source_system": SOURCE_SYSTEM,
        "created_at": created_at,
    }, columns=ML_SIGNAL_COLUMNS)
    signals["claim_sk"] = pd.to_numeric(signals["claim_sk"], errors="coerce").astype("Int64")
    signals["ml_attention_points"] = pd.to_numeric(signals["ml_attention_points"], errors="coerce").fillna(0).astype(int)
    return signals


def validate_ml_anomaly_signals(signals: pd.DataFrame) -> dict[str, int]:
    if signals.empty:
        return {
            "signal_rows": 0,
            "duplicate_grain_rows": 0,
            "null_required_rows": 0,
            "score_out_of_range_rows": 0,
            "negative_point_rows": 0,
            "null_feature_list_rows": 0,
            "accusatory_wording_rows": 0,
        }

    required = ["signal_run_id", "signal_version", "claim_sk", "raw_anomaly_score", "score_ml", "ml_attention_level"]
    text_to_check = pd.concat([
        signals.get("ml_attention_level", pd.Series(dtype="object")).fillna(""),
        signals.get("top_variable_1", pd.Series(dtype="object")).fillna(""),
        signals.get("top_variable_2", pd.Series(dtype="object")).fillna(""),
        signals.get("top_variable_3", pd.Series(dtype="object")).fillna(""),
    ], ignore_index=True)
    return {
        "signal_rows": int(len(signals)),
        "duplicate_grain_rows": int(signals.duplicated(["signal_run_id", "signal_version", "claim_sk"]).sum()),
        "null_required_rows": int(signals[required].isna().any(axis=1).sum()),
        "score_out_of_range_rows": int((~pd.to_numeric(signals["score_ml"], errors="coerce").between(0, 1)).sum()),
        "negative_point_rows": int((pd.to_numeric(signals["ml_attention_points"], errors="coerce").fillna(0) < 0).sum()),
        "null_feature_list_rows": int(signals["feature_list_json"].map(_text).isna().sum()),
        "accusatory_wording_rows": int(text_to_check.map(contains_accusatory_wording).sum()),
    }


def _write_ml_reports(signals: pd.DataFrame, signal_run_id: str, config: dict[str, Any]) -> dict[str, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    validation = validate_ml_anomaly_signals(signals)

    summary = pd.DataFrame([{
        "signal_run_id": signal_run_id,
        "signal_version": SIGNAL_VERSION,
        "signal_rows": len(signals),
        "distinct_claims": int(signals["claim_sk"].nunique()) if not signals.empty else 0,
        "positive_ml_point_rows": int((signals["ml_attention_points"] > 0).sum()) if not signals.empty else 0,
        "max_score_ml": float(signals["score_ml"].max()) if not signals.empty else 0,
        "config_path": str(CONFIG_PATH),
    }])
    path = REPORT_DIR / "ml_anomaly_load_summary.csv"
    summary.to_csv(path, index=False)
    paths["load_summary"] = path

    distribution = (
        signals["ml_attention_level"].value_counts(dropna=False).rename_axis("ml_attention_level").reset_index(name="rows")
        if not signals.empty else pd.DataFrame(columns=["ml_attention_level", "rows"])
    )
    path = REPORT_DIR / "ml_anomaly_attention_distribution.csv"
    distribution.to_csv(path, index=False)
    paths["attention_distribution"] = path

    score_distribution = pd.DataFrame({
        "bucket": ["0-0.90", "0.90-0.95", "0.95-0.98", "0.98-1.00"],
        "rows": [
            int((signals["score_ml"] < 0.90).sum()) if not signals.empty else 0,
            int(((signals["score_ml"] >= 0.90) & (signals["score_ml"] < 0.95)).sum()) if not signals.empty else 0,
            int(((signals["score_ml"] >= 0.95) & (signals["score_ml"] < 0.98)).sum()) if not signals.empty else 0,
            int((signals["score_ml"] >= 0.98).sum()) if not signals.empty else 0,
        ],
    })
    path = REPORT_DIR / "ml_anomaly_score_distribution.csv"
    score_distribution.to_csv(path, index=False)
    paths["score_distribution"] = path

    top_examples = (
        signals.sort_values("score_ml", ascending=False).head(100)[[
            "claim_sk", "claim_business_id", "score_ml", "ml_attention_points",
            "top_variable_1", "top_variable_2", "top_variable_3",
        ]]
        if not signals.empty else pd.DataFrame()
    )
    path = REPORT_DIR / "ml_anomaly_top_examples.csv"
    top_examples.to_csv(path, index=False)
    paths["top_examples"] = path

    config_path = REPORT_DIR / "ml_anomaly_config_snapshot.json"
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    paths["config_snapshot"] = config_path

    validation_path = REPORT_DIR / "ml_anomaly_validation_summary.csv"
    pd.DataFrame([validation]).to_csv(validation_path, index=False)
    paths["validation_csv"] = validation_path

    validation_md = REPORT_DIR / "ml_anomaly_validation_summary.md"
    lines = [
        "# Claim ML anomaly signal V1 candidate validation",
        "",
        f"- **Run ID:** `{signal_run_id}`",
        f"- **Signal version:** `{SIGNAL_VERSION}`",
        f"- **Signal rows:** {len(signals)}",
        "",
        "Isolation Forest scores are calibrated as population percentiles. The signal is a prioritization aid only.",
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


def _read_features(engine, feature_run_id: str) -> pd.DataFrame:
    query = text("""
        SELECT *
        FROM mart.fact_claim_scoring_features
        WHERE scoring_feature_version = :version
          AND feature_run_id = :run_id
    """)
    with engine.connect() as conn:
        return pd.read_sql(query, conn, params={"version": FEATURE_VERSION, "run_id": feature_run_id})


def _read_post_inspection(engine, signal_run_id: str | None) -> pd.DataFrame:
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


def _copy_signals_to_db(engine, signals: pd.DataFrame, chunksize: int = 100000) -> None:
    if signals.empty:
        return
    columns_sql = ", ".join(ML_SIGNAL_COLUMNS)
    copy_sql = f"""
        COPY mart.fact_claim_ml_anomaly_signal ({columns_sql})
        FROM STDIN WITH (FORMAT CSV, HEADER FALSE, DELIMITER E'\\t', NULL '\\N')
    """
    export = signals[ML_SIGNAL_COLUMNS].copy()
    export["created_at"] = pd.to_datetime(export["created_at"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")
    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cursor:
            for start in range(0, len(export), chunksize):
                chunk = export.iloc[start:start + chunksize]
                buffer = StringIO()
                chunk.to_csv(buffer, sep="\t", header=False, index=False, na_rep="\\N", lineterminator="\n")
                buffer.seek(0)
                cursor.copy_expert(copy_sql, buffer)
        raw_conn.commit()
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        raw_conn.close()


def compute_claim_ml_anomaly_signal_v1_candidate(
    feature_run_id: str | None = None,
    post_inspection_signal_run_id: str | None = None,
    config_path: Path | str = CONFIG_PATH,
) -> pd.DataFrame:
    if text is None:
        raise RuntimeError("SQLAlchemy is required to write mart.fact_claim_ml_anomaly_signal.")

    dwh_utils = _load_dwh_utils()
    config = load_ml_config(config_path)
    today = datetime.now(timezone.utc).replace(tzinfo=None)
    signal_run_id = f"{SIGNAL_VERSION}_{today.strftime('%Y%m%d_%H%M%S')}"
    logger = dwh_utils.setup_logging(signal_run_id, log_name="compute_claim_ml_anomaly_signal_v1_candidate")
    logger.info("=" * 70)
    logger.info(f"[RUN] {signal_run_id}")
    logger.info(f"      profile={PROFILE_NAME} version={SIGNAL_VERSION}")
    logger.info("      Isolation Forest calibrated anomaly signal only; no automatic decision")
    logger.info("=" * 70)

    engine = dwh_utils.build_engine(logger)
    with engine.begin() as conn:
        conn.execute(text(DDL_CREATE_SCHEMA))
        conn.execute(text(DDL_FACT_CLAIM_ML_ANOMALY_SIGNAL))

    feature_run_id = feature_run_id or _latest_run_id(
        engine, "mart.fact_claim_scoring_features", "feature_run_id", "scoring_feature_version", FEATURE_VERSION
    )
    if feature_run_id is None:
        raise RuntimeError("No feature run found in mart.fact_claim_scoring_features.")
    post_inspection_signal_run_id = post_inspection_signal_run_id or _latest_run_id(
        engine, "mart.fact_post_inspection_attention_signal", "signal_run_id", "signal_version", POST_INSPECTION_SIGNAL_VERSION
    )

    features = _read_features(engine, feature_run_id)
    post_inspection = _read_post_inspection(engine, post_inspection_signal_run_id)
    logger.info(f"features loaded              : {len(features)}")
    logger.info(f"post-inspection signals loaded: {len(post_inspection)}")

    signals = compute_ml_anomaly_signals(
        features,
        post_inspection,
        config=config,
        signal_run_id=signal_run_id,
        created_at=today,
    )
    validation = validate_ml_anomaly_signals(signals)
    logger.info(f"ML anomaly signal rows: {len(signals)}")
    logger.info(f"validation: {validation}")

    blocking_checks = [
        "duplicate_grain_rows",
        "null_required_rows",
        "score_out_of_range_rows",
        "negative_point_rows",
        "null_feature_list_rows",
        "accusatory_wording_rows",
    ]
    failed_checks = {key: validation[key] for key in blocking_checks if validation.get(key, 0) > 0}
    if failed_checks:
        raise RuntimeError(f"ML anomaly signal validation failed: {failed_checks}")

    with engine.begin() as conn:
        conn.execute(text("""
            DELETE FROM mart.fact_claim_ml_anomaly_signal
            WHERE signal_version = :version
              AND signal_run_id = :run_id
        """), {"version": SIGNAL_VERSION, "run_id": signal_run_id})
    _copy_signals_to_db(engine, signals)

    report_paths = _write_ml_reports(signals, signal_run_id, config)
    for name, path in report_paths.items():
        logger.info(f"report {name}: {path}")

    print("=" * 70)
    print(f"  signal_run_id                : {signal_run_id}")
    print(f"  feature_run_id               : {feature_run_id}")
    print(f"  post_inspection_signal_run_id: {post_inspection_signal_run_id}")
    print(f"  ML signal rows               : {len(signals)}")
    print(f"  positive ML point rows       : {int((signals['ml_attention_points'] > 0).sum()) if not signals.empty else 0}")
    print(f"  validation                   : {validation}")
    print(f"  report folder                : {REPORT_DIR}")
    print("=" * 70)
    return signals


if __name__ == "__main__":
    compute_claim_ml_anomaly_signal_v1_candidate()
