"""
Build review candidates from excluded GEO rows using rue/quartier-zone signals.

This script is intentionally non-destructive: it reads DimRegion.csv and the
latest dim_geo_excluded.csv, then writes a PENDING review report. It never
updates staging, dwh, or approved correction files.

Example:
  python etl/dwh/audit_dim_geo_excluded_rue_candidates.py
"""
from __future__ import annotations

import argparse
import csv
import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_REFERENCE_CSV = BASE_DIR / "data" / "reference" / "dim_geo" / "DimRegion.csv"
DEFAULT_EXCLUDED_CSV = BASE_DIR / "data" / "quality_reports" / "dim_geo" / "dim_geo_excluded.csv"
DEFAULT_OUTPUT_CSV = BASE_DIR / "data" / "quality_reports" / "dim_geo" / "dim_geo_excluded_rue_review_candidates.csv"

NULL_TOKENS = frozenset({
    "", "NULL", "NAN", "NONE", "UNKNOWN", "INCONNU", "INCONNUE",
    "NON RENSEIGNE", "NON RENSEIGNEE", "N/A", "NA", "#N/A", "ND", "NR",
    "/", "-", "--", "---", ".", "..", "0", "00", "0000", "1",
})
VALID_GOVERNORATS = frozenset({
    "TUNIS", "ARIANA", "BEN AROUS", "MANOUBA", "NABEUL", "ZAGHOUAN", "BIZERTE",
    "BEJA", "JENDOUBA", "KEF", "SILIANA", "SOUSSE", "MONASTIR", "MAHDIA", "SFAX",
    "KAIROUAN", "KASSERINE", "SIDI BOUZID", "GABES", "MEDENINE", "TATAOUINE",
    "GAFSA", "TOZEUR", "KEBILI",
})
REGION_FROM_GOUVERNORAT = {
    "ARIANA": "GRAND TUNIS", "BEN AROUS": "GRAND TUNIS", "MANOUBA": "GRAND TUNIS", "TUNIS": "GRAND TUNIS",
    "BIZERTE": "NORD EST", "NABEUL": "NORD EST", "ZAGHOUAN": "NORD EST",
    "BEJA": "NORD OUEST", "JENDOUBA": "NORD OUEST", "KEF": "NORD OUEST", "SILIANA": "NORD OUEST",
    "MONASTIR": "CENTRE EST", "MAHDIA": "CENTRE EST", "SFAX": "CENTRE EST", "SOUSSE": "CENTRE EST",
    "KAIROUAN": "CENTRE OUEST", "KASSERINE": "CENTRE OUEST", "SIDI BOUZID": "CENTRE OUEST",
    "GABES": "SUD EST", "MEDENINE": "SUD EST", "TATAOUINE": "SUD EST",
    "GAFSA": "SUD OUEST", "KEBILI": "SUD OUEST", "TOZEUR": "SUD OUEST",
}
GOVERNORAT_ALIASES = {
    "MANNOUBA": "MANOUBA", "LA MANNOUBA": "MANOUBA", "BENA ROUS": "BEN AROUS", "BEN ARUS": "BEN AROUS",
    "BIZERT": "BIZERTE", "BIZERTA": "BIZERTE", "NABEL": "NABEUL", "SAFX": "SFAX", "SFX": "SFAX",
    "SOUSS": "SOUSSE", "SOSSE": "SOUSSE", "MEDNINE": "MEDENINE", "MEDNIN": "MEDENINE",
}
ZONE_PAT = re.compile(r"\b(CITE|ZONE|CENTRE|URBAIN|LAC|BERGES|LAFAYETTE|BELVEDERE|KANTAOUI|AUTOROUTE|RIADH|ENNASR|INTILAKA)\b")

OUTPUT_COLUMNS = [
    "approval_status", "review_priority", "review_decision_rule", "geo_audit_status",
    "source_geo_key", "source_gouvernorat", "source_localite", "source_code_postal", "source_region", "source_rue",
    "source_label_type", "matched_source_field", "matched_reference_terms", "matched_reference_key",
    "current_region", "current_gouvernorat", "current_localite", "current_code_postal",
    "approved_region", "approved_gouvernorat", "approved_delegation", "approved_localite", "approved_code_postal",
    "confidence_score", "reviewer_comment", "candidate_reason",
]


@dataclass(frozen=True)
class ReferenceRow:
    gouvernorat: str
    delegation: str
    localite: str
    code_postal: str


@dataclass(frozen=True)
class Target:
    gouvernorat: str
    delegation: str
    localite: str
    code_postal: str
    matched_reference_key: str


