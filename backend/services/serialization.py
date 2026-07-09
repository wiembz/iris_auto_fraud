"""JSON serialization helpers for database rows."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any


def to_json_value(value: Any) -> Any:
    """Convert common SQLAlchemy/Pandas scalar values to JSON-safe values."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def row_to_dict(row) -> dict[str, Any]:
    """Convert a SQLAlchemy row mapping to a JSON-safe dict."""
    mapping = row._mapping if hasattr(row, "_mapping") else row
    return {key: to_json_value(value) for key, value in dict(mapping).items()}


def rows_to_dicts(rows) -> list[dict[str, Any]]:
    """Convert SQLAlchemy rows to JSON-safe dictionaries."""
    return [row_to_dict(row) for row in rows]
