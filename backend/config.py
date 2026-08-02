"""Configuration for the read-only IRIS frontend API."""
from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_SCORE_VERSION = "IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE"
DEFAULT_BASE_SCORE_VERSION = "IRIS_CLAIM_ATTENTION_HYBRID_V1_CANDIDATE"
DEFAULT_ML_SIGNAL_VERSION = "IRIS_CLAIM_ML_ANOMALY_SIGNAL_V1_CANDIDATE"
DEFAULT_POST_INSPECTION_SIGNAL_VERSION = "IRIS_POST_INSPECTION_SIGNAL_V1_CANDIDATE"


@dataclass(frozen=True)
class ApiConfig:
    """Runtime options for the Flask read-only API."""

    default_score_version: str = DEFAULT_SCORE_VERSION
    base_score_version: str = DEFAULT_BASE_SCORE_VERSION
    ml_signal_version: str = DEFAULT_ML_SIGNAL_VERSION
    post_inspection_signal_version: str = DEFAULT_POST_INSPECTION_SIGNAL_VERSION
    max_page_size: int = 200
    summary_cache_ttl_seconds: int = 60
    inspection_image_storage_dir: str = "data/inspection_images"
    inspection_image_max_bytes: int = 8 * 1024 * 1024


def load_config() -> ApiConfig:
    """Load API configuration from environment variables."""
    return ApiConfig(
        default_score_version=os.getenv("IRIS_API_SCORE_VERSION", DEFAULT_SCORE_VERSION),
        base_score_version=os.getenv("IRIS_API_BASE_SCORE_VERSION", DEFAULT_BASE_SCORE_VERSION),
        ml_signal_version=os.getenv("IRIS_API_ML_SIGNAL_VERSION", DEFAULT_ML_SIGNAL_VERSION),
        post_inspection_signal_version=os.getenv(
            "IRIS_API_POST_INSPECTION_SIGNAL_VERSION",
            DEFAULT_POST_INSPECTION_SIGNAL_VERSION,
        ),
        max_page_size=int(os.getenv("IRIS_API_MAX_PAGE_SIZE", "200")),
        summary_cache_ttl_seconds=int(os.getenv("IRIS_API_SUMMARY_CACHE_TTL_SECONDS", "60")),
        inspection_image_storage_dir=os.getenv(
            "IRIS_INSPECTION_IMAGE_STORAGE_DIR",
            "data/inspection_images",
        ),
        inspection_image_max_bytes=int(os.getenv("IRIS_INSPECTION_IMAGE_MAX_BYTES", str(8 * 1024 * 1024))),
    )