@dataclass(frozen=True)
class ReferenceIndex:
    by_localite: dict[str, tuple[ReferenceRow, ...]]
    by_delegation: dict[str, tuple[ReferenceRow, ...]]
    terms: tuple[str, ...]
    term_set: frozenset[str]
    max_term_tokens: int

def normalize_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return None if text in NULL_TOKENS else text


def normalize_gouvernorat(value: object) -> str | None:
    text = normalize_text(value)
    if text is None:
        return None
    return GOVERNORAT_ALIASES.get(text, text)


def normalize_postal_code(value: object) -> str | None:
    text = normalize_text(value)
    if text is None:
        return None
    compact = re.sub(r"\s+", "", text)
    float_match = re.fullmatch(r"(\d+)[\.,]0+", compact)
    if float_match:
        compact = float_match.group(1)
    digits = re.sub(r"\D", "", compact)
    if not digits:
        return None
    try:
        numeric = int(digits)
    except ValueError:
        return None
    return str(numeric).zfill(4) if 700 <= numeric <= 9999 else None


def _unique(values: Iterable[str | None]) -> list[str]:
    return sorted({value for value in values if value})


def _reference_key(target: Target) -> str:
    region = REGION_FROM_GOUVERNORAT.get(target.gouvernorat, "UNKNOWN")
    cp = target.code_postal or "UNKNOWN"
    return f"{region}|{target.gouvernorat}|{target.delegation}|{target.localite}|{cp}"


def _row_from_reference(raw: dict[str, str]) -> ReferenceRow | None:
    gouvernorat = normalize_gouvernorat(raw.get("Gouvernorat"))
    delegation = normalize_text(raw.get("Delegation"))
    localite = normalize_text(raw.get("Localite"))
    code_postal = normalize_postal_code(raw.get("Code postal"))
    if gouvernorat not in VALID_GOVERNORATS or not localite or not code_postal:
        return None
    return ReferenceRow(gouvernorat, delegation or "", localite, code_postal)


def read_reference(path: Path) -> tuple[ReferenceRow, ...]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        rows = [_row_from_reference(raw) for raw in reader]
    return tuple(row for row in rows if row is not None)


def build_reference_index(rows: Iterable[ReferenceRow]) -> ReferenceIndex:
    by_localite: defaultdict[str, list[ReferenceRow]] = defaultdict(list)
    by_delegation: defaultdict[str, list[ReferenceRow]] = defaultdict(list)
    for row in rows:
        by_localite[row.localite].append(row)
        if row.delegation:
            by_delegation[row.delegation].append(row)
    terms = sorted(set(by_localite) | set(by_delegation), key=lambda value: (-len(value), value))
    max_term_tokens = max((len(term.split()) for term in terms), default=1)
    return ReferenceIndex(
        by_localite={key: tuple(value) for key, value in by_localite.items()},
        by_delegation={key: tuple(value) for key, value in by_delegation.items()},
        terms=tuple(terms),
        term_set=frozenset(terms),
        max_term_tokens=max_term_tokens,
    )

def _collapse_localite(refs: tuple[ReferenceRow, ...]) -> Target | None:
    gov_localites = {(ref.gouvernorat, ref.localite) for ref in refs}
    if len(gov_localites) != 1:
        return None
    gouvernorat, localite = next(iter(gov_localites))
    delegations = _unique(ref.delegation for ref in refs)
    codes = _unique(ref.code_postal for ref in refs)
    target = Target(
        gouvernorat=gouvernorat,
        delegation=delegations[0] if len(delegations) == 1 else "",
        localite=localite,
        code_postal=codes[0] if len(codes) == 1 else "",
        matched_reference_key="",
    )
    return Target(target.gouvernorat, target.delegation, target.localite, target.code_postal, _reference_key(target))


def _collapse_delegation(refs: tuple[ReferenceRow, ...]) -> Target | None:
    gov_delegations = {(ref.gouvernorat, ref.delegation) for ref in refs if ref.delegation}
    if len(gov_delegations) != 1:
        return None
    gouvernorat, delegation = next(iter(gov_delegations))
    codes = _unique(ref.code_postal for ref in refs)
    target = Target(
        gouvernorat=gouvernorat,
        delegation=delegation,
        localite=delegation,
        code_postal=codes[0] if len(codes) == 1 else "",
        matched_reference_key="",
    )
    return Target(target.gouvernorat, target.delegation, target.localite, target.code_postal, _reference_key(target))


