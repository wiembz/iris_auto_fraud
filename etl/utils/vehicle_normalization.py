"""
Shared vehicle immatriculation normalization for DWH linkage.

This module is deliberately conservative: it only normalizes obvious technical
format differences used for joins. It does not validate ownership, infer a
vehicle from weak evidence, or create any attention signal.
"""

from __future__ import annotations

import math
import re
from typing import Any


INVALID_IMMATRICULATION_TOKENS = frozenset(
    {
        "",
        "0",
        "00",
        "000",
        "0000",
        "00000",
        "000000",
        "TEST",
        "NULL",
        "NAN",
        "NONE",
        "UNKNOWN",
        "INCONNU",
        "INCONNUE",
        "NON RENSEIGNE",
        "NON RENSEIGNEE",
        "NON RENSEIGNÉ",
        "NON RENSEIGNÉE",
        "N/A",
        "NA",
        "#N/A",
        "ND",
        "NR",
        "NEANT",
        "NÉANT",
        "SANS",
        "RAS",
        "/",
        "-",
        "--",
        "---",
        ".",
        "..",
        "PIETON",
        "MOBYLETTE",
        "NON ASSURE",
        "NON ASSURÉ",
    }
)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return type(value).__name__ in {"NAType", "NaTType"}


def _raw_to_text(value: Any) -> str | None:
    if _is_missing(value):
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip().upper()
    if not text:
        return None
    numeric_float = re.fullmatch(r"(\d+)[\.,]0+", text)
    if numeric_float:
        return numeric_float.group(1)
    return text


def _compact(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value)


COMPACT_INVALID_IMMATRICULATION_TOKENS = frozenset(
    _compact(token) for token in INVALID_IMMATRICULATION_TOKENS
)


def normalize_immatriculation(value: Any) -> str | None:
    """
    Normalize a primary vehicle immatriculation for deterministic DWH joins.

    Applied rules:
    - trim and uppercase;
    - remove non-alphanumeric separators;
    - treat known technical/placeholder values as missing;
    - preserve existing STAFFIM RS/NT inversion behavior;
    - preserve existing cautious TU inversion behavior when the right side is
      clearly the longer registration component.

    Numeric-only values are preserved as normalized text. Claim-only vehicles
    without VIN or motorisation should still remain valid dimension members.
    """
    text = _raw_to_text(value)
    if text is None:
        return None

    if text in INVALID_IMMATRICULATION_TOKENS:
        return None

    compact = _compact(text)
    if (
        not compact
        or compact in COMPACT_INVALID_IMMATRICULATION_TOKENS
        or re.fullmatch(r"0+", compact)
    ):
        return None

    tu_match = re.fullmatch(r"(\d+)TU(\d+)", compact)
    if tu_match:
        left, right = tu_match.groups()
        if len(left) <= 3 and len(right) >= 4:
            return f"{right}TU{left}"
        return f"{left}TU{right}"

    rs_match = re.fullmatch(r"RS(\d+)", compact)
    if rs_match:
        return f"RS{rs_match.group(1)}"
    rs_inverted = re.fullmatch(r"(\d+)RS", compact)
    if rs_inverted:
        return f"RS{rs_inverted.group(1)}"

    nt_match = re.fullmatch(r"(\d+)NT", compact)
    if nt_match:
        return f"{nt_match.group(1)}NT"
    nt_inverted = re.fullmatch(r"NT(\d+)", compact)
    if nt_inverted:
        return f"{nt_inverted.group(1)}NT"

    return compact
