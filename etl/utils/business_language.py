"""Centralized non-accusatory business language guardrails for IRIS."""
from __future__ import annotations

import re
import unicodedata

FORBIDDEN_BUSINESS_TERMS = (
    "fraude confirmee",
    "fraude confirmée",
    "preuve de fraude",
    "client fraudeur",
    "fraudeur",
    "coupable",
    "suspect confirme",
    "suspect confirmé",
    "probabilite de fraude",
    "probabilité de fraude",
    "prediction de fraude",
    "prédiction de fraude",
    "fraud detected",
    "proof of fraud",
)


def normalize_business_text(value: object) -> str:
    """Normalize case, accents and repeated spaces for wording checks."""
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"\s+", " ", text.casefold()).strip()
    return text


_NORMALIZED_FORBIDDEN_TERMS = tuple(normalize_business_text(term) for term in FORBIDDEN_BUSINESS_TERMS)


def contains_forbidden_business_wording(value: object) -> bool:
    normalized = normalize_business_text(value)
    return any(term in normalized for term in _NORMALIZED_FORBIDDEN_TERMS)


def assert_non_accusatory(value: object, *, context: str = "business text") -> None:
    if contains_forbidden_business_wording(value):
        raise ValueError(f"Forbidden accusatory wording detected in {context}")
