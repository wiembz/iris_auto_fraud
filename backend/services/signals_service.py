"""Read-only signal query service for the IRIS frontend API."""
from __future__ import annotations

from sqlalchemy import text

from backend.config import ApiConfig
from backend.services.query_helpers import (
    latest_ml_signal_run_sql,
    latest_post_inspection_run_sql,
    latest_score_run_sql,
    scalar_or_none,
)
from backend.services.serialization import row_to_dict, rows_to_dicts


def get_claim_signals(engine, config: ApiConfig, claim_sk: int, score_version: str | None = None) -> dict:
    selected_version = score_version or config.default_score_version
    with engine.connect() as conn:
        score_run_id = scalar_or_none(
            conn,
            latest_score_run_sql(),
            {"score_version": selected_version},
        )
        if not score_run_id:
            return {"score_version": selected_version, "score_run_id": None, "items": []}
        rows = conn.execute(
            text(
                """
                SELECT
                    claim_sk,
                    claim_business_id,
                    signal_family,
                    signal_code,
                    signal_label,
                    signal_value,
                    points,
                    severity,
                    business_explanation,
                    score_version,
                    score_run_id,
                    created_at
                FROM mart.fact_claim_attention_signal_detail
                WHERE claim_sk = :claim_sk
                  AND score_version = :score_version
                  AND score_run_id = :score_run_id
                ORDER BY points DESC, signal_family, signal_code
                """
            ),
            {
                "claim_sk": claim_sk,
                "score_version": selected_version,
                "score_run_id": score_run_id,
            },
        ).fetchall()
    return {
        "score_version": selected_version,
        "score_run_id": score_run_id,
        "items": rows_to_dicts(rows),
    }


def get_ml_anomaly(engine, config: ApiConfig, claim_sk: int) -> dict | None:
    with engine.connect() as conn:
        signal_run_id = scalar_or_none(
            conn,
            latest_ml_signal_run_sql(),
            {"signal_version": config.ml_signal_version},
        )
        if not signal_run_id:
            return None
        row = conn.execute(
            text(
                """
                SELECT
                    claim_sk,
                    claim_business_id,
                    signal_version,
                    signal_run_id,
                    raw_anomaly_score,
                    anomaly_percentile_score,
                    score_ml,
                    ml_attention_points,
                    ml_attention_level,
                    top_variable_1,
                    top_variable_2,
                    top_variable_3,
                    created_at
                FROM mart.fact_claim_ml_anomaly_signal
                WHERE claim_sk = :claim_sk
                  AND signal_version = :signal_version
                  AND signal_run_id = :signal_run_id
                LIMIT 1
                """
            ),
            {
                "claim_sk": claim_sk,
                "signal_version": config.ml_signal_version,
                "signal_run_id": signal_run_id,
            },
        ).first()
    return row_to_dict(row) if row else None


def get_post_inspection(engine, config: ApiConfig, claim_sk: int) -> dict:
    with engine.connect() as conn:
        signal_run_id = scalar_or_none(
            conn,
            latest_post_inspection_run_sql(),
            {"signal_version": config.post_inspection_signal_version},
        )
        if not signal_run_id:
            return {
                "signal_version": config.post_inspection_signal_version,
                "signal_run_id": None,
                "items": [],
            }
        rows = conn.execute(
            text(
                """
                SELECT
                    signal_run_id,
                    signal_version,
                    scenario_code,
                    scenario_label,
                    inspection_sk,
                    claim_sk,
                    contract_sk,
                    client_sk,
                    vehicule_sk,
                    immatriculation,
                    inspection_date,
                    claim_date,
                    days_inspection_to_claim,
                    delay_bucket,
                    defective_zone,
                    defective_checkpoint_count,
                    critical_checkpoint_count,
                    representative_checkpoint_labels,
                    claim_area,
                    claim_guarantee_code,
                    claim_guarantee_label,
                    zone_match_status,
                    linkage_method,
                    attention_level,
                    confidence_level,
                    business_explanation,
                    created_at
                FROM mart.fact_post_inspection_attention_signal
                WHERE claim_sk = :claim_sk
                  AND signal_version = :signal_version
                  AND signal_run_id = :signal_run_id
                ORDER BY days_inspection_to_claim, defective_zone
                """
            ),
            {
                "claim_sk": claim_sk,
                "signal_version": config.post_inspection_signal_version,
                "signal_run_id": signal_run_id,
            },
        ).fetchall()
    return {
        "signal_version": config.post_inspection_signal_version,
        "signal_run_id": signal_run_id,
        "items": rows_to_dicts(rows),
    }
