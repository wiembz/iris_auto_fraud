"""
Verify DimRegion rue/quartier GEO candidates with OpenStreetMap Nominatim.

This script is non-destructive. It reads the PENDING candidates generated from
rue/quartier signals, calls the public Nominatim API only when --online is
provided, and writes a verification report. It never updates dim_geo, fact tables,
or approved correction files.

Important public Nominatim usage constraints:
  - keep requests single-threaded;
  - use a valid identifying User-Agent;
  - keep at or below 1 request/second;
  - cache results locally;
  - do not send confidential or personal data.

Examples:
  python etl/dwh/geo_audit_tools/audit_dim_geo_nominatim_candidates.py --limit 20
  python etl/dwh/geo_audit_tools/audit_dim_geo_nominatim_candidates.py --online --limit 50
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
        VALID_GOVERNORATS,
        normalize_gouvernorat,
        normalize_text,
    )
except ModuleNotFoundError:  # pytest/package import path
    from etl.dwh.geo_audit_tools.audit_dim_geo_excluded_rue_candidates import (
        VALID_GOVERNORATS,
        normalize_gouvernorat,
        normalize_text,
    )


BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_INPUT_CSV = BASE_DIR / "data" / "quality_reports" / "dim_geo" / "dim_geo_excluded_rue_review_candidates.csv"
DEFAULT_OUTPUT_CSV = BASE_DIR / "data" / "quality_reports" / "dim_geo" / "dim_geo_nominatim_verified_candidates.csv"
DEFAULT_CACHE_JSON = BASE_DIR / "data" / "quality_reports" / "dim_geo" / "dim_geo_nominatim_cache.json"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
TUNISIA_NAMES = {"TUNISIE", "TUNISIA", "TN"}
GOVERNORATE_SUFFIXES = (" GOUVERNORAT", " GOVERNORATE", " GOVERNORAT", " WILAYA")
GOVERNORATE_PREFIXES = ("GOUVERNORAT DE ", "GOUVERNORAT D'", "GOUVERNORAT ", "GOVERNORATE OF ")

NOMINATIM_COLUMNS = [
    "nominatim_decision",
    "nominatim_status",
    "nominatim_reason",
    "nominatim_query",
    "nominatim_result_count",
    "nominatim_display_name",
    "nominatim_place_id",
    "nominatim_osm_type",
    "nominatim_osm_id",
    "nominatim_class",
    "nominatim_type",
    "nominatim_importance",
    "nominatim_lat",
    "nominatim_lon",
    "nominatim_country_code",
    "nominatim_governorate_match",
    "nominatim_place_match",
    "nominatim_attribution",
]


class NominatimUsageError(ValueError):
    """Raised when the command would violate the intended safe usage profile."""


def _norm(value: object) -> str | None:
    return normalize_text(value)


def _norm_gov(value: object) -> str | None:
    value_norm = normalize_gouvernorat(value)
    if value_norm in VALID_GOVERNORATS:
        return value_norm
    return value_norm


def _strip_governorate_affixes(value: str | None) -> str | None:
    text = _norm(value)
    if not text:
        return None
    for prefix in GOVERNORATE_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
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


def build_nominatim_query(row: dict[str, str]) -> str:
    """Build a privacy-conscious query from reference candidates, not raw rue text."""
    terms = []
    for name in ("matched_reference_terms", "approved_localite", "approved_delegation", "approved_gouvernorat"):
        value = _field(row, name)
        if value and value.upper() != "UNKNOWN" and value not in terms:
            terms.append(value)
    terms.append("Tunisie")
    return ", ".join(terms)


def _cache_key(query: str, language: str, limit: int, base_url: str) -> str:
    raw = json.dumps(
        {"query": query, "language": language, "limit": limit, "countrycodes": "tn", "base_url": base_url},
        sort_keys=True,
    )
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


def geocode_nominatim(
    query: str,
    language: str,
    result_limit: int,
    timeout_seconds: int,
    base_url: str,
    user_agent: str,
    email: str | None,
) -> list[dict[str, Any]]:
    params = {
        "q": query,
        "format": "jsonv2",
        "addressdetails": "1",
        "limit": str(result_limit),
        "countrycodes": "tn",
        "accept-language": language,
    }
    if email:
        params["email"] = email
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept-Language": language,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = response.read().decode("utf-8")
    parsed = json.loads(payload)
    if not isinstance(parsed, list):
        return []
    return parsed


def _result_address(result: dict[str, Any]) -> dict[str, Any]:
    address = result.get("address", {}) or {}
    return address if isinstance(address, dict) else {}


def _result_text(result: dict[str, Any]) -> str:
    address = _result_address(result)
    values = [str(result.get("display_name", ""))]
    values.extend(str(value) for value in address.values())
    normalized = [_norm(value) for value in values]
    return " ".join(value for value in normalized if value)


def _country_code(result: dict[str, Any]) -> str:
    address = _result_address(result)
    return _norm(address.get("country_code")) or ""


def _country_text(result: dict[str, Any]) -> str:
    address = _result_address(result)
    return _norm(address.get("country")) or ""


def _governorates_from_result(result: dict[str, Any]) -> set[str]:
    address = _result_address(result)
    found = set()
    preferred_keys = (
        "state",
        "state_district",
        "county",
        "municipality",
        "city",
        "town",
        "village",
        "suburb",
        "quarter",
        "neighbourhood",
    )
    for key in preferred_keys:
        gov = _strip_governorate_affixes(address.get(key))
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


def _base_output(query: str, results: list[dict[str, Any]]) -> dict[str, str]:
    return {
        "nominatim_query": query,
        "nominatim_result_count": str(len(results)),
        "nominatim_display_name": "",
        "nominatim_place_id": "",
        "nominatim_osm_type": "",
        "nominatim_osm_id": "",
        "nominatim_class": "",
        "nominatim_type": "",
        "nominatim_importance": "",
        "nominatim_lat": "",
        "nominatim_lon": "",
        "nominatim_country_code": "",
        "nominatim_governorate_match": "NO",
        "nominatim_place_match": "NO",
        "nominatim_attribution": "OpenStreetMap contributors, ODbL",
    }


def _result_output(base: dict[str, str], result: dict[str, Any], governorate_match: bool, place_match: bool) -> dict[str, str]:
    return {
        **base,
        "nominatim_display_name": str(result.get("display_name", "")),
        "nominatim_place_id": str(result.get("place_id", "")),
        "nominatim_osm_type": str(result.get("osm_type", "")),
        "nominatim_osm_id": str(result.get("osm_id", "")),
        "nominatim_class": str(result.get("class", "")),
        "nominatim_type": str(result.get("type", "")),
        "nominatim_importance": str(result.get("importance", "")),
        "nominatim_lat": str(result.get("lat", "")),
        "nominatim_lon": str(result.get("lon", "")),
        "nominatim_country_code": _country_code(result),
        "nominatim_governorate_match": "YES" if governorate_match else "NO",
        "nominatim_place_match": "YES" if place_match else "NO",
    }


def evaluate_nominatim_response(row: dict[str, str], results: list[dict[str, Any]], query: str) -> dict[str, str]:
    base = _base_output(query, results)
    if not results:
        return {**base, "nominatim_decision": "REVIEW", "nominatim_status": "NOMINATIM_NO_RESULT", "nominatim_reason": "No result returned by Nominatim"}

    expected_gov = _norm_gov(row.get("approved_gouvernorat"))
    expected_terms = _expected_place_terms(row)
    partial_candidate: dict[str, str] | None = None
    unconfirmed_candidate: dict[str, str] | None = None

    for result in results:
        text = _result_text(result)
        country_code = _country_code(result)
        country_text = _country_text(result)
        if country_code and country_code != "TN":
            out = _result_output(base, result, False, False)
            return {**out, "nominatim_decision": "REVIEW", "nominatim_status": "NOMINATIM_CONFLICT", "nominatim_reason": f"Nominatim country_code={country_code}, expected TN"}

        country_ok = country_code == "TN" or country_text in TUNISIA_NAMES or any(_contains_tokenized(text, name) for name in TUNISIA_NAMES)
        result_govs = _governorates_from_result(result)
        governorate_match = expected_gov in result_govs or _contains_tokenized(text, expected_gov)
        place_match = any(_contains_tokenized(text, term) for term in expected_terms)
        output = _result_output(base, result, governorate_match, place_match)

        if not country_ok:
            unconfirmed_candidate = unconfirmed_candidate or {
                **output,
                "nominatim_decision": "REVIEW",
                "nominatim_status": "NOMINATIM_UNCONFIRMED",
                "nominatim_reason": "Nominatim result is not clearly in Tunisia",
            }
            continue

        if governorate_match and place_match and row.get("geo_audit_status") == "CORRECTION_CANDIDATE":
            return {
                **output,
                "nominatim_decision": "AUTO_APPROVABLE",
                "nominatim_status": "NOMINATIM_CONFIRMED",
                "nominatim_reason": "Nominatim confirms Tunisia, expected governorate, and expected place term",
            }
        if governorate_match or place_match:
            partial_candidate = partial_candidate or {
                **output,
                "nominatim_decision": "REVIEW",
                "nominatim_status": "NOMINATIM_PARTIAL",
                "nominatim_reason": "Nominatim confirms only part of the expected geography",
            }

    if partial_candidate:
        return partial_candidate
    if unconfirmed_candidate:
        return unconfirmed_candidate
    first = results[0]
    out = _result_output(base, first, False, False)
    return {**out, "nominatim_decision": "REVIEW", "nominatim_status": "NOMINATIM_UNCONFIRMED", "nominatim_reason": "Nominatim result does not confirm expected governorate/place"}


def read_candidates(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        columns = list(reader.fieldnames or [])
    return rows, columns


def write_verified(path: Path, rows: Iterable[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = fieldnames + [col for col in NOMINATIM_COLUMNS if col not in fieldnames]
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
    cache: dict[str, Any],
    language: str,
    limit: int | None,
    result_limit: int,
    include_ambiguous: bool,
    sleep_seconds: float,
    timeout_seconds: int,
    online: bool,
    base_url: str,
    user_agent: str,
    email: str | None,
) -> list[dict[str, str]]:
    verified = []
    processed = 0
    for row in rows:
        if not should_process(row, include_ambiguous):
            verified.append({**row, "nominatim_decision": "NOT_PROCESSED", "nominatim_status": "SKIPPED", "nominatim_reason": "candidate type not selected"})
            continue
        if limit is not None and processed >= limit:
            verified.append({**row, "nominatim_decision": "NOT_PROCESSED", "nominatim_status": "LIMIT_SKIPPED", "nominatim_reason": f"limit={limit} reached"})
            continue

        query = build_nominatim_query(row)
        if not online:
            verified.append({**row, "nominatim_decision": "REVIEW", "nominatim_status": "NOMINATIM_NOT_RUN", "nominatim_reason": "online mode not enabled", "nominatim_query": query})
            processed += 1
            continue

        key = _cache_key(query, language, result_limit, base_url)
        if key not in cache:
            try:
                cache[key] = geocode_nominatim(query, language, result_limit, timeout_seconds, base_url, user_agent, email)
                time.sleep(max(sleep_seconds, 1.0))
            except Exception as exc:  # network/API errors stay in report, not as partial writes.
                cache[key] = {"_local_error": str(exc), "_results": []}
        cached = cache[key]
        if isinstance(cached, dict) and "_local_error" in cached:
            nominatim_eval = evaluate_nominatim_response(row, [], query)
            nominatim_eval["nominatim_status"] = "NOMINATIM_LOCAL_ERROR"
            nominatim_eval["nominatim_reason"] = f"Local request error: {cached.get('_local_error', '')}"
        else:
            nominatim_eval = evaluate_nominatim_response(row, cached if isinstance(cached, list) else [], query)
        verified.append({**row, **nominatim_eval})
        processed += 1
    return verified


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify GEO rue/quartier candidates with OpenStreetMap Nominatim.")
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--cache-json", type=Path, default=DEFAULT_CACHE_JSON)
    parser.add_argument("--online", action="store_true", help="Call public Nominatim. Without this flag, no network call is made.")
    parser.add_argument("--language", default="fr")
    parser.add_argument("--limit", type=int, default=50, help="Maximum selected rows to query or prepare. Default keeps batches small.")
    parser.add_argument("--result-limit", type=int, default=5, help="Maximum Nominatim results per query.")
    parser.add_argument("--include-ambiguous", action="store_true", help="Also query AMBIGUOUS_CANDIDATE rows.")
    parser.add_argument("--sleep-seconds", type=float, default=1.1, help="Delay between uncached online requests. Public Nominatim requires <= 1 request/second.")
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--base-url", default=NOMINATIM_SEARCH_URL)
    parser.add_argument("--user-agent", default=os.environ.get("NOMINATIM_USER_AGENT", "IRIS-AUTO-FRAUD-GEO-AUDIT/1.0"))
    parser.add_argument("--email", default=os.environ.get("NOMINATIM_EMAIL"))
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    if args.online and args.base_url == NOMINATIM_SEARCH_URL and args.sleep_seconds < 1.0:
        raise NominatimUsageError("Public Nominatim requires at most 1 request/second; use --sleep-seconds >= 1.0.")
    if args.result_limit < 1 or args.result_limit > 40:
        raise NominatimUsageError("--result-limit must be between 1 and 40.")

    rows, columns = read_candidates(args.input_csv)
    cache = load_cache(args.cache_json)
    verified = verify_candidates(
        rows,
        cache,
        args.language,
        args.limit,
        args.result_limit,
        args.include_ambiguous,
        args.sleep_seconds,
        args.timeout_seconds,
        args.online,
        args.base_url,
        args.user_agent,
        args.email,
    )
    if args.online:
        save_cache(args.cache_json, cache)
    write_verified(args.output_csv, verified, columns)

    counts: dict[str, int] = {}
    for row in verified:
        decision = row.get("nominatim_decision", "UNKNOWN")
        counts[decision] = counts.get(decision, 0) + 1
    print("=" * 72)
    print(f"input rows          : {len(rows)}")
    print(f"output rows         : {len(verified)}")
    for decision, count in sorted(counts.items()):
        print(f"{decision:<20}: {count}")
    print(f"output              : {args.output_csv}")
    if args.online:
        print(f"cache               : {args.cache_json}")
        print("provider            : OpenStreetMap Nominatim")
    else:
        print("nominatim api       : not called (use --online for real verification)")
    print("=" * 72)


if __name__ == "__main__":
    main()
