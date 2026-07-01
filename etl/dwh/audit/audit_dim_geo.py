"""
etl/dwh/audit/audit_dim_geo.py
========================
Audit dwh.dim_geo against a Tunisian geographical reference file.

This script does not update dwh.dim_geo. It produces explainable audit
reports and correction candidates so risky manual-entry geography can be
reviewed case by case.

Default inputs:
  - dwh.dim_geo from PostgreSQL
  - data/reference/dim_geo/geo_tunisia_reference.csv

The reference file must contain:
  localite, delegation, gouvernorat, region, code_postal, aliases, confidence

Aliases can be separated with "|" or ";". Confidence can be HIGH, MEDIUM,
LOW, or a numeric value between 0 and 1.

Usage:
  python etl/dwh/audit/audit_dim_geo.py
  python etl/dwh/audit/audit_dim_geo.py --init-reference-template
"""
from __future__ import annotations

import argparse
import math
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd
from sqlalchemy import text

DWH_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DWH_DIR))
import dwh_utils


BASE_DIR = DWH_DIR.parent.parent
DEFAULT_REF_CSV = BASE_DIR / "data" / "reference" / "dim_geo" / "geo_tunisia_reference.csv"
REPORT_DIR = BASE_DIR / "data" / "quality_reports" / "dim_geo"

OUTPUT_ALL = REPORT_DIR / "dim_geo_audit_all.csv"
OUTPUT_VALIDATED = REPORT_DIR / "dim_geo_validated.csv"
OUTPUT_CANDIDATES = REPORT_DIR / "dim_geo_correction_candidates.csv"
OUTPUT_CONFLICTS = REPORT_DIR / "dim_geo_conflicts.csv"
OUTPUT_MANUAL = REPORT_DIR / "dim_geo_manual_review.csv"
OUTPUT_NON_CORR = REPORT_DIR / "dim_geo_non_corrigeable.csv"

STATUS_VALIDATED_REFERENCE = "VALIDATED_REFERENCE"
STATUS_VALIDATED_GOV_ONLY = "VALIDATED_GOV_ONLY"
STATUS_CORRECTION_CANDIDATE = "CORRECTION_CANDIDATE"
STATUS_CONFLICT = "CONFLICT"
STATUS_MANUAL_REVIEW = "MANUAL_REVIEW"
STATUS_NON_CORRIGEABLE = "NON_CORRIGEABLE"
STATUS_UNKNOWN = "UNKNOWN"

UNKNOWN = "UNKNOWN"

REQUIRED_REF_COLUMNS = {
    "localite",
    "delegation",
    "gouvernorat",
    "region",
    "code_postal",
    "aliases",
    "confidence",
}

VALID_GOVERNORATS = frozenset(
    {
        "TUNIS",
        "ARIANA",
        "BEN AROUS",
        "MANOUBA",
        "NABEUL",
        "ZAGHOUAN",
        "BIZERTE",
        "BEJA",
        "JENDOUBA",
        "KEF",
        "SILIANA",
        "SOUSSE",
        "MONASTIR",
        "MAHDIA",
        "SFAX",
        "KAIROUAN",
        "KASSERINE",
        "SIDI BOUZID",
        "GABES",
        "MEDENINE",
        "TATAOUINE",
        "GAFSA",
        "TOZEUR",
        "KEBILI",
    }
)

