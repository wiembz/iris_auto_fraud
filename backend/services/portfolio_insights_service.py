"""Portfolio-level strategic aggregates for the manager/responsable dashboard.

Read-only, mart-only. Kept separate from summary_service (used by every
dashboard) so these heavier GROUP BY queries only run for the audience that
actually needs them.
"""
from __future__ import annotations

from time import monotonic
from copy import deepcopy

from sqlalchemy import text

from backend.config import ApiConfig
from backend.services.query_helpers import latest_score_run_sql, scalar_or_none
from backend.services.serialization import rows_to_dicts

_INSIGHTS_CACHE: dict[tuple[str, int], tuple[float, dict]] = {}


def clear_portfolio_insights_cache() -> None:
    _INSIGHTS_CACHE.clear()


def _cached(score_version: str, ttl_seconds: int) -> dict | None:
    if ttl_seconds <= 0:
        return None
    cached = _INSIGHTS_CACHE.get((score_version, ttl_seconds))
    if not cached:
        return None
    cached_at, payload = cached
    if monotonic() - cached_at > ttl_seconds:
        _INSIGHTS_CACHE.pop((score_version, ttl_seconds), None)
        return None
    return deepcopy(payload)


def _set_cached(score_version: str, ttl_seconds: int, payload: dict) -> None:
    if ttl_seconds <= 0:
        return
    _INSIGHTS_CACHE[(score_version, ttl_seconds)] = (monotonic(), deepcopy(payload))


def get_portfolio_insights(engine, config: ApiConfig, score_version: str | None = None) -> dict:
    selected_version = score_version or config.default_score_version
    cached = _cached(selected_version, config.summary_cache_ttl_seconds)
    if cached is not None:
        cached["cache"] = {"hit": True}
        return cached

    with engine.connect() as conn:
        score_run_id = scalar_or_none(conn, latest_score_run_sql(), {"score_version": selected_version})
        if not score_run_id:
            empty = {
                "score_version": selected_version,
                "score_run_id": None,
                "financial_exposure": [],
                "guarantee_breakdown": [],
                "monthly_trend": [],
                "reason_distribution": [],
                "validation_coverage": None,
                "cache": {"hit": False},
            }
            _set_cached(selected_version, config.summary_cache_ttl_seconds, empty)
            return empty

        params = {"score_version": selected_version, "score_run_id": score_run_id}

        financial_exposure = conn.execute(
            text(
                """
                SELECT
                    s.attention_level,
                    COUNT(*) AS claims,
                    COALESCE(SUM(f.claim_amount), 0) AS total_amount,
                    COALESCE(AVG(f.claim_amount), 0) AS avg_amount
                FROM mart.fact_claim_attention_score s
                JOIN mart.fact_claim_scoring_features f
                    ON f.claim_sk = s.claim_sk AND f.feature_run_id = s.feature_run_id
                WHERE s.score_version = :score_version AND s.score_run_id = :score_run_id
                GROUP BY s.attention_level
                ORDER BY total_amount DESC
                """
            ),
            params,
        ).fetchall()

        guarantee_breakdown = conn.execute(
            text(
                """
                SELECT
                    f.code_garantie,
                    COUNT(*) AS claims,
                    COUNT(*) FILTER (WHERE s.attention_level ILIKE '%priorit%') AS priority_claims,
                    COALESCE(SUM(f.claim_amount), 0) AS total_amount
                FROM mart.fact_claim_attention_score s
                JOIN mart.fact_claim_scoring_features f
                    ON f.claim_sk = s.claim_sk AND f.feature_run_id = s.feature_run_id
                WHERE s.score_version = :score_version AND s.score_run_id = :score_run_id
                  AND f.code_garantie IS NOT NULL
                GROUP BY f.code_garantie
                ORDER BY priority_claims DESC, total_amount DESC
                LIMIT 8
                """
            ),
            params,
        ).fetchall()

        monthly_trend = conn.execute(
            text(
                """
                WITH bounds AS (
                    SELECT MAX(f.claim_date) AS max_date
                    FROM mart.fact_claim_attention_score s
                    JOIN mart.fact_claim_scoring_features f
                        ON f.claim_sk = s.claim_sk AND f.feature_run_id = s.feature_run_id
                    WHERE s.score_version = :score_version AND s.score_run_id = :score_run_id
                )
                SELECT
                    date_trunc('month', f.claim_date) AS month,
                    COUNT(*) AS claims,
                    COUNT(*) FILTER (WHERE s.attention_level ILIKE '%priorit%') AS priority_claims
                FROM mart.fact_claim_attention_score s
                JOIN mart.fact_claim_scoring_features f
                    ON f.claim_sk = s.claim_sk AND f.feature_run_id = s.feature_run_id
                CROSS JOIN bounds
                WHERE s.score_version = :score_version AND s.score_run_id = :score_run_id
                  AND f.claim_date >= date_trunc('month', bounds.max_date) - INTERVAL '11 months'
                GROUP BY 1
                ORDER BY 1
                """
            ),
            params,
        ).fetchall()

        reason_distribution = conn.execute(
            text(
                """
                SELECT main_reason_1 AS reason, COUNT(*) AS claims
                FROM mart.fact_claim_attention_score
                WHERE score_version = :score_version AND score_run_id = :score_run_id
                  AND main_reason_1 IS NOT NULL
                  -- Placeholder "pas de signal" sur les dossiers standard : pas une cause
                  -- exploitable, on ne veut que les raisons qui declenchent reellement l attention.
                  AND main_reason_1 <> 'Aucun signal prioritaire hybride ML'
                GROUP BY main_reason_1
                ORDER BY claims DESC
                LIMIT 8
                """
            ),
            params,
        ).fetchall()

        validation_row = conn.execute(
            text(
                """
                SELECT
                    COUNT(*) AS total_claims,
                    COUNT(d.decision) AS decided_claims,
                    COUNT(*) FILTER (WHERE d.decision = 'SUSPICION_CONFIRMED') AS suspicion_confirmed,
                    COUNT(*) FILTER (WHERE d.decision = 'CONFORME') AS conforme,
                    COUNT(*) FILTER (WHERE d.decision = 'A_COMPLETER') AS a_completer
                FROM mart.fact_claim_attention_score s
                LEFT JOIN app.claim_review_decision_latest d ON d.claim_sk = s.claim_sk
                WHERE s.score_version = :score_version AND s.score_run_id = :score_run_id
                """
            ),
            params,
        ).first()

    result = {
        "score_version": selected_version,
        "score_run_id": score_run_id,
        "financial_exposure": rows_to_dicts(financial_exposure),
        "guarantee_breakdown": rows_to_dicts(guarantee_breakdown),
        "monthly_trend": rows_to_dicts(monthly_trend),
        "reason_distribution": rows_to_dicts(reason_distribution),
        "validation_coverage": dict(validation_row._mapping) if validation_row else None,
        "cache": {"hit": False},
    }
    _set_cached(selected_version, config.summary_cache_ttl_seconds, result)
    return result
