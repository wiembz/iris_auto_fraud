"""
Pure GEO normalization helpers for staging preparation.

This module does not connect to PostgreSQL, does not read files, and does not
write files. It performs only technical normalization and never applies business
geographical corrections.
"""

from __future__ import annotations

import math
import re
from typing import Any


_NULL_TOKENS = {
    "",
    "N/A",
    "NA",
    "-",
    "--",
    ".",
    "NULL",
    "NONE",
}

_UNKNOWN_TOKENS = {
    "UNKNOWN",
    "INCONNU",
    "INCONNUE",
    "NON RENSEIGNE",
    "NON RENSEIGNÉ",
}


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)


def _collapse_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _to_clean_upper(value: Any) -> str | None:
    if value is None or _is_nan(value):
        return None

    text = _collapse_spaces(str(value))
    if not text:
        return None

    return text.upper()


def _is_null_token(text: str) -> bool:
    return text in _NULL_TOKENS


def _is_unknown_token(text: str) -> bool:
    return text in _UNKNOWN_TOKENS


def normalize_geo_text(value: Any) -> str | None:
    """Normalize a free-text GEO value without applying business mapping."""
    text = _to_clean_upper(value)
    if text is None:
        return None
    if _is_null_token(text):
        return None
    if _is_unknown_token(text):
        return "UNKNOWN"
    return text


def normalize_postal_code(value: Any) -> str | None:
    """Normalize a postal code as text without validating it against a reference."""
    text = _to_clean_upper(value)
    if text is None:
        return None
    if _is_null_token(text):
        return None
    if _is_unknown_token(text):
        return "UNKNOWN"

    compact = re.sub(r"\s+", "", text)
    float_match = re.fullmatch(r"(\d+)[\.,]0+", compact)
    if float_match:
        return float_match.group(1)

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    return compact


def normalize_numeric_code(value: Any) -> str | None:
    """Normalize a numeric business code such as iddelega without inventing it."""
    text = _to_clean_upper(value)
    if text is None:
        return None
    if _is_null_token(text):
        return None
    if _is_unknown_token(text):
        return "UNKNOWN"

    compact = re.sub(r"\s+", "", text)
    float_match = re.fullmatch(r"(\d+)[\.,]0+", compact)
    if float_match:
        return float_match.group(1)

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    if re.fullmatch(r"\d+", compact):
        return compact

    return compact


if __name__ == "__main__":
    examples = [
        None,
        "",
        " Tunis ",
        "Ben  Arous",
        "N/A",
        "INCONNU",
        "1000.0",
        1000.0,
    ]
    for value in examples:
        print(
            value,
            "=>",
            normalize_geo_text(value),
            normalize_postal_code(value),
            normalize_numeric_code(value),
        )