GOVERNORAT_ALIASES = {
    "ARI": "ARIANA",
    "ARIA": "ARIANA",
    "ARIAN": "ARIANA",
    "ARIANA VILLE": "ARIANA",
    "AEN AROUS": "BEN AROUS",
    "BENAROUS": "BEN AROUS",
    "BENA ROUS": "BEN AROUS",
    "BEN AOUS": "BEN AROUS",
    "BEN AROU": "BEN AROUS",
    "BEN ARUS": "BEN AROUS",
    "BIZER": "BIZERTE",
    "BIZERT": "BIZERTE",
    "BIZERTA": "BIZERTE",
    "GAFES": "GAFSA",
    "GABES VILLE": "GABES",
    "JANDOUBA": "JENDOUBA",
    "KAIROUEN": "KAIROUAN",
    "KEROUAN": "KAIROUAN",
    "KASSERIEN": "KASSERINE",
    "KEBILLI": "KEBILI",
    "LE KEF": "KEF",
    "EL KEF": "KEF",
    "LA MANNOUBA": "MANOUBA",
    "MANNOUBA": "MANOUBA",
    "MANOUBA VILLE": "MANOUBA",
    "MEDNINE": "MEDENINE",
    "MEDNIN": "MEDENINE",
    "MONASTIR VILLE": "MONASTIR",
    "NABEL": "NABEUL",
    "NABEOUL": "NABEUL",
    "SAFX": "SFAX",
    "SFA": "SFAX",
    "SFX": "SFAX",
    "SFXA": "SFAX",
    "SFGAX": "SFAX",
    "SFAX VILLE": "SFAX",
    "SIDI BOUSID": "SIDI BOUZID",
    "SIDI BOUZAID": "SIDI BOUZID",
    "SOUSS": "SOUSSE",
    "SOUSSE VILLE": "SOUSSE",
    "STUNIS": "TUNIS",
    "TUNI": "TUNIS",
    "TUNID": "TUNIS",
    "TUINS": "TUNIS",
    "TUIS": "TUNIS",
    "TUNS": "TUNIS",
    "TUNIS VILLE": "TUNIS",
    "TUNISIE": "TUNIS",
    "ZAGHOUANE": "ZAGHOUAN",
}

INVALID_TEXT = frozenset(
    {
        "",
        ".",
        "..",
        "-",
        "--",
        "---",
        "/",
        "0",
        "00",
        "0000",
        "1",
        "NULL",
        "NAN",
        "NONE",
        "UNKNOWN",
        "INCONNU",
        "INCONNUE",
        "NON RENSEIGNE",
        "NON RENSEIGNEE",
        "NA",
        "N A",
        "N/A",
        "#N/A",
        "ND",
        "NR",
    }
)

GENERIC_PLACE_TERMS = frozenset(
    {
        "AVENUE",
        "AV",
        "BOULEVARD",
        "CENTRE",
        "CENTRE VILLE",
        "CITE",
        "EL",
        "LA",
        "LES",
        "RUE",
        "ROUTE",
        "RTE",
        "SID",
        "SIDI",
        "VILLE",
        "ZONE",
    }
)


@dataclass(frozen=True)
class ReferenceRow:
    ref_id: int
    localite: str
    delegation: str
    gouvernorat: str
    region: str
    code_postal: str
    confidence: float
    localite_norm: str
    delegation_norm: str
    gouvernorat_norm: str
    region_norm: str
    code_postal_norm: str
    aliases_norm: tuple[str, ...]
    terms_norm: tuple[str, ...]


@dataclass(frozen=True)
class MatchCandidate:
    ref: ReferenceRow
    score: float
    source_field: str
    match_type: str
    matched_term: str


def normalize_text(raw) -> str | None:
    """Normalize free text for matching while preserving business values."""
    if raw is None:
        return None
    if isinstance(raw, float) and math.isnan(raw):
        return None
    s = str(raw).strip()
    if not s:
        return None

    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.upper()
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s or s in INVALID_TEXT:
        return None

    # Frequent Tunisian address variants seen in manually typed data.
    replacements = [
        (r"\bCITEE\b", "CITE"),
        (r"\bCTE\b", "CITE"),
        (r"\bEL\s+MANZEH\b", "EL MENZAH"),
        (r"\bEL\s+MENZEH\b", "EL MENZAH"),
        (r"\bMANZEH\b", "EL MENZAH"),
        (r"\bMENZEH\b", "EL MENZAH"),
        (r"\bENNASSER\b", "ENNASR"),
        (r"\bENNASER\b", "ENNASR"),
        (r"\bENNASSR\b", "ENNASR"),
        (r"\bLANDLOUS\b", "EL ANDALOUS"),
        (r"\bL ANDALOUS\b", "EL ANDALOUS"),
        (r"\bOUED\s+ELLILI\b", "OUED ELLIL"),
        (r"\bOUED\s+ELILI\b", "OUED ELLIL"),
        (r"\bELKRAM\b", "EL KRAM"),
    ]
    for pattern, replacement in replacements:
        s = re.sub(pattern, replacement, s)

    s = re.sub(r"\s+", " ", s).strip()
    return None if not s or s in INVALID_TEXT else s


