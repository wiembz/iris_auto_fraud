"""Read-only claim query service for the IRIS frontend API."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from backend.config import ApiConfig
from backend.services.decision_service import ALLOWED_DECISIONS
from backend.services.query_helpers import (
    latest_ml_signal_run_sql,
    latest_post_inspection_run_sql,
    latest_score_run_sql,
    scalar_or_none,
)
from backend.services.serialization import row_to_dict, rows_to_dicts


def _latest_score_run(conn, score_version: str) -> str | None:
    return scalar_or_none(conn, latest_score_run_sql(), {"score_version": score_version})


def _latest_ml_run(conn, config: ApiConfig) -> str | None:
    return scalar_or_none(
        conn,
        latest_ml_signal_run_sql(),
        {"signal_version": config.ml_signal_version},
    )


def _latest_post_inspection_run(conn, config: ApiConfig) -> str | None:
    return scalar_or_none(
        conn,
        latest_post_inspection_run_sql(),
        {"signal_version": config.post_inspection_signal_version},
    )


def _bool_filter(value: Any) -> bool:
    return str(value).lower() == "true"


def _include_total(value: Any) -> bool:
    return str(value).lower() not in {"false", "0", "no"}


def _sort_clause(sort_by: Any, sort_direction: Any) -> str:
    allowed_columns = {
        "attention_score": "s.attention_score",
        "claim_sk": "s.claim_sk",
        "claim_root_id": "s.claim_business_id",
        "claim_date": "f.claim_date",
        "claim_amount": "f.claim_amount",
        "age_days": "f.claim_date",
    }
    column = allowed_columns.get(str(sort_by or "attention_score"), "s.attention_score")
    direction = "ASC" if str(sort_direction).lower() == "asc" else "DESC"
    if column == "f.claim_date" and str(sort_by) == "age_days":
        direction = "ASC" if direction == "DESC" else "DESC"
    return f"{column} {direction}, s.claim_sk ASC"


def _safe_int(value: Any, default: int, min_value: int, max_value: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    parsed = max(parsed, min_value)
    if max_value is not None:
        parsed = min(parsed, max_value)
    return parsed


def _signal_exists_sql(table_name: str, run_column: str) -> str:
    return f"""
        EXISTS (
            SELECT 1
            FROM {table_name} sig
            WHERE sig.claim_sk = s.claim_sk
              AND sig.signal_version = :{table_name.replace('.', '_')}_version
              AND sig.{run_column} = :{table_name.replace('.', '_')}_run_id
        )
    """


def list_claims(engine, config: ApiConfig, filters: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded page of claim scores for the latest selected run."""
    score_version = filters.get("score_version") or config.default_score_version
    page = _safe_int(filters.get("page"), default=1, min_value=1)
    page_size = _safe_int(
        filters.get("page_size"),
        default=50,
        min_value=1,
        max_value=config.max_page_size,
    )
    offset = (page - 1) * page_size
    include_total = _include_total(filters.get("include_total"))
    fetch_limit = page_size if include_total else page_size + 1
    order_by_sql = _sort_clause(filters.get("sort_by"), filters.get("sort_direction"))

    where = ["s.score_version = :score_version", "s.score_run_id = :score_run_id"]
    params: dict[str, Any] = {
        "score_version": score_version,
        "page_size": fetch_limit,
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
        params["min_score"] = _safe_int(filters["min_score"], 0, 0, 100)
    if filters.get("max_score") is not None:
        where.append("s.attention_score <= :max_score")
        params["max_score"] = _safe_int(filters["max_score"], 100, 0, 100)
    if filters.get("search"):
        where.append("s.claim_business_id ILIKE :search")
        params["search"] = f"%{filters['search']}%"

    validation_status = filters.get("validation_status")
    if validation_status == "NONE":
        where.append("d.decision IS NULL")
    elif validation_status in ALLOWED_DECISIONS:
        where.append("d.decision = :validation_status")
        params["validation_status"] = validation_status

    with engine.connect() as conn:
        score_run_id = _latest_score_run(conn, score_version)
        if not score_run_id:
            return {
                "score_version": score_version,
                "score_run_id": None,
                "page": page,
                "page_size": page_size,
                "max_page_size": config.max_page_size,
                "total": 0,
                "items": [],
            }
        params["score_run_id"] = score_run_id

        ml_run_id = _latest_ml_run(conn, config)
        post_inspection_run_id = _latest_post_inspection_run(conn, config)
        params["mart_fact_claim_ml_anomaly_signal_version"] = config.ml_signal_version
        params["mart_fact_claim_ml_anomaly_signal_run_id"] = ml_run_id or "__NO_ML_RUN__"
        params["mart_fact_post_inspection_attention_signal_version"] = config.post_inspection_signal_version
        params["mart_fact_post_inspection_attention_signal_run_id"] = post_inspection_run_id or "__NO_PI_RUN__"

        ml_exists_sql = _signal_exists_sql("mart.fact_claim_ml_anomaly_signal", "signal_run_id")
        post_inspection_exists_sql = _signal_exists_sql(
            "mart.fact_post_inspection_attention_signal",
            "signal_run_id",
        )

        if _bool_filter(filters.get("has_ml")):
            where.append(ml_exists_sql)
        if _bool_filter(filters.get("has_post_inspection")):
            where.append(post_inspection_exists_sql)

        where_sql = " AND ".join(where)

        total = None
        if include_total:
            count_sql = f"""
                SELECT COUNT(*) AS total
                FROM mart.fact_claim_attention_score s
                LEFT JOIN app.claim_review_decision_latest d ON d.claim_sk = s.claim_sk
                WHERE {where_sql}
            """
            total = conn.execute(text(count_sql), params).scalar_one()

        query_sql = f"""
            SELECT
                s.claim_sk,
                s.claim_business_id,
                f.numero_sinistre,
                f.client_sk,
                f.contrat_sk,
                f.code_garantie,
                f.claim_date,
                f.claim_amount,
                s.attention_score,
                s.attention_level,
                s.confidence_level,
                s.main_reason_1,
                s.main_reason_2,
                s.main_reason_3,
                s.score_version,
                s.score_run_id,
                s.created_at,
                {ml_exists_sql} AS has_ml_signal,
                {post_inspection_exists_sql} AS has_post_inspection_signal,
                d.decision AS validation_status,
                d.decided_at AS validation_decided_at,
                d.reviewer_email AS validation_reviewer_email
            FROM mart.fact_claim_attention_score s
            LEFT JOIN mart.fact_claim_scoring_features f
                ON f.claim_sk = s.claim_sk
               AND f.feature_run_id = s.feature_run_id
            LEFT JOIN app.claim_review_decision_latest d ON d.claim_sk = s.claim_sk
            WHERE {where_sql}
            ORDER BY {order_by_sql}
            LIMIT :page_size OFFSET :offset
        """
        rows = conn.execute(text(query_sql), params).fetchall()
        has_next = False
        if not include_total and len(rows) > page_size:
            has_next = True
            rows = rows[:page_size]

    return {
        "score_version": score_version,
        "score_run_id": score_run_id,
        "ml_signal_run_id": ml_run_id,
        "post_inspection_signal_run_id": post_inspection_run_id,
        "page": page,
        "page_size": page_size,
        "max_page_size": config.max_page_size,
        "total": total if total is not None else offset + len(rows) + (1 if has_next else 0),
        "has_next": has_next if not include_total else (offset + len(rows) < total),
        "total_is_exact": include_total,
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