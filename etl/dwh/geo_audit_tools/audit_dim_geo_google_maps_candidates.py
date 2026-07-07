"""
Verify DimRegion rue/quartier GEO candidates with Google Maps Geocoding.

This script is non-destructive. It reads the PENDING candidates generated from
rue/quartier signals, calls Google Maps Geocoding only when an API key is
provided, and writes a verification report. It never updates dim_geo, fact tables,
or approved correction files.

Environment:
  GOOGLE_MAPS_API_KEY=...

Example:
  python etl/dwh/geo_audit_tools/audit_dim_geo_google_maps_candidates.py --limit 50
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

try:
    from audit_dim_geo_excluded_rue_candidates import (
        REGION_FROM_GOUVERNORAT,
        VALID_GOVERNORATS,
        normalize_gouvernorat,
        normalize_text,
    )
except ModuleNotFoundError:  # pytest/package import path
    from etl.dwh.geo_audit_tools.audit_dim_geo_excluded_rue_candidates import (
        REGION_FROM_GOUVERNORAT,
        VALID_GOVERNORATS,
        normalize_gouvernorat,
        normalize_text,
    )


BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_INPUT_CSV = BASE_DIR / "data" / "quality_reports" / "dim_geo" / "dim_geo_excluded_rue_review_candidates.csv"
DEFAULT_OUTPUT_CSV = BASE_DIR / "data" / "quality_reports" / "dim_geo" / "dim_geo_google_verified_candidates.csv"
DEFAULT_CACHE_JSON = BASE_DIR / "data" / "quality_reports" / "dim_geo" / "dim_geo_google_geocode_cache.json"
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
TUNISIA_NAMES = {"TUNISIE", "TUNISIA", "TN"}
GOVERNORATE_SUFFIXES = (" GOUVERNORAT", " GOVERNORATE", " GOVERNORAT", " WILAYA")

GOOGLE_COLUMNS = [
    "google_decision",
    "google_status",
    "google_reason",
    "google_query",
    "google_api_status",
    "google_result_count",
    "google_formatted_address",
    "google_place_id",
    "google_location_type",
    "google_result_types",
    "google_lat",
    "google_lng",
    "google_country",
    "google_governorate_match",
    "google_place_match",
]


def _norm(value: object) -> str | None:
    return normalize_text(value)


def _norm_gov(value: object) -> str | None:
    value_norm = normalize_gouvernorat(value)
    if value_norm in VALID_GOVERNORATS:
        return value_norm
    return value_norm


def _strip_governorate_suffix(value: str | None) -> str | None:
    text = _norm(value)
    if not text:
        return None
    for suffix in GOVERNORATE_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return _norm_gov(text)


def _contains_tokenized(text: str, term: str | None) -> bool:
    term_norm = _norm(term)
    if not term_norm:
        return False
    return f" {term_norm} " in f" {text} "


def _field(row: dict[str, str], name: str) -> str:
    return str(row.get(name, "") or "").strip()


def build_google_query(row: dict[str, str]) -> str:
    terms = []
    for name in ("matched_reference_terms", "approved_localite", "approved_delegation", "approved_gouvernorat"):
        value = _field(row, name)
        if value and value.upper() != "UNKNOWN" and value not in terms:
            terms.append(value)
    terms.append("Tunisie")
    return ", ".join(terms)


def _cache_key(query: str, language: str) -> str:
    raw = json.dumps({"query": query, "language": language, "country": "TN"}, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        try:
            loaded = json.load(handle)
        except json.JSONDecodeError:
            return {}
    return loaded if isinstance(loaded, dict) else {}


def save_cache(path: Path, cache: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(cache, handle, ensure_ascii=False, indent=2, sort_keys=True)


def geocode_google(query: str, api_key: str, language: str, timeout_seconds: int) -> dict[str, Any]:
    params = urllib.parse.urlencode({
        "address": query,
        "components": "country:TN",
        "region": "tn",
        "language": language,
        "key": api_key,
    })
    url = f"{GOOGLE_GEOCODE_URL}?{params}"
    request = urllib.request.Request(url, headers={"User-Agent": "IRIS-AUTO-FRAUD-GEO-AUDIT/1.0"})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = response.read().decode("utf-8")
    parsed = json.loads(payload)
    parsed["_request_url_without_key"] = f"{GOOGLE_GEOCODE_URL}?" + urllib.parse.urlencode({
        "address": query,
        "components": "country:TN",
        "region": "tn",
        "language": language,
        "key": "***",
    })
    return parsed


def _component_names(result: dict[str, Any]) -> list[tuple[str, str, tuple[str, ...]]]:
    names = []
    for component in result.get("address_components", []) or []:
        long_name = str(component.get("long_name", ""))
        short_name = str(component.get("short_name", ""))
        types = tuple(str(item) for item in component.get("types", []) or [])
        names.append((long_name, short_name, types))
    return names


def _result_text(result: dict[str, Any]) -> str:
    values = [str(result.get("formatted_address", ""))]
    for long_name, short_name, _ in _component_names(result):
        values.extend([long_name, short_name])
    normalized = [_norm(value) for value in values]
    return " ".join(value for value in normalized if value)


def _country_from_result(result: dict[str, Any]) -> str:
    for long_name, short_name, types in _component_names(result):
        if "country" in types:
            return _norm(short_name) or _norm(long_name) or ""
    return ""


def _governorates_from_result(result: dict[str, Any]) -> set[str]:
    found = set()
    for long_name, short_name, types in _component_names(result):
        if "administrative_area_level_1" in types or "administrative_area_level_2" in types or "locality" in types:
            for value in (long_name, short_name):
                gov = _strip_governorate_suffix(value)
                if gov in VALID_GOVERNORATS:
                    found.add(gov)
    text = _result_text(result)
    for gov in VALID_GOVERNORATS:
        if _contains_tokenized(text, gov):
            found.add(gov)
    return found


def _expected_place_terms(row: dict[str, str]) -> list[str]:
    terms = []
    for name in ("matched_reference_terms", "approved_localite", "approved_delegation"):
        for part in _field(row, name).split("|"):
            part = part.strip()
            if part and part.upper() != "UNKNOWN" and part not in terms:
                terms.append(part)
    return terms


def evaluate_google_response(row: dict[str, str], response: dict[str, Any], query: str) -> dict[str, str]:
    api_status = str(response.get("status", "UNKNOWN"))
    results = response.get("results", []) or []
    base = {
        "google_query": query,
        "google_api_status": api_status,
        "google_result_count": str(len(results)),
        "google_formatted_address": "",
        "google_place_id": "",
        "google_location_type": "",
        "google_result_types": "",
        "google_lat": "",
        "google_lng": "",
        "google_country": "",
        "google_governorate_match": "NO",
        "google_place_match": "NO",
    }

    if api_status != "OK":
        decision = "REVIEW"
        status = "GOOGLE_NO_RESULT" if api_status == "ZERO_RESULTS" else "GOOGLE_ERROR"
        if api_status in {"OVER_QUERY_LIMIT", "REQUEST_DENIED", "INVALID_REQUEST"}:
            status = f"GOOGLE_{api_status}"
        return {**base, "google_decision": decision, "google_status": status, "google_reason": f"Google status={api_status}"}

    result = results[0]
    geometry = result.get("geometry", {}) or {}
    location = geometry.get("location", {}) or {}
    text = _result_text(result)
    country = _country_from_result(result)
    expected_gov = _norm_gov(row.get("approved_gouvernorat"))
    expected_terms = _expected_place_terms(row)
    result_govs = _governorates_from_result(result)
    governorate_match = expected_gov in result_govs or _contains_tokenized(text, expected_gov)
    place_match = any(_contains_tokenized(text, term) for term in expected_terms)
    country_ok = country in TUNISIA_NAMES if country else any(_contains_tokenized(text, name) for name in TUNISIA_NAMES)
    other_govs = sorted(gov for gov in result_govs if expected_gov and gov != expected_gov)

    output = {
        **base,
        "google_formatted_address": str(result.get("formatted_address", "")),
        "google_place_id": str(result.get("place_id", "")),
        "google_location_type": str(geometry.get("location_type", "")),
        "google_result_types": "|".join(str(item) for item in result.get("types", []) or []),
        "google_lat": str(location.get("lat", "")),
        "google_lng": str(location.get("lng", "")),
        "google_country": country,
        "google_governorate_match": "YES" if governorate_match else "NO",
        "google_place_match": "YES" if place_match else "NO",
    }

    if not country_ok:
        return {**output, "google_decision": "REVIEW", "google_status": "GOOGLE_CONFLICT", "google_reason": "Google result is not clearly in Tunisia"}
    if other_govs and not governorate_match:
        return {**output, "google_decision": "REVIEW", "google_status": "GOOGLE_CONFLICT", "google_reason": f"Google points to other governorate(s): {', '.join(other_govs)}"}
    if governorate_match and place_match and row.get("geo_audit_status") == "CORRECTION_CANDIDATE":
        return {**output, "google_decision": "AUTO_APPROVABLE", "google_status": "GOOGLE_CONFIRMED", "google_reason": "Google confirms Tunisia, expected governorate, and expected place term"}
    if governorate_match or place_match:
        return {**output, "google_decision": "REVIEW", "google_status": "GOOGLE_PARTIAL", "google_reason": "Google confirms only part of the expected geography"}
    return {**output, "google_decision": "REVIEW", "google_status": "GOOGLE_UNCONFIRMED", "google_reason": "Google result does not confirm expected governorate/place"}


def read_candidates(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        columns = list(reader.fieldnames or [])
    return rows, columns


def write_verified(path: Path, rows: Iterable[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = fieldnames + [col for col in GOOGLE_COLUMNS if col not in fieldnames]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def should_process(row: dict[str, str], include_ambiguous: bool) -> bool:
    status = row.get("geo_audit_status", "")
    if status == "CORRECTION_CANDIDATE":
        return True
    return include_ambiguous and status == "AMBIGUOUS_CANDIDATE"


def verify_candidates(
    rows: list[dict[str, str]],
    api_key: str | None,
    cache: dict[str, Any],
    language: str,
    limit: int | None,
    include_ambiguous: bool,
    sleep_seconds: float,
    timeout_seconds: int,
    offline: bool,
) -> list[dict[str, str]]:
    verified = []
    processed = 0
    for row in rows:
        if not should_process(row, include_ambiguous):
            verified.append({**row, "google_decision": "NOT_PROCESSED", "google_status": "SKIPPED", "google_reason": "candidate type not selected"})
            continue
        if limit is not None and processed >= limit:
            verified.append({**row, "google_decision": "NOT_PROCESSED", "google_status": "LIMIT_SKIPPED", "google_reason": f"limit={limit} reached"})
            continue

        query = build_google_query(row)
        if offline or not api_key:
            verified.append({**row, "google_decision": "REVIEW", "google_status": "GOOGLE_NOT_RUN", "google_reason": "offline mode or missing GOOGLE_MAPS_API_KEY", "google_query": query})
            processed += 1
            continue

        key = _cache_key(query, language)
        if key not in cache:
            try:
                cache[key] = geocode_google(query, api_key, language, timeout_seconds)
                time.sleep(max(sleep_seconds, 0.0))
            except Exception as exc:  # network/API errors stay in report, not as partial writes.
                cache[key] = {"status": "LOCAL_ERROR", "error_message": str(exc), "results": []}
        google_eval = evaluate_google_response(row, cache[key], query)
        if cache[key].get("status") == "LOCAL_ERROR":
            google_eval["google_reason"] = f"Local request error: {cache[key].get('error_message', '')}"
        verified.append({**row, **google_eval})
        processed += 1
    return verified


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify GEO rue/quartier candidates with Google Maps Geocoding.")
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--cache-json", type=Path, default=DEFAULT_CACHE_JSON)
    parser.add_argument("--api-key", default=os.environ.get("GOOGLE_MAPS_API_KEY"))
    parser.add_argument("--language", default="fr")
    parser.add_argument("--limit", type=int, default=None, help="Maximum selected rows to query.")
    parser.add_argument("--include-ambiguous", action="store_true", help="Also query AMBIGUOUS_CANDIDATE rows.")
    parser.add_argument("--offline", action="store_true", help="Write GOOGLE_NOT_RUN rows without calling Google.")
    parser.add_argument("--sleep-seconds", type=float, default=0.05)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    rows, columns = read_candidates(args.input_csv)
    cache = load_cache(args.cache_json)
    verified = verify_candidates(
        rows,
        args.api_key,
        cache,
        args.language,
        args.limit,
        args.include_ambiguous,
        args.sleep_seconds,
        args.timeout_seconds,
        args.offline,
    )
    if args.api_key and not args.offline:
        save_cache(args.cache_json, cache)
    write_verified(args.output_csv, verified, columns)

    counts: dict[str, int] = {}
    for row in verified:
        decision = row.get("google_decision", "UNKNOWN")
        counts[decision] = counts.get(decision, 0) + 1
    print("=" * 72)
    print(f"input rows          : {len(rows)}")
    print(f"output rows         : {len(verified)}")
    for decision, count in sorted(counts.items()):
        print(f"{decision:<20}: {count}")
    print(f"output              : {args.output_csv}")
    if args.api_key and not args.offline:
        print(f"cache               : {args.cache_json}")
    else:
        print("google api          : not called (missing key or offline mode)")
    print("=" * 72)


if __name__ == "__main__":
    main()