def normalize_gouvernorat(raw) -> str | None:
    s = normalize_text(raw)
    if s is None:
        return None
    s = re.sub(r"\bGOUVERNORAT\b", "", s).strip()
    s = re.sub(r"\bGOVERNORAT\b", "", s).strip()
    s = re.sub(r"\s+", " ", s).strip()
    if s in VALID_GOVERNORATS:
        return s
    if s in GOVERNORAT_ALIASES:
        return GOVERNORAT_ALIASES[s]
    return s


def normalize_code_postal(raw) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, float) and math.isnan(raw):
        return None
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return None
    try:
        value = int(digits)
    except ValueError:
        return None
    return str(value).zfill(4) if 700 <= value <= 9999 else None


def to_output(value: str | None) -> str:
    return value if value else UNKNOWN


def confidence_to_float(raw) -> float:
    s = normalize_text(raw)
    if s is None:
        return 1.0
    if s == "HIGH":
        return 1.0
    if s == "MEDIUM":
        return 0.8
    if s == "LOW":
        return 0.6
    try:
        value = float(str(raw).strip().replace(",", "."))
    except ValueError:
        return 1.0
    if value > 1:
        value = value / 100
    return max(0.0, min(1.0, value))


def split_aliases(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, float) and math.isnan(raw):
        return []
    result: list[str] = []
    for part in re.split(r"[|;]", str(raw)):
        alias = normalize_text(part)
        if alias and alias not in result:
            result.append(alias)
    return result


def is_generic_term(term: str | None) -> bool:
    if term is None:
        return True
    if term in INVALID_TEXT or term in GENERIC_PLACE_TERMS:
        return True
    if len(term) < 3:
        return True
    if term.isdigit():
        return True
    return False


def standardize_reference_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    aliases = {
        "cpost": "code_postal",
        "cp": "code_postal",
        "postal_code": "code_postal",
        "codepostal": "code_postal",
        "gouvernor": "gouvernorat",
        "gouvernorat_norm": "gouvernorat",
        "localite_norm": "localite",
        "cite": "localite",
        "cite_norm": "localite",
        "delegation_norm": "delegation",
        "region_norm": "region",
    }
    rename = {c: aliases[c] for c in df.columns if c in aliases}
    df = df.rename(columns=rename)
    return df


def read_reference(path: Path) -> list[ReferenceRow]:
    if not path.exists():
        raise FileNotFoundError(
            f"Reference file not found: {path}. "
            "Create it with columns: "
            "localite, delegation, gouvernorat, region, code_postal, aliases, confidence."
        )

    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df = standardize_reference_columns(df)
    missing = REQUIRED_REF_COLUMNS.difference(df.columns)
    if missing:
        raise ValueError(
            f"Reference file {path} is missing columns: {sorted(missing)}"
        )

    rows: list[ReferenceRow] = []
    for idx, row in df.iterrows():
        localite_norm = normalize_text(row["localite"])
        delegation_norm = normalize_text(row["delegation"])
        gouvernorat_norm = normalize_gouvernorat(row["gouvernorat"])
        region_norm = normalize_text(row["region"])
        code_postal_norm = normalize_code_postal(row["code_postal"])
        aliases_norm = tuple(split_aliases(row["aliases"]))
        confidence = confidence_to_float(row["confidence"])

        if gouvernorat_norm not in VALID_GOVERNORATS:
            continue
        if localite_norm is None and delegation_norm is None:
            continue

        terms = []
        for term in (localite_norm, delegation_norm, *aliases_norm):
            if term and not is_generic_term(term) and term not in terms:
                terms.append(term)

        rows.append(
            ReferenceRow(
                ref_id=idx,
                localite=to_output(localite_norm),
                delegation=to_output(delegation_norm),
                gouvernorat=gouvernorat_norm,
                region=to_output(region_norm),
                code_postal=to_output(code_postal_norm),
                confidence=confidence,
                localite_norm=to_output(localite_norm),
                delegation_norm=to_output(delegation_norm),
                gouvernorat_norm=gouvernorat_norm,
                region_norm=to_output(region_norm),
                code_postal_norm=to_output(code_postal_norm),
                aliases_norm=aliases_norm,
                terms_norm=tuple(terms),
            )
        )

    if not rows:
        raise ValueError(
            f"Reference file {path} contains no usable rows after normalization."
        )
    return rows


