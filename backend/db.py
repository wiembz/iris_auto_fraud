"""Database access helpers for the read-only IRIS frontend API."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import sys


BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from etl.utils.runtime import build_engine  # noqa: E402


@lru_cache(maxsize=1)
def get_engine():
    """Return a cached SQLAlchemy engine built from the project .env file."""
    return build_engine()