def _target_for_term(term: str, ref_index: ReferenceIndex) -> Target | None:
    localite_target = _collapse_localite(ref_index.by_localite.get(term, ()))
    delegation_target = _collapse_delegation(ref_index.by_delegation.get(term, ()))
    targets = [target for target in (localite_target, delegation_target) if target is not None]
    unique_keys = {(target.gouvernorat, target.delegation, target.localite, target.code_postal) for target in targets}
    if len(unique_keys) == 1:
        return targets[0]
    if len(targets) == 1:
        return targets[0]
    return None


def classify_source_label(source_localite: str | None) -> str:
    value = normalize_text(source_localite)
    if not value:
        return "MISSING"
    if value in VALID_GOVERNORATS:
        return "GOUVERNORAT"
    if ZONE_PAT.search(value):
        return "QUARTIER_ZONE"
    return "LOCALITE_OR_FREE_TEXT"


def _spans_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def find_reference_terms(text: str | None, ref_index: ReferenceIndex, source_localite: str | None = None) -> list[str]:
    value = normalize_text(text)
    if not value:
        return []
    source_value = normalize_text(source_localite)
    tokens = value.split()
    raw_candidates: list[tuple[str, int, int]] = []
    max_size = min(ref_index.max_term_tokens, len(tokens))
    for start in range(len(tokens)):
        for size in range(max_size, 0, -1):
            end = start + size
            if end > len(tokens):
                continue
            term = " ".join(tokens[start:end])
            if term not in ref_index.term_set:
                continue
            if len(term) < 5 or term in VALID_GOVERNORATS:
                continue
            if source_value and term == source_value:
                continue
            raw_candidates.append((term, start, end))

    selected: list[tuple[str, int, int]] = []
    for term, start, end in sorted(raw_candidates, key=lambda item: (-(item[2] - item[1]), item[1], item[0])):
        span = (start, end)
        if any(_spans_overlap(span, (chosen_start, chosen_end)) for _, chosen_start, chosen_end in selected):
            continue
        selected.append((term, start, end))
    return [term for term, _, _ in selected]

def _base_candidate_fields(row: dict[str, str], source_localite: str | None, source_geo_key: str) -> dict[str, str]:
    return {
        "source_geo_key": source_geo_key,
        "source_gouvernorat": row.get("source_gouvernorat", ""),
        "source_localite": row.get("source_localite", ""),
        "source_code_postal": row.get("source_code_postal", ""),
        "source_region": row.get("source_region", ""),
        "source_rue": row.get("source_rue", ""),
        "source_label_type": classify_source_label(source_localite),
        "current_region": "UNKNOWN",
        "current_gouvernorat": normalize_gouvernorat(row.get("source_gouvernorat")) or "UNKNOWN",
        "current_localite": source_localite or "UNKNOWN",
        "current_code_postal": normalize_postal_code(row.get("source_code_postal")) or "UNKNOWN",
    }


def _ambiguous_reference_summary(term: str, ref_index: ReferenceIndex, limit: int = 6) -> str:
    refs = list(ref_index.by_localite.get(term, ())) + list(ref_index.by_delegation.get(term, ()))
    parts = []
    seen = set()
    for ref in refs:
        key = f"{REGION_FROM_GOUVERNORAT.get(ref.gouvernorat, 'UNKNOWN')}|{ref.gouvernorat}|{ref.delegation}|{ref.localite}|{ref.code_postal}"
        if key not in seen:
            seen.add(key)
            parts.append(key)
        if len(parts) >= limit:
            break
    suffix = f" (+{len(seen) - limit})" if len(seen) > limit else ""
    return " | ".join(parts) + suffix