def build_indexes(ref_rows: list[ReferenceRow]):
    term_index: dict[str, list[ReferenceRow]] = defaultdict(list)
    code_index: dict[str, list[ReferenceRow]] = defaultdict(list)
    all_terms: list[tuple[str, ReferenceRow]] = []

    for ref in ref_rows:
        if ref.code_postal_norm != UNKNOWN:
            code_index[ref.code_postal_norm].append(ref)
        for term in ref.terms_norm:
            term_index[term].append(ref)
            all_terms.append((term, ref))

    return term_index, code_index, all_terms


def exact_match_type(term: str, ref: ReferenceRow) -> str:
    if term == ref.localite_norm:
        return "exact_localite"
    if term == ref.delegation_norm:
        return "exact_delegation"
    if term in ref.aliases_norm:
        return "exact_alias"
    return "exact_reference_term"


def score_candidate(
    ref: ReferenceRow,
    source_field: str,
    match_type: str,
    base_score: float,
    row_gouvernorat: str | None,
    row_code_postal: str | None,
) -> float:
    score = base_score

    if match_type == "exact_localite":
        score += 5
    elif match_type == "exact_alias":
        score += 3
    elif match_type == "exact_delegation":
        score += 2

    if source_field == "localite":
        score += 2
    elif source_field == "region":
        score -= 1

    if row_gouvernorat in VALID_GOVERNORATS:
        if row_gouvernorat == ref.gouvernorat_norm:
            score += 6
        else:
            score -= 15

    if row_code_postal:
        if ref.code_postal_norm == row_code_postal:
            score += 8
        elif ref.code_postal_norm != UNKNOWN:
            score -= 8

    score = max(0.0, min(100.0, score))
    return round(score * ref.confidence, 2)


def add_exact_candidates(
    candidates: list[MatchCandidate],
    term_index: dict[str, list[ReferenceRow]],
    term: str | None,
    source_field: str,
    row_gouvernorat: str | None,
    row_code_postal: str | None,
) -> None:
    if is_generic_term(term):
        return
    assert term is not None
    for ref in term_index.get(term, []):
        match_type = exact_match_type(term, ref)
        base_score = 90 if source_field == "localite" else 84
        score = score_candidate(
            ref=ref,
            source_field=source_field,
            match_type=match_type,
            base_score=base_score,
            row_gouvernorat=row_gouvernorat,
            row_code_postal=row_code_postal,
        )
        candidates.append(
            MatchCandidate(
                ref=ref,
                score=score,
                source_field=source_field,
                match_type=match_type,
                matched_term=term,
            )
        )


def add_code_candidates(
    candidates: list[MatchCandidate],
    code_index: dict[str, list[ReferenceRow]],
    code_postal: str | None,
    row_gouvernorat: str | None,
) -> None:
    if code_postal is None:
        return
    for ref in code_index.get(code_postal, []):
        score = score_candidate(
            ref=ref,
            source_field="code_postal",
            match_type="exact_code_postal",
            base_score=88,
            row_gouvernorat=row_gouvernorat,
            row_code_postal=code_postal,
        )
        candidates.append(
            MatchCandidate(
                ref=ref,
                score=score,
                source_field="code_postal",
                match_type="exact_code_postal",
                matched_term=code_postal,
            )
        )


def add_fuzzy_candidates(
    candidates: list[MatchCandidate],
    all_terms: list[tuple[str, ReferenceRow]],
    term: str | None,
    source_field: str,
    row_gouvernorat: str | None,
    row_code_postal: str | None,
) -> None:
    if is_generic_term(term):
        return
    assert term is not None

    for ref_term, ref in all_terms:
        if row_gouvernorat in VALID_GOVERNORATS and ref.gouvernorat_norm != row_gouvernorat:
            # Keep conflicting exact matches, but keep fuzzy search conservative.
            continue
        ratio = SequenceMatcher(None, term, ref_term).ratio()
        if ratio < 0.82:
            continue
        score = score_candidate(
            ref=ref,
            source_field=source_field,
            match_type="fuzzy",
            base_score=ratio * 86,
            row_gouvernorat=row_gouvernorat,
            row_code_postal=row_code_postal,
        )
        candidates.append(
            MatchCandidate(
                ref=ref,
                score=score,
                source_field=source_field,
                match_type="fuzzy",
                matched_term=ref_term,
            )
        )


