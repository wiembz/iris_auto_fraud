"""
Build fuzzy DimRegion GEO candidates and mark double-proof rows when an external
verification report already confirms the same target.

This script is non-destructive by default. It does not call the web. It reads:
  - data/quality_reports/dim_geo/dim_geo_conflicts_after_resolution.csv
  - data/reference/dim_geo/DimRegion.csv
  - data/quality_reports/dim_geo/dim_geo_nominatim_verified_candidates.csv, if present

Outputs:
  - data/quality_reports/dim_geo/dim_geo_fuzzy_web_candidates.csv
  - optionally, geo_dim_auto_double_proof_corrections.csv when --write-auto-corrections is used
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import load_dim_geo as geo

DEFAULT_INPUT_CSV = BASE_DIR / "data" / "quality_reports" / "dim_geo" / "dim_geo_conflicts_after_resolution.csv"
DEFAULT_NOMINATIM_CSV = BASE_DIR / "data" / "quality_reports" / "dim_geo" / "dim_geo_nominatim_verified_candidates.csv"
DEFAULT_OUTPUT_CSV = BASE_DIR / "data" / "quality_reports" / "dim_geo" / "dim_geo_fuzzy_web_candidates.csv"
DEFAULT_AUTO_CORRECTIONS_CSV = BASE_DIR / "data" / "reference" / "dim_geo" / "geo_dim_auto_double_proof_corrections.csv"

OUTPUT_COLUMNS = [
    "candidate_decision",
    "candidate_reason",
    "source_geo_key",
    "source_gouvernorat",
    "source_localite",
    "source_region",
    "source_rue",
    "source_code_postal",
    "current_region",
    "current_gouvernorat",
    "current_localite",
    "current_code_postal",
    "matched_source_field",
    "matched_source_value",
    "match_method",
    "match_confidence",
    "external_proof_status",
    "approved_region",
    "approved_gouvernorat",
    "approved_delegation",
    "approved_localite",
    "approved_code_postal",
    "matched_reference_key",
]

AUTO_COLUMNS = [
    "geo_key",
    "source_geo_key",
    "current_region",
    "current_gouvernorat",
    "current_localite",
    "current_code_postal",
    "approved_region",
    "approved_gouvernorat",
    "approved_delegation",
    "approved_localite",
    "approved_code_postal",
    "approval_status",
    "reviewer_comment",
    "review_decision_rule",
    "geo_audit_status",
    "confidence_score",
    "matched_source_field",
    "matched_reference_key",
]


def _clean(value: object) -> str:
    return str(value or "").strip()


def _norm(value: object) -> str:
    return _clean(value).upper()


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _target_key(row: dict[str, str]) -> tuple[str, str, str, str, str]:
    return (
        _norm(row.get("approved_region")),
        _norm(row.get("approved_gouvernorat")),
        _norm(row.get("approved_delegation")),
        _norm(row.get("approved_localite")),
        _norm(row.get("approved_code_postal")),
    )


def load_external_confirmations(path: Path) -> set[tuple[str, tuple[str, str, str, str, str]]]:
    df = _read_csv(path)
    confirmations: set[tuple[str, tuple[str, str, str, str, str]]] = set()
    if df.empty:
        return confirmations
    for _, row in df.iterrows():
        if _norm(row.get("nominatim_decision")) != "AUTO_APPROVABLE":
            continue
        if _norm(row.get("nominatim_status")) != "NOMINATIM_CONFIRMED":
            continue
        if _norm(row.get("nominatim_governorate_match")) != "YES":
            continue
        if _norm(row.get("nominatim_place_match")) != "YES":
            continue
        source_key = _norm(row.get("source_geo_key"))
        if source_key:
            confirmations.add((source_key, _target_key(row)))
    return confirmations


def build_reference_indexes() -> dict:
    df_ref = geo._read_dimregion_reference(geo.GEO_DIMREGION_REFERENCE_PATH)
    reference_indexes, _ = geo._build_reference_resolver_indexes(df_ref)
    postal_indexes, _ = geo._build_postal_resolver_indexes(df_ref)
    return geo._merge_postal_indexes(reference_indexes, postal_indexes)


def _reference_key(candidate: dict) -> str:
    return "|".join([
        geo.to_unknown(geo._REGION_FROM_GOUVERNORAT.get(candidate.get("gouvernorat"))),
        geo.to_unknown(candidate.get("gouvernorat")),
        geo.to_unknown(candidate.get("delegation")),
        geo.to_unknown(candidate.get("localite")),
        geo.to_unknown(candidate.get("code_postal")),
    ])


def _candidate_from_term(term: str, source_gouvernorat: str | None, reference_indexes: dict) -> tuple[dict | None, str, float, str]:
    terms = geo._localite_match_terms(term)
    if source_gouvernorat in geo._VALID_GOVERNORATS:
        for candidate_term in terms:
            refs = reference_indexes.get("postal_localite", {}).get((source_gouvernorat, candidate_term), [])
            ref = geo._unique_ref_from_refs(refs)
            if ref:
                return ref, "DIMREGION_EXACT_LOCALITE", 1.0, "exact DimRegion locality match"
        for candidate_term in terms:
            refs = reference_indexes.get("postal_delegation", {}).get((source_gouvernorat, candidate_term), [])
            ref = geo._unique_ref_from_refs(refs)
            if ref:
                return ref, "DIMREGION_EXACT_DELEGATION", 0.9, "exact DimRegion delegation match"
        for candidate_term in terms:
            refs = reference_indexes.get("postal_alias", {}).get((source_gouvernorat, candidate_term), [])
            ref = geo._unique_ref_from_refs(refs)
            if ref:
                return ref, "DIMREGION_ALIAS_LOCALITE", 0.96, "DimRegion generated alias match"
        for candidate_term in terms:
            key = geo._linguistic_key_for_localite(candidate_term)
            if not key:
                continue
            refs = [
                ref
                for ref in reference_indexes.get("postal_localite_linguistic_global", {}).get(key, [])
                if geo.normalize_gouvernorat(ref.get("gouvernorat")) == source_gouvernorat
            ]
            ref = geo._unique_ref_from_refs(refs)
            if ref:
                return ref, "DIMREGION_LINGUISTIC_LOCALITE", 0.94, "DimRegion linguistic/transliteration match"

    for candidate_term in terms:
        place = geo._unique_dimregion_place_from_term(candidate_term, reference_indexes)
        if place:
            return place, f"DIMREGION_GLOBAL_{place.get('method')}", float(place.get("confidence", 0.9)), "unique global DimRegion match"
    return None, "NO_CANDIDATE", 0.0, "no unique DimRegion fuzzy candidate"

def build_candidates(df_conflicts: pd.DataFrame, reference_indexes: dict, external_confirmations: set) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    candidate_cache: dict[tuple[str, str], tuple[dict | None, str, float, str]] = {}
    for _, row in df_conflicts.iterrows():
        source_key = _clean(row.get("source_geo_key") or row.get("_source_geo_key"))
        source_key_norm = _norm(source_key)
        source_gouvernorat = geo.normalize_gouvernorat(row.get("source_gouvernorat") or row.get("gouvernorat"))
        terms = [
            ("source_localite", row.get("source_localite")),
            ("localite", row.get("localite")),
            ("source_rue", row.get("source_rue")),
            ("source_region", row.get("source_region")),
        ]
        emitted_for_key = False
        for field_name, raw_term in terms:
            term = geo.normalize_text(raw_term)
            if not term:
                continue
            cache_key = (source_gouvernorat or "", term)
            if cache_key not in candidate_cache:
                candidate_cache[cache_key] = _candidate_from_term(term, source_gouvernorat, reference_indexes)
            candidate, method, confidence, reason = candidate_cache[cache_key]
            if not candidate:
                continue
            approved_gov = geo.normalize_gouvernorat(candidate.get("gouvernorat"))
            approved_localite = geo.normalize_text(candidate.get("localite"))
            approved_code = geo.normalize_cpost(candidate.get("code_postal"))
            approved_region = geo._REGION_FROM_GOUVERNORAT.get(approved_gov or "", "")
            approved_delegation = geo.normalize_text(candidate.get("delegation")) or ""
            target = (
                _norm(approved_region),
                _norm(approved_gov),
                _norm(approved_delegation),
                _norm(approved_localite),
                _norm(approved_code),
            )
            external_status = "NOMINATIM_CONFIRMED" if (source_key_norm, target) in external_confirmations else "PENDING_EXTERNAL_PROOF"
            decision = "AUTO_DOUBLE_PROOF" if external_status == "NOMINATIM_CONFIRMED" else "CANDIDATE_REVIEW"
            rows.append({
                "candidate_decision": decision,
                "candidate_reason": reason,
                "source_geo_key": source_key,
                "source_gouvernorat": _clean(row.get("source_gouvernorat")),
                "source_localite": _clean(row.get("source_localite")),
                "source_region": _clean(row.get("source_region")),
                "source_rue": _clean(row.get("source_rue")),
                "source_code_postal": _clean(row.get("source_code_postal")),
                "current_region": _clean(row.get("region")),
                "current_gouvernorat": _clean(row.get("gouvernorat")),
                "current_localite": _clean(row.get("localite")),
                "current_code_postal": _clean(row.get("code_postal")),
                "matched_source_field": field_name,
                "matched_source_value": term,
                "match_method": method,
                "match_confidence": f"{confidence:.3f}",
                "external_proof_status": external_status,
                "approved_region": approved_region,
                "approved_gouvernorat": approved_gov or "",
                "approved_delegation": approved_delegation,
                "approved_localite": approved_localite or "",
                "approved_code_postal": approved_code or "",
                "matched_reference_key": _reference_key(candidate),
            })
            emitted_for_key = True
            break
        if not emitted_for_key:
            continue
    return rows


def auto_correction_rows(candidate_rows: list[dict[str, str]], approval_status: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in candidate_rows:
        if row.get("candidate_decision") != "AUTO_DOUBLE_PROOF":
            continue
        rows.append({
            "geo_key": row["source_geo_key"],
            "source_geo_key": row["source_geo_key"],
            "current_region": row["current_region"],
            "current_gouvernorat": row["current_gouvernorat"],
            "current_localite": row["current_localite"],
            "current_code_postal": row["current_code_postal"],
            "approved_region": row["approved_region"],
            "approved_gouvernorat": row["approved_gouvernorat"],
            "approved_delegation": row["approved_delegation"],
            "approved_localite": row["approved_localite"],
            "approved_code_postal": row["approved_code_postal"],
            "approval_status": approval_status.upper(),
            "reviewer_comment": "AUTO_DOUBLE_PROOF: DimRegion fuzzy candidate confirmed by cached external verification.",
            "review_decision_rule": "AUTO_DOUBLE_PROOF_DIMREGION_FUZZY_EXTERNAL_CONFIRMED",
            "geo_audit_status": "AUTO_DOUBLE_PROOF",
            "confidence_score": row["match_confidence"],
            "matched_source_field": row["matched_source_field"],
            "matched_reference_key": row["matched_reference_key"],
        })
    return rows


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build fuzzy DimRegion + cached web proof GEO candidates.")
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--nominatim-csv", type=Path, default=DEFAULT_NOMINATIM_CSV)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--auto-corrections-csv", type=Path, default=DEFAULT_AUTO_CORRECTIONS_CSV)
    parser.add_argument("--approval-status", default="PENDING")
    parser.add_argument("--write-auto-corrections", action="store_true")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    df_conflicts = _read_csv(args.input_csv)
    reference_indexes = build_reference_indexes()
    external_confirmations = load_external_confirmations(args.nominatim_csv)
    candidates = build_candidates(df_conflicts, reference_indexes, external_confirmations)

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(candidates, columns=OUTPUT_COLUMNS).to_csv(args.output_csv, index=False, encoding="utf-8-sig")

    auto_rows = auto_correction_rows(candidates, args.approval_status)
    if args.write_auto_corrections:
        args.auto_corrections_csv.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(auto_rows, columns=AUTO_COLUMNS).to_csv(args.auto_corrections_csv, index=False, encoding="utf-8-sig")

    print("=" * 72)
    print(f"input rows             : {len(df_conflicts)}")
    print(f"candidate rows         : {len(candidates)}")
    print(f"external confirmations : {len(external_confirmations)}")
    print(f"AUTO_DOUBLE_PROOF      : {sum(1 for row in candidates if row['candidate_decision'] == 'AUTO_DOUBLE_PROOF')}")
    print(f"output                 : {args.output_csv}")
    if args.write_auto_corrections:
        print(f"auto corrections       : {args.auto_corrections_csv}")
        print(f"approval_status        : {args.approval_status.upper()}")
    print("=" * 72)


if __name__ == "__main__":
    main()
