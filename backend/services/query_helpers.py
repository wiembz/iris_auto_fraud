"""Small query helpers shared by read-only services."""
from __future__ import annotations

from sqlalchemy import text


def latest_score_run_sql() -> str:
    return """
        SELECT score_run_id
        FROM mart.fact_claim_attention_score
        WHERE score_version = :score_version
        ORDER BY created_at DESC, score_run_id DESC
        LIMIT 1
    """


def latest_feature_run_sql() -> str:
    return """
        SELECT feature_run_id
        FROM mart.fact_claim_scoring_features
        ORDER BY created_at DESC, feature_run_id DESC
        LIMIT 1
    """


def latest_ml_signal_run_sql() -> str:
    return """
        SELECT signal_run_id
        FROM mart.fact_claim_ml_anomaly_signal
        WHERE signal_version = :signal_version
        ORDER BY created_at DESC, signal_run_id DESC
        LIMIT 1
    """


def latest_post_inspection_run_sql() -> str:
    return """
        SELECT signal_run_id
        FROM mart.fact_post_inspection_attention_signal
        WHERE signal_version = :signal_version
        ORDER BY created_at DESC, signal_run_id DESC
        LIMIT 1
    """


def scalar_or_none(conn, sql: str, params: dict | None = None):
    return conn.execute(text(sql), params or {}).scalar_one_or_none()