def dedupe_candidates(candidates: list[MatchCandidate]) -> list[MatchCandidate]:
    best_by_ref: dict[int, MatchCandidate] = {}
    for cand in candidates:
        current = best_by_ref.get(cand.ref.ref_id)
        if current is None or cand.score > current.score:
            best_by_ref[cand.ref.ref_id] = cand
    return sorted(best_by_ref.values(), key=lambda c: c.score, reverse=True)


def summarize_candidates(candidates: list[MatchCandidate], limit: int = 3) -> str:
    parts = []
    for cand in candidates[:limit]:
        parts.append(
            f"{cand.ref.localite}/{cand.ref.delegation}/{cand.ref.gouvernorat}"
            f" ({cand.score:.2f}, {cand.match_type}, {cand.source_field})"
        )
    return " | ".join(parts)


def is_source_already_reference(cand: MatchCandidate, row_gouvernorat: str | None) -> bool:
    if row_gouvernorat != cand.ref.gouvernorat_norm:
        return False
    if cand.source_field == "region":
        return False
    return cand.match_type in {
        "exact_localite",
        "exact_delegation",
        "exact_code_postal",
    }


def audit_one_row(
    row: pd.Series,
    term_index: dict[str, list[ReferenceRow]],
    code_index: dict[str, list[ReferenceRow]],
    all_terms: list[tuple[str, ReferenceRow]],
) -> dict:
    row_gouvernorat = normalize_gouvernorat(row.get("gouvernorat"))
    row_region = normalize_text(row.get("region"))
    row_localite = normalize_text(row.get("localite"))
    row_code_postal = normalize_code_postal(row.get("code_postal"))

    geo_sk = str(row.get("geo_sk", "")).strip()
    no_signal = not any([row_gouvernorat, row_region, row_localite, row_code_postal])
    if geo_sk == "0" or no_signal:
        return {
            "geo_audit_status": STATUS_UNKNOWN,
            "geo_audit_reason": "technical unknown row or no usable geographical signal",
            "confidence_score": 0.0,
            "candidate_region": UNKNOWN,
            "candidate_gouvernorat": UNKNOWN,
            "candidate_delegation": UNKNOWN,
            "candidate_localite": UNKNOWN,
            "candidate_code_postal": UNKNOWN,
            "matched_source_field": UNKNOWN,
            "matched_reference_key": UNKNOWN,
            "candidate_summary": "",
            "source_region_norm": to_output(row_region),
            "source_gouvernorat_norm": to_output(row_gouvernorat),
            "source_localite_norm": to_output(row_localite),
            "source_code_postal_norm": to_output(row_code_postal),
        }

    candidates: list[MatchCandidate] = []
    add_exact_candidates(
        candidates,
        term_index,
        row_localite,
        "localite",
        row_gouvernorat,
        row_code_postal,
    )
    add_exact_candidates(
        candidates,
        term_index,
        row_region,
        "region",
        row_gouvernorat,
        row_code_postal,
    )
    add_code_candidates(candidates, code_index, row_code_postal, row_gouvernorat)

    # Fuzzy candidates are used only after exact/reference-term attempts.
    if not candidates:
        add_fuzzy_candidates(
            candidates,
            all_terms,
            row_localite,
            "localite",
            row_gouvernorat,
            row_code_postal,
        )
        add_fuzzy_candidates(
            candidates,
            all_terms,
            row_region,
            "region",
            row_gouvernorat,
            row_code_postal,
        )

    candidates = dedupe_candidates(candidates)

    if not candidates:
        if row_gouvernorat in VALID_GOVERNORATS:
            return {
                "geo_audit_status": STATUS_VALIDATED_GOV_ONLY,
                "geo_audit_reason": "official governorate present, but no reliable reference match for region/localite",
                "confidence_score": 0.55,
                "candidate_region": UNKNOWN,
                "candidate_gouvernorat": row_gouvernorat,
                "candidate_delegation": UNKNOWN,
                "candidate_localite": UNKNOWN,
                "candidate_code_postal": UNKNOWN,
                "matched_source_field": UNKNOWN,
                "matched_reference_key": UNKNOWN,
                "candidate_summary": "",
                "source_region_norm": to_output(row_region),
                "source_gouvernorat_norm": to_output(row_gouvernorat),
                "source_localite_norm": to_output(row_localite),
                "source_code_postal_norm": to_output(row_code_postal),
            }
        status = STATUS_NON_CORRIGEABLE if is_generic_term(row_region) and is_generic_term(row_localite) else STATUS_MANUAL_REVIEW
        return {
            "geo_audit_status": status,
            "geo_audit_reason": "no reliable reference match and governorate is not confirmed",
            "confidence_score": 0.0,
            "candidate_region": UNKNOWN,
            "candidate_gouvernorat": UNKNOWN,
            "candidate_delegation": UNKNOWN,
            "candidate_localite": UNKNOWN,
            "candidate_code_postal": UNKNOWN,
            "matched_source_field": UNKNOWN,
            "matched_reference_key": UNKNOWN,
            "candidate_summary": "",
            "source_region_norm": to_output(row_region),
            "source_gouvernorat_norm": to_output(row_gouvernorat),
            "source_localite_norm": to_output(row_localite),
            "source_code_postal_norm": to_output(row_code_postal),
        }

    top = candidates[0]
    localite_governorate_conflict = next(
        (
            cand
            for cand in candidates
            if cand.source_field == "localite"
            and row_gouvernorat in VALID_GOVERNORATS
            and cand.ref.gouvernorat_norm != row_gouvernorat
            and cand.score >= 78
        ),
        None,
    )
    if localite_governorate_conflict is not None:
        top = localite_governorate_conflict
    second = candidates[1] if len(candidates) > 1 else None
    ambiguous = (
        second is not None
        and second.score >= top.score - 4
        and (
            second.ref.gouvernorat_norm != top.ref.gouvernorat_norm
            or second.ref.localite_norm != top.ref.localite_norm
        )
    )
    governorate_conflict = (
        row_gouvernorat in VALID_GOVERNORATS
        and top.ref.gouvernorat_norm != row_gouvernorat
        and top.score >= 78
    )
    region_only_with_specific_localite = (
        top.source_field == "region"
        and not is_generic_term(row_localite)
        and row_localite not in top.ref.terms_norm
    )

    if governorate_conflict:
        status = STATUS_CONFLICT
        reason = (
            "source governorate conflicts with the strongest reference match "
            f"({row_gouvernorat} vs {top.ref.gouvernorat_norm})"
        )
    elif ambiguous:
        status = STATUS_CONFLICT if second and second.ref.gouvernorat_norm != top.ref.gouvernorat_norm else STATUS_MANUAL_REVIEW
        reason = "several close reference candidates require human arbitration"
    elif region_only_with_specific_localite and row_gouvernorat == top.ref.gouvernorat_norm:
        status = STATUS_VALIDATED_GOV_ONLY
        reason = "region/delegation is coherent, but source localite remains unresolved"
    elif is_source_already_reference(top, row_gouvernorat) and top.score >= 95:
        status = STATUS_VALIDATED_REFERENCE
        reason = "source geography matches reference coherently"
    elif top.score >= 88:
        status = STATUS_CORRECTION_CANDIDATE
        reason = "single strong candidate proposed without automatic update"
    elif row_gouvernorat in VALID_GOVERNORATS and top.ref.gouvernorat_norm == row_gouvernorat:
        status = STATUS_VALIDATED_GOV_ONLY
        reason = "governorate is coherent, but localite/delegation evidence is weak"
    else:
        status = STATUS_MANUAL_REVIEW
        reason = "weak or incomplete reference evidence"

    return {
        "geo_audit_status": status,
        "geo_audit_reason": reason,
        "confidence_score": round(top.score / 100, 4),
        "candidate_region": top.ref.region,
        "candidate_gouvernorat": top.ref.gouvernorat,
        "candidate_delegation": top.ref.delegation,
        "candidate_localite": top.ref.localite,
        "candidate_code_postal": top.ref.code_postal,
        "matched_source_field": top.source_field,
        "matched_reference_key": (
            f"{top.ref.region}|{top.ref.gouvernorat}|"
            f"{top.ref.delegation}|{top.ref.localite}|{top.ref.code_postal}"
        ),
        "candidate_summary": summarize_candidates(candidates),
        "source_region_norm": to_output(row_region),
        "source_gouvernorat_norm": to_output(row_gouvernorat),
        "source_localite_norm": to_output(row_localite),
        "source_code_postal_norm": to_output(row_code_postal),
    }