def build_candidate(row: dict[str, str], ref_index: ReferenceIndex) -> dict[str, str] | None:
    source_localite = normalize_text(row.get("source_localite"))
    source_rue = normalize_text(row.get("source_rue"))
    search_fields = [("source_rue", source_rue), ("source_localite", source_localite), ("source_region", normalize_text(row.get("source_region")))]

    matched_field = ""
    matched_terms: list[str] = []
    ambiguous_terms: list[str] = []
    targets: list[Target] = []
    for field, value in search_fields:
        terms = find_reference_terms(value, ref_index, source_localite=source_localite)
        if not terms:
            continue
        field_targets: list[Target] = []
        field_ambiguous: list[str] = []
        for term in terms:
            target = _target_for_term(term, ref_index)
            if target is None:
                field_ambiguous.append(term)
            else:
                field_targets.append(target)
        if field_targets or field_ambiguous:
            matched_field = field
            matched_terms = terms
            ambiguous_terms = field_ambiguous
            targets = field_targets
            break

    if not targets and not ambiguous_terms:
        return None

    source_geo_key = str(row.get("_source_geo_key", "")).strip()
    base = _base_candidate_fields(row, source_localite, source_geo_key)
    unique_targets = {
        (target.gouvernorat, target.delegation, target.localite, target.code_postal): target
        for target in targets
    }

    if len(unique_targets) == 1 and not ambiguous_terms:
        target = next(iter(unique_targets.values()))
        return {
            "approval_status": "PENDING",
            "review_priority": "HIGH" if classify_source_label(source_localite) == "QUARTIER_ZONE" else "MEDIUM",
            "review_decision_rule": "RUE_UNIQUE_DIMREGION_TERM_REVIEW",
            "geo_audit_status": "CORRECTION_CANDIDATE",
            **base,
            "matched_source_field": matched_field,
            "matched_reference_terms": "|".join(matched_terms),
            "matched_reference_key": target.matched_reference_key,
            "approved_region": REGION_FROM_GOUVERNORAT.get(target.gouvernorat, "UNKNOWN"),
            "approved_gouvernorat": target.gouvernorat,
            "approved_delegation": target.delegation,
            "approved_localite": target.localite,
            "approved_code_postal": target.code_postal or "UNKNOWN",
            "confidence_score": "0.70" if matched_field == "source_rue" else "0.65",
            "reviewer_comment": "PENDING review: candidate inferred from rue/quartier-zone term; not applied automatically.",
            "candidate_reason": "A term in the free-text geography matches one unique DimRegion target; manual approval required.",
        }

    summaries = []
    for target in unique_targets.values():
        summaries.append(target.matched_reference_key)
    for term in ambiguous_terms:
        summary = _ambiguous_reference_summary(term, ref_index)
        if summary:
            summaries.append(f"{term}: {summary}")

    return {
        "approval_status": "PENDING",
        "review_priority": "MEDIUM",
        "review_decision_rule": "RUE_AMBIGUOUS_DIMREGION_TERMS_REVIEW",
        "geo_audit_status": "AMBIGUOUS_CANDIDATE",
        **base,
        "matched_source_field": matched_field,
        "matched_reference_terms": "|".join(matched_terms),
        "matched_reference_key": " | ".join(summaries),
        "approved_region": "",
        "approved_gouvernorat": "",
        "approved_delegation": "",
        "approved_localite": "",
        "approved_code_postal": "",
        "confidence_score": "0.00",
        "reviewer_comment": "PENDING review: ambiguous rue/quartier-zone signal; do not auto-approve.",
        "candidate_reason": "Free-text geography contains ambiguous or multiple DimRegion targets.",
    }

def read_excluded(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_candidates(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def generate_candidates(excluded_rows: Iterable[dict[str, str]], ref_index: ReferenceIndex) -> list[dict[str, str]]:
    candidates = []
    seen_keys: set[tuple[str, str, str]] = set()
    for row in excluded_rows:
        candidate = build_candidate(row, ref_index)
        if candidate is None:
            continue
        dedup_key = (
            candidate.get("source_geo_key", ""),
            candidate.get("matched_reference_terms", ""),
            candidate.get("matched_reference_key", ""),
        )
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)
        candidates.append(candidate)
    return candidates


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate PENDING GEO correction candidates from rue/quartier-zone signals.")
    parser.add_argument("--reference-csv", type=Path, default=DEFAULT_REFERENCE_CSV)
    parser.add_argument("--excluded-csv", type=Path, default=DEFAULT_EXCLUDED_CSV)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    reference_rows = read_reference(args.reference_csv)
    ref_index = build_reference_index(reference_rows)
    excluded_rows = read_excluded(args.excluded_csv)
    candidates = generate_candidates(excluded_rows, ref_index)
    write_candidates(args.output_csv, candidates)

    unique = sum(1 for row in candidates if row["geo_audit_status"] == "CORRECTION_CANDIDATE")
    ambiguous = sum(1 for row in candidates if row["geo_audit_status"] == "AMBIGUOUS_CANDIDATE")
    print("=" * 72)
    print(f"excluded rows read      : {len(excluded_rows)}")
    print(f"review candidates       : {len(candidates)}")
    print(f"unique correction hints : {unique}")
    print(f"ambiguous hints         : {ambiguous}")
    print(f"output                  : {args.output_csv}")
    print("=" * 72)


if __name__ == "__main__":
    main()
