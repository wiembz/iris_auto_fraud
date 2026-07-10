"""Read-only portfolio summary service for the IRIS frontend API."""
from __future__ import annotations

from time import monotonic
from copy import deepcopy

from sqlalchemy import text

from backend.config import ApiConfig
from backend.services.query_helpers import latest_score_run_sql, scalar_or_none
from backend.services.serialization import rows_to_dicts

_SUMMARY_CACHE: dict[tuple[str, int], tuple[float, dict]] = {}


def clear_summary_cache() -> None:
    """Clear the in-memory summary cache, mainly for tests."""
    _SUMMARY_CACHE.clear()


def _cache_key(score_version: str, ttl_seconds: int) -> tuple[str, int]:
    return score_version, ttl_seconds


def _get_cached_summary(score_version: str, ttl_seconds: int) -> dict | None:
    if ttl_seconds <= 0:
        return None
    cached = _SUMMARY_CACHE.get(_cache_key(score_version, ttl_seconds))
    if not cached:
        return None
    cached_at, payload = cached
    if monotonic() - cached_at > ttl_seconds:
        _SUMMARY_CACHE.pop(_cache_key(score_version, ttl_seconds), None)
        return None
    result = deepcopy(payload)
    result["cache"] = {"hit": True, "ttl_seconds": ttl_seconds}
    return result


def _set_cached_summary(score_version: str, ttl_seconds: int, payload: dict) -> None:
    if ttl_seconds <= 0:
        return
    stored = deepcopy(payload)
    stored["cache"] = {"hit": False, "ttl_seconds": ttl_seconds}
    _SUMMARY_CACHE[_cache_key(score_version, ttl_seconds)] = (monotonic(), stored)


def get_summary(engine, config: ApiConfig, score_version: str | None = None) -> dict:
    selected_version = score_version or config.default_score_version
    cached = _get_cached_summary(selected_version, config.summary_cache_ttl_seconds)
    if cached is not None:
        return cached

    with engine.connect() as conn:
        score_run_id = scalar_or_none(
            conn,
            latest_score_run_sql(),
            {"score_version": selected_version},
        )
        if not score_run_id:
            empty = {
                "score_version": selected_version,
                "score_run_id": None,
                "total_claims": 0,
                "attention_distribution": [],
                "confidence_distribution": [],
                "top_claims": [],
                "cache": {"hit": False, "ttl_seconds": config.summary_cache_ttl_seconds},
            }
            _set_cached_summary(selected_version, config.summary_cache_ttl_seconds, empty)
            return empty

        total_claims = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM mart.fact_claim_attention_score
                WHERE score_version = :score_version
                  AND score_run_id = :score_run_id
                """
            ),
            {"score_version": selected_version, "score_run_id": score_run_id},
        ).scalar_one()

        attention_distribution = conn.execute(
            text(
                """
                SELECT attention_level, COUNT(*) AS claims
                FROM mart.fact_claim_attention_score
                WHERE score_version = :score_version
                  AND score_run_id = :score_run_id
                GROUP BY attention_level
                ORDER BY claims DESC
                """
            ),
            {"score_version": selected_version, "score_run_id": score_run_id},
        ).fetchall()

        confidence_distribution = conn.execute(
            text(
                """
                SELECT confidence_level, COUNT(*) AS claims
                FROM mart.fact_claim_attention_score
                WHERE score_version = :score_version
                  AND score_run_id = :score_run_id
                GROUP BY confidence_level
                ORDER BY claims DESC
                """
            ),
            {"score_version": selected_version, "score_run_id": score_run_id},
        ).fetchall()

        top_claims = conn.execute(
            text(
                """
                SELECT
                    claim_sk,
                    claim_business_id,
                    attention_score,
                    attention_level,
                    confidence_level,
                    main_reason_1
                FROM mart.fact_claim_attention_score
                WHERE score_version = :score_version
                  AND score_run_id = :score_run_id
                ORDER BY attention_score DESC, claim_sk
                LIMIT 20
                """
            ),
            {"score_version": selected_version, "score_run_id": score_run_id},
        ).fetchall()

    result = {
        "score_version": selected_version,
        "score_run_id": score_run_id,
        "total_claims": total_claims,
        "attention_distribution": rows_to_dicts(attention_distribution),
        "confidence_distribution": rows_to_dicts(confidence_distribution),
        "top_claims": rows_to_dicts(top_claims),
        "cache": {"hit": False, "ttl_seconds": config.summary_cache_ttl_seconds},
    }
    _set_cached_summary(selected_version, config.summary_cache_ttl_seconds, result)
    return result