def read_dim_geo() -> pd.DataFrame:
    engine = dwh_utils.build_engine()
    with engine.connect() as conn:
        return pd.read_sql(text("SELECT * FROM dwh.dim_geo ORDER BY geo_sk"), conn)


def audit_dim_geo(df_geo: pd.DataFrame, ref_rows: list[ReferenceRow]) -> pd.DataFrame:
    term_index, code_index, all_terms = build_indexes(ref_rows)
    audit_records = [
        audit_one_row(row, term_index, code_index, all_terms)
        for _, row in df_geo.iterrows()
    ]
    df_audit = pd.DataFrame(audit_records)
    return pd.concat([df_geo.reset_index(drop=True), df_audit], axis=1)


def write_reports(df: pd.DataFrame) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_ALL, index=False, encoding="utf-8-sig")

    df[df["geo_audit_status"].isin([STATUS_VALIDATED_REFERENCE, STATUS_VALIDATED_GOV_ONLY])].to_csv(
        OUTPUT_VALIDATED, index=False, encoding="utf-8-sig"
    )
    df[df["geo_audit_status"] == STATUS_CORRECTION_CANDIDATE].to_csv(
        OUTPUT_CANDIDATES, index=False, encoding="utf-8-sig"
    )
    df[df["geo_audit_status"] == STATUS_CONFLICT].to_csv(
        OUTPUT_CONFLICTS, index=False, encoding="utf-8-sig"
    )
    df[df["geo_audit_status"] == STATUS_MANUAL_REVIEW].to_csv(
        OUTPUT_MANUAL, index=False, encoding="utf-8-sig"
    )
    df[df["geo_audit_status"].isin([STATUS_NON_CORRIGEABLE, STATUS_UNKNOWN])].to_csv(
        OUTPUT_NON_CORR, index=False, encoding="utf-8-sig"
    )


