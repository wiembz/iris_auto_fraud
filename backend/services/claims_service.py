"""Read-only claim query service for the IRIS frontend API."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from backend.config import ApiConfig
from backend.services.query_helpers import latest_score_run_sql, scalar_or_none
from backend.services.serialization import row_to_dict, rows_to_dicts


def _latest_score_run(conn, score_version: str) -> str | None:
    return scalar_or_none(conn, latest_score_run_sql(), {"score_version": score_version})


def list_claims(engine, config: ApiConfig, filters: dict[str, Any]) -> dict[str, Any]:
    """Return paginated claim scores for the latest selected score run."""
    score_version = filters.get("score_version") or config.default_score_version
    page = max(int(filters.get("page") or 1), 1)
    page_size = min(max(int(filters.get("page_size") or 50), 1), config.max_page_size)
    offset = (page - 1) * page_size

    where = ["s.score_version = :score_version", "s.score_run_id = :score_run_id"]
    params: dict[str, Any] = {
        "score_version": score_version,
        "page_size": page_size,
        "offset": offset,
    }

    if filters.get("attention_level"):
        where.append("s.attention_level = :attention_level")
        params["attention_level"] = filters["attention_level"]
    if filters.get("confidence_level"):
        where.append("s.confidence_level = :confidence_level")
        params["confidence_level"] = filters["confidence_level"]
    if filters.get("min_score") is not None:
        where.append("s.attention_score >= :min_score")
        params["min_score"] = int(filters["min_score"])
    if filters.get("max_score") is not None:
        where.append("s.attention_score <= :max_score")
        params["max_score"] = int(filters["max_score"])
    if filters.get("search"):
        where.append("s.claim_business_id ILIKE :search")
        params["search"] = f"%{filters['search']}%"
    if filters.get("has_ml") == "true":
        where.append("ml.claim_sk IS NOT NULL")
    if filters.get("has_post_inspection") == "true":
        where.append("pi.claim_sk IS NOT NULL")

    where_sql = " AND ".join(where)

    with engine.connect() as conn:
        score_run_id = _latest_score_run(conn, score_version)
        if not score_run_id:
            return {
                "score_version": score_version,
                "score_run_id": None,
                "page": page,
                "page_size": page_size,
                "total": 0,
                "items": [],
            }
        params["score_run_id"] = score_run_id

        count_sql = f"""
            SELECT COUNT(DISTINCT s.claim_sk) AS total
            FROM mart.fact_claim_attention_score s
            LEFT JOIN mart.fact_claim_ml_anomaly_signal ml
                ON ml.claim_sk = s.claim_sk
               AND ml.signal_version = :ml_signal_version
            LEFT JOIN mart.fact_post_inspection_attention_signal pi
                ON pi.claim_sk = s.claim_sk
               AND pi.signal_version = :post_inspection_signal_version
            WHERE {where_sql}
        """
        params["ml_signal_version"] = config.ml_signal_version
        params["post_inspection_signal_version"] = config.post_inspection_signal_version
        total = conn.execute(text(count_sql), params).scalar_one()

        query_sql = f"""
            SELECT
                s.claim_sk,
                s.claim_business_id,
                s.attention_score,
                s.attention_level,
                s.confidence_level,
                s.main_reason_1,
                s.main_reason_2,
                s.main_reason_3,
                s.score_version,
                s.score_run_id,
                s.created_at,
                CASE WHEN MAX(ml.claim_sk) IS NULL THEN FALSE ELSE TRUE END AS has_ml_signal,
                CASE WHEN MAX(pi.claim_sk) IS NULL THEN FALSE ELSE TRUE END AS has_post_inspection_signal
            FROM mart.fact_claim_attention_score s
            LEFT JOIN mart.fact_claim_ml_anomaly_signal ml
                ON ml.claim_sk = s.claim_sk
               AND ml.signal_version = :ml_signal_version
            LEFT JOIN mart.fact_post_inspection_attention_signal pi
                ON pi.claim_sk = s.claim_sk
               AND pi.signal_version = :post_inspection_signal_version
            WHERE {where_sql}
            GROUP BY
                s.claim_sk, s.claim_business_id, s.attention_score,
                s.attention_level, s.confidence_level,
                s.main_reason_1, s.main_reason_2, s.main_reason_3,
                s.score_version, s.score_run_id, s.created_at
            ORDER BY s.attention_score DESC, s.created_at DESC, s.claim_sk
            LIMIT :page_size OFFSET :offset
        """
        rows = conn.execute(text(query_sql), params).fetchall()

    return {
        "score_version": score_version,
        "score_run_id": score_run_id,
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": rows_to_dicts(rows),
    }


def get_claim(engine, config: ApiConfig, claim_sk: int, score_version: str | None = None) -> dict[str, Any] | None:
    """Return the latest score row and feature context for one claim."""
    selected_version = score_version or config.default_score_version
    with engine.connect() as conn:
        score_run_id = _latest_score_run(conn, selected_version)
        if not score_run_id:
            return None
        row = conn.execute(
            text(
                """
                SELECT
                    s.claim_sk,
                    s.claim_business_id,
                    s.attention_score,
                    s.attention_level,
                    s.confidence_level,
                    s.main_reason_1,
                    s.main_reason_2,
                    s.main_reason_3,
                    s.score_version,
                    s.score_run_id,
                    s.feature_run_id,
                    s.created_at,
                    f.numero_sinistre,
                    f.code_garantie,
                    f.client_sk,
                    f.contrat_sk,
                    f.vehicle_sk,
                    f.claim_date,
                    f.declaration_date,
                    f.contract_start_date,
                    f.claim_amount,
                    f.client_claim_count_12m,
                    f.client_claim_count_24m,
                    f.days_claim_to_declaration,
                    f.days_contract_start_to_claim,
                    f.missing_keys_count,
                    f.unknown_dimensions_count
                FROM mart.fact_claim_attention_score s
                LEFT JOIN mart.fact_claim_scoring_features f
                    ON f.claim_sk = s.claim_sk
                   AND f.feature_run_id = s.feature_run_id
                WHERE s.claim_sk = :claim_sk
                  AND s.score_version = :score_version
                  AND s.score_run_id = :score_run_id
                LIMIT 1
                """
            ),
            {
                "claim_sk": claim_sk,
                "score_version": selected_version,
                "score_run_id": score_run_id,
            },
        ).first()
    return row_to_dict(row) if row else None


def get_vehicle_context(engine, config: ApiConfig, claim_sk: int) -> dict[str, Any] | None:
    """Return vehicle-oriented context used by the claim detail page."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT
                    f.claim_sk,
                    f.claim_business_id,
                    f.vehicle_sk,
                    f.missing_vehicle_flag,
                    f.vehicle_recurrence_ready_flag,
                    MAX(pi.immatriculation) AS immatriculation,
                    COUNT(pi.post_inspection_signal_sk) AS post_inspection_signal_count
                FROM mart.fact_claim_scoring_features f
                LEFT JOIN mart.fact_post_inspection_attention_signal pi
                    ON pi.claim_sk = f.claim_sk
                   AND pi.signal_version = :post_inspection_signal_version
                WHERE f.claim_sk = :claim_sk
                GROUP BY
                    f.claim_sk,
                    f.claim_business_id,
                    f.vehicle_sk,
                    f.missing_vehicle_flag,
                    f.vehicle_recurrence_ready_flag
                ORDER BY f.created_at DESC
                LIMIT 1
                """
            ),
            {
                "claim_sk": claim_sk,
                "post_inspection_signal_version": config.post_inspection_signal_version,
            },
        ).first()
    return row_to_dict(row) if row else None