def init_reference_template(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "localite",
        "delegation",
        "gouvernorat",
        "region",
        "code_postal",
        "aliases",
        "confidence",
    ]
    if path.exists():
        raise FileExistsError(f"Reference file already exists: {path}")
    pd.DataFrame(columns=columns).to_csv(path, index=False, encoding="utf-8-sig")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit dwh.dim_geo geography quality.")

    parser.add_argument(
        "--reference-csv",
        type=Path,
        default=DEFAULT_REF_CSV,
        help="Tunisian reference CSV path.",
    )
    parser.add_argument(
        "--init-reference-template",
        action="store_true",
        help="Create an empty reference CSV template and exit.",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()

    if args.init_reference_template:
        init_reference_template(args.reference_csv)
        print(f"Reference template created: {args.reference_csv}")
        return

    started_at = datetime.now(timezone.utc)
    df_geo = read_dim_geo()
    ref_rows = read_reference(args.reference_csv)
    df_audit = audit_dim_geo(df_geo, ref_rows)
    write_reports(df_audit)

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
    print("=" * 72)
    print(f"dim_geo rows audited     : {len(df_audit)}")
    print(f"reference rows usable    : {len(ref_rows)}")
    print(f"elapsed seconds          : {elapsed:.1f}")
    print("-" * 72)
    print(df_audit["geo_audit_status"].value_counts().to_string())
    print("-" * 72)
    print(f"all rows                 : {OUTPUT_ALL}")
    print(f"validated                : {OUTPUT_VALIDATED}")
    print(f"correction candidates    : {OUTPUT_CANDIDATES}")
    print(f"conflicts                : {OUTPUT_CONFLICTS}")
    print(f"manual review            : {OUTPUT_MANUAL}")
    print(f"non corrigeable/unknown  : {OUTPUT_NON_CORR}")
    print("=" * 72)


if __name__ == "__main__":
    main()






