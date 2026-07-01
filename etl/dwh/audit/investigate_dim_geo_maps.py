"""
etl/dwh/audit/investigate_dim_geo_maps.py
=========================================
Investigate risky dwh.dim_geo geography rows with administrative reference
checks, postal-code signals, and optional OpenStreetMap/Nominatim geocoding.

This script never updates dwh.dim_geo. It writes map-investigation reports
that can be reviewed before approved corrections are added to:
  data/reference/dim_geo/geo_dim_approved_corrections.csv

Default behavior is offline: reference + postal checks only. Add
--use-geocoder plus --confirm-public-geocoder-risk to query Nominatim with
local caching and rate limiting.

Usage:
  python etl/dwh/audit/investigate_dim_geo_maps.py
  python etl/dwh/audit/investigate_dim_geo_maps.py --use-geocoder --confirm-public-geocoder-risk --max-geocode-queries 50
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[3]
QUALITY_DIR = BASE_DIR / "data" / "quality_reports" / "dim_geo"
REVIEW_DIR = QUALITY_DIR / "review"
OUTPUT_DIR = QUALITY_DIR / "map_investigation"
REFERENCE_CSV = BASE_DIR / "data" / "reference" / "dim_geo" / "geo_tunisia_reference.csv"
APPROVED_CORRECTIONS_CSV = BASE_DIR / "data" / "reference" / "dim_geo" / "geo_dim_approved_corrections.csv"
GEOCODING_CACHE_CSV = BASE_DIR / "data" / "reference" / "dim_geo" / "geocoding_cache.csv"

OUTPUT_ALL = OUTPUT_DIR / "dim_geo_map_investigation_all.csv"
OUTPUT_VALIDATED = OUTPUT_DIR / "dim_geo_map_validated.csv"
OUTPUT_CANDIDATES = OUTPUT_DIR / "dim_geo_map_correction_candidates.csv"
OUTPUT_CONFLICTS = OUTPUT_DIR / "dim_geo_map_conflicts_confirmed.csv"
OUTPUT_UNRESOLVED = OUTPUT_DIR / "dim_geo_map_unresolved.csv"
OUTPUT_SEARCH_LOG = OUTPUT_DIR / "dim_geo_map_search_log.csv"

UNKNOWN = "UNKNOWN"

STATUS_VALIDATED = "MAP_VALIDATED_REFERENCE"
STATUS_CANDIDATE = "MAP_CORRECTION_CANDIDATE"
STATUS_CONFLICT = "MAP_CONFIRMED_CONFLICT"
STATUS_AMBIGUOUS = "MAP_AMBIGUOUS_MULTIPLE_MATCHES"
STATUS_NOT_FOUND = "MAP_NOT_FOUND"
STATUS_MANUAL = "MAP_MANUAL_REVIEW"

REC_APPROVE = "MAP_RECOMMEND_APPROVE"
REC_KEEP_SOURCE = "MAP_RECOMMEND_KEEP_SOURCE"
REC_REJECT = "MAP_RECOMMEND_REJECT"
REC_MANUAL = "MAP_RECOMMEND_MANUAL_REVIEW"

OUTPUT_COLUMNS = [
    "geo_sk",
    "geo_key",
    "source_region",
    "source_gouvernorat",
    "source_localite",
    "source_code_postal",
    "current_audit_status",
    "current_audit_reason",
    "current_confidence_score",
    "map_search_query",
    "map_source",
    "map_found_name",
    "map_found_display_name",
    "map_found_type",
    "map_found_lat",
    "map_found_lon",
    "map_found_gouvernorat",
    "map_found_delegation",
    "map_found_code_postal",
    "candidate_region",
    "candidate_gouvernorat",
    "candidate_delegation",
    "candidate_localite",
    "candidate_code_postal",
    "map_investigation_status",
    "map_investigation_reason",
    "confidence_score_map",
    "recommendation",
    "reviewer_comment",
]

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


@dataclass(frozen=True)
class ReferencePlace:
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
    terms_norm: tuple[str, ...]


@dataclass(frozen=True)
class MapPlace:
    query: str
    source: str
    name: str
    display_name: str
    osm_class: str
    osm_type: str
    lat: str
    lon: str
    gouvernorat: str
    delegation: str
    code_postal: str
    result_count: int
    multiple_governorates: bool


def normalize_text(raw) -> str | None:
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
    s = re.sub(r"\bGOVERNORATE\b", "", s).strip()
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


def output_value(value: str | None) -> str:
    return value if value else UNKNOWN


def confidence_to_float(raw) -> float:
    s = normalize_text(raw)
    if s is None or s == "HIGH":
        return 1.0
    if s == "MEDIUM":
        return 0.8
    if s == "LOW":
        return 0.6
    try:
        value = float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return 1.0
    if value > 1:
        value = value / 100
    return max(0.0, min(1.0, value))


def split_aliases(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, float) and math.isnan(raw):
        return []
    aliases: list[str] = []
    for part in re.split(r"[|;]", str(raw)):
        value = normalize_text(part)
        if value and value not in aliases:
            aliases.append(value)
    return aliases


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


def first_existing(row: pd.Series, names: list[str]) -> str:
    for name in names:
        if name in row:
            value = row.get(name)
            if value is not None and not (isinstance(value, float) and math.isnan(value)):
                text = str(value).strip()
                if text:
                    return text
    return ""


def find_latest_manual_review_file() -> Path:
    exact = [
        QUALITY_DIR / "dim_geo_manual_review_remaining.csv",
        REVIEW_DIR / "dim_geo_manual_review_remaining.csv",
    ]
    for path in exact:
        if path.exists():
            return path

    candidates = list(QUALITY_DIR.glob("**/dim_geo_manual_review_remaining*.csv"))
    if candidates:
        return max(candidates, key=lambda p: p.stat().st_mtime)

    fallback = QUALITY_DIR / "dim_geo_manual_review.csv"
    if fallback.exists():
        return fallback
    raise FileNotFoundError("No manual-review input file found under data/quality_reports/dim_geo.")


def read_review_input(path: Path, source_name: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df = standardize_columns(df)
    rows = []
    for _, row in df.iterrows():
        rows.append(
            {
                "geo_sk": first_existing(row, ["geo_sk"]),
                "geo_key": first_existing(row, ["geo_key"]),
                "source_region": first_existing(row, ["current_region", "region", "source_region_norm"]),
                "source_gouvernorat": first_existing(row, ["current_gouvernorat", "gouvernorat", "source_gouvernorat_norm"]),
                "source_localite": first_existing(row, ["current_localite", "localite", "source_localite_norm"]),
                "source_code_postal": first_existing(row, ["current_code_postal", "code_postal", "source_code_postal_norm"]),
                "current_audit_status": first_existing(row, ["geo_audit_status", "current_audit_status"]),
                "current_audit_reason": first_existing(row, ["geo_audit_reason", "current_audit_reason"]),
                "current_confidence_score": first_existing(row, ["confidence_score", "current_confidence_score"]),
                "candidate_region": first_existing(row, ["candidate_region"]),
                "candidate_gouvernorat": first_existing(row, ["candidate_gouvernorat"]),
                "candidate_delegation": first_existing(row, ["candidate_delegation"]),
                "candidate_localite": first_existing(row, ["candidate_localite"]),
                "candidate_code_postal": first_existing(row, ["candidate_code_postal"]),
                "_input_source": source_name,
            }
        )
    return pd.DataFrame(rows)


def load_investigation_inputs(args: argparse.Namespace) -> tuple[pd.DataFrame, Path, Path]:
    manual_path = args.manual_review_csv or find_latest_manual_review_file()
    conflicts_path = args.conflicts_csv or (QUALITY_DIR / "dim_geo_conflicts.csv")

    manual_df = read_review_input(manual_path, "manual_review")
    conflicts_df = read_review_input(conflicts_path, "conflicts")
    df = pd.concat([manual_df, conflicts_df], ignore_index=True)
    df = df.drop_duplicates(subset=["geo_key"], keep="first").reset_index(drop=True)

    if args.max_rows and args.max_rows > 0:
        df = df.head(args.max_rows).copy()
    return df, manual_path, conflicts_path


def load_approved_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df = standardize_columns(df)
    if "geo_key" not in df.columns:
        return set()
    if "approval_status" in df.columns:
        df = df[df["approval_status"].str.upper().eq("APPROVED")]
    return {str(v).strip().upper() for v in df["geo_key"] if str(v).strip()}


def load_reference(path: Path) -> list[ReferencePlace]:
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df = standardize_columns(df)
    required = {"localite", "delegation", "gouvernorat", "region", "code_postal", "aliases", "confidence"}
    missing = sorted(required.difference(df.columns))
    if missing:
        raise RuntimeError(f"Reference file {path} missing columns: {missing}")

    rows: list[ReferencePlace] = []
    for idx, row in df.iterrows():
        localite = normalize_text(row.get("localite"))
        delegation = normalize_text(row.get("delegation"))
        gouvernorat = normalize_gouvernorat(row.get("gouvernorat"))
        region = normalize_text(row.get("region"))
        code_postal = normalize_code_postal(row.get("code_postal"))
        if gouvernorat not in VALID_GOVERNORATS or (not localite and not delegation):
            continue
        terms = []
        for term in [localite, delegation, *split_aliases(row.get("aliases"))]:
            if term and term not in terms:
                terms.append(term)
        rows.append(
            ReferencePlace(
                ref_id=int(idx),
                localite=output_value(localite),
                delegation=output_value(delegation),
                gouvernorat=gouvernorat,
                region=output_value(region),
                code_postal=output_value(code_postal),
                confidence=confidence_to_float(row.get("confidence")),
                localite_norm=output_value(localite),
                delegation_norm=output_value(delegation),
                gouvernorat_norm=gouvernorat,
                region_norm=output_value(region),
                code_postal_norm=output_value(code_postal),
                terms_norm=tuple(terms),
            )
        )
    return rows


def build_reference_indexes(ref_rows: list[ReferencePlace]) -> tuple[dict[str, list[ReferencePlace]], dict[str, str]]:
    term_index: dict[str, list[ReferencePlace]] = defaultdict(list)
    prefix_to_governorates: dict[str, set[str]] = defaultdict(set)
    for ref in ref_rows:
        for term in ref.terms_norm:
            term_index[term].append(ref)
        if ref.code_postal_norm != UNKNOWN and len(ref.code_postal_norm) == 4:
            prefix_to_governorates[ref.code_postal_norm[:2]].add(ref.gouvernorat_norm)
    postal_prefix_index = {
        prefix: next(iter(govs))
        for prefix, govs in prefix_to_governorates.items()
        if len(govs) == 1
    }
    return term_index, postal_prefix_index


def ref_output_key(ref: ReferencePlace) -> tuple[str, str, str, str, str]:
    return (ref.region, ref.gouvernorat, ref.delegation, ref.localite, ref.code_postal)


def unique_reference_candidates(candidates: list[ReferencePlace]) -> list[ReferencePlace]:
    unique: dict[tuple[str, str, str, str, str], ReferencePlace] = {}
    for ref in candidates:
        unique[ref_output_key(ref)] = ref
    return list(unique.values())


def source_values(row: pd.Series) -> dict[str, str | None]:
    return {
        "region": normalize_text(row.get("source_region")),
        "gouvernorat": normalize_gouvernorat(row.get("source_gouvernorat")),
        "localite": normalize_text(row.get("source_localite")),
        "code_postal": normalize_code_postal(row.get("source_code_postal")),
    }


def reference_match_for_row(row: pd.Series, term_index: dict[str, list[ReferencePlace]]) -> tuple[list[ReferencePlace], str]:
    source = source_values(row)
    for field in ["localite", "region"]:
        term = source[field]
        if term and term in term_index:
            return unique_reference_candidates(term_index[term]), field
    return [], ""


def postal_governorate_signal(code_postal: str | None, postal_prefix_index: dict[str, str]) -> str | None:
    if not code_postal or len(code_postal) != 4:
        return None
    return postal_prefix_index.get(code_postal[:2])


def build_search_queries(row: pd.Series) -> list[str]:
    source = {
        "region": output_value(normalize_text(row.get("source_region"))),
        "gouvernorat": output_value(normalize_gouvernorat(row.get("source_gouvernorat"))),
        "localite": output_value(normalize_text(row.get("source_localite"))),
    }
    queries = []
    localite = source["localite"]
    gouvernorat = source["gouvernorat"]
    region = source["region"]
    if localite != UNKNOWN and gouvernorat != UNKNOWN:
        queries.append(f"{localite}, {gouvernorat}, Tunisia")
    if localite != UNKNOWN:
        queries.append(f"{localite}, Tunisia")
        queries.append(f"{localite} delegation Tunisia")
    if region != UNKNOWN and gouvernorat != UNKNOWN:
        queries.append(f"{region}, {gouvernorat}, Tunisia")
    if region != UNKNOWN:
        queries.append(f"{region}, Tunisia")

    deduped = []
    for query in queries:
        query_norm = normalize_text(query)
        if query_norm and query not in deduped:
            deduped.append(query)
    return deduped


class GeocodingCache:
    def __init__(self, path: Path):
        self.path = path
        self.rows: dict[str, dict] = {}
        if path.exists():
            df = pd.read_csv(path, dtype=str, keep_default_na=False)
            df = standardize_columns(df)
            for _, row in df.iterrows():
                query_norm = str(row.get("query_norm", "")).strip()
                if query_norm:
                    self.rows[query_norm] = row.to_dict()

    def get(self, query: str) -> dict | None:
        return self.rows.get(output_value(normalize_text(query)))

    def put(self, query: str, payload: list[dict], status_code: str, error: str = "") -> None:
        now = datetime.now(timezone.utc).isoformat()
        query_norm = output_value(normalize_text(query))
        row = {
            "query": query,
            "query_norm": query_norm,
            "fetched_at": now,
            "source": "NOMINATIM",
            "status_code": status_code,
            "error": error,
            "result_count": str(len(payload)),
            "raw_json": json.dumps(payload, ensure_ascii=False),
        }
        self.rows[query_norm] = row

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        columns = [
            "query",
            "query_norm",
            "fetched_at",
            "source",
            "status_code",
            "error",
            "result_count",
            "raw_json",
        ]
        pd.DataFrame(list(self.rows.values()), columns=columns).to_csv(
            self.path, index=False, encoding="utf-8-sig"
        )


def parse_cached_payload(row: dict) -> list[dict]:
    raw_json = row.get("raw_json", "")
    if not raw_json:
        return []
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def fetch_nominatim(query: str, args: argparse.Namespace) -> tuple[list[dict], str, str]:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": args.nominatim_limit,
            "countrycodes": "tn",
            "accept-language": "en",
        }
    )
    url = f"https://nominatim.openstreetmap.org/search?{params}"
    user_agent = args.user_agent
    if args.email:
        user_agent = f"{user_agent} ({args.email})"
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(request, timeout=args.timeout_seconds) as response:
            status = str(response.status)
            payload = json.loads(response.read().decode("utf-8"))
            return (payload if isinstance(payload, list) else [], status, "")
    except urllib.error.HTTPError as exc:
        return [], str(exc.code), str(exc)
    except Exception as exc:  # noqa: BLE001 - report geocoding failures in CSV
        return [], "ERROR", str(exc)


def normalize_map_governorate(raw) -> str | None:
    s = normalize_text(raw)
    if s is None:
        return None
    s = re.sub(r"\bGOVERNORATE\b", "", s).strip()
    s = re.sub(r"\bGOUVERNORAT\b", "", s).strip()
    s = re.sub(r"\bGOVERNORAT\b", "", s).strip()
    s = re.sub(r"\s+", " ", s).strip()
    return normalize_gouvernorat(s)


def map_result_to_place(query: str, payload: list[dict]) -> MapPlace | None:
    if not payload:
        return None
    places: list[MapPlace] = []
    governors = set()
    for item in payload:
        address = item.get("address") or {}
        gov = (
            normalize_map_governorate(address.get("state"))
            or normalize_map_governorate(address.get("province"))
            or normalize_map_governorate(address.get("region"))
        )
        delegation = (
            normalize_text(address.get("county"))
            or normalize_text(address.get("municipality"))
            or normalize_text(address.get("city"))
            or normalize_text(address.get("town"))
            or normalize_text(address.get("village"))
        )
        code_postal = normalize_code_postal(address.get("postcode"))
        if gov in VALID_GOVERNORATS:
            governors.add(gov)
        name = item.get("name") or address.get("city") or address.get("town") or address.get("village") or ""
        places.append(
            MapPlace(
                query=query,
                source="NOMINATIM",
                name=output_value(normalize_text(name)),
                display_name=str(item.get("display_name", "")),
                osm_class=str(item.get("class", "")),
                osm_type=str(item.get("type", "")),
                lat=str(item.get("lat", "")),
                lon=str(item.get("lon", "")),
                gouvernorat=output_value(gov),
                delegation=output_value(delegation),
                code_postal=output_value(code_postal),
                result_count=len(payload),
                multiple_governorates=len(governors) > 1,
            )
        )
    return places[0] if places else None


def run_geocoding(
    row: pd.Series,
    args: argparse.Namespace,
    cache: GeocodingCache,
    counters: Counter,
    search_log: list[dict],
) -> MapPlace | None:
    for query in build_search_queries(row):
        query_norm = output_value(normalize_text(query))
        cached = cache.get(query)
        if cached is not None:
            counters["cache_hits"] += 1
            payload = parse_cached_payload(cached)
            place = map_result_to_place(query, payload)
            search_log.append(
                {
                    "geo_sk": row.get("geo_sk", ""),
                    "geo_key": row.get("geo_key", ""),
                    "query": query,
                    "query_norm": query_norm,
                    "cache_hit": "YES",
                    "executed": "NO",
                    "result_count": str(len(payload)),
                    "status": cached.get("status_code", ""),
                    "message": cached.get("error", ""),
                }
            )
            if place is not None:
                return place
            continue

        if not args.use_geocoder:
            search_log.append(
                {
                    "geo_sk": row.get("geo_sk", ""),
                    "geo_key": row.get("geo_key", ""),
                    "query": query,
                    "query_norm": query_norm,
                    "cache_hit": "NO",
                    "executed": "NO",
                    "result_count": "0",
                    "status": "GEOCODER_DISABLED",
                    "message": "run with --use-geocoder to query Nominatim",
                }
            )
            continue

        if counters["map_queries_executed"] >= args.max_geocode_queries:
            search_log.append(
                {
                    "geo_sk": row.get("geo_sk", ""),
                    "geo_key": row.get("geo_key", ""),
                    "query": query,
                    "query_norm": query_norm,
                    "cache_hit": "NO",
                    "executed": "NO",
                    "result_count": "0",
                    "status": "QUERY_LIMIT_REACHED",
                    "message": f"max_geocode_queries={args.max_geocode_queries}",
                }
            )
            continue

        counters["cache_misses"] += 1
        payload, status_code, error = fetch_nominatim(query, args)
        counters["map_queries_executed"] += 1
        cache.put(query, payload, status_code, error)
        search_log.append(
            {
                "geo_sk": row.get("geo_sk", ""),
                "geo_key": row.get("geo_key", ""),
                "query": query,
                "query_norm": query_norm,
                "cache_hit": "NO",
                "executed": "YES",
                "result_count": str(len(payload)),
                "status": status_code,
                "message": error,
            }
        )
        if args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)
        place = map_result_to_place(query, payload)
        if place is not None:
            return place
    return None


def blank_map_fields() -> dict:
    return {
        "map_search_query": "",
        "map_source": "",
        "map_found_name": UNKNOWN,
        "map_found_display_name": "",
        "map_found_type": UNKNOWN,
        "map_found_lat": "",
        "map_found_lon": "",
        "map_found_gouvernorat": UNKNOWN,
        "map_found_delegation": UNKNOWN,
        "map_found_code_postal": UNKNOWN,
    }


def place_map_fields(place: MapPlace | None) -> dict:
    if place is None:
        return blank_map_fields()
    return {
        "map_search_query": place.query,
        "map_source": place.source,
        "map_found_name": place.name,
        "map_found_display_name": place.display_name,
        "map_found_type": place.osm_type or place.osm_class or UNKNOWN,
        "map_found_lat": place.lat,
        "map_found_lon": place.lon,
        "map_found_gouvernorat": place.gouvernorat,
        "map_found_delegation": place.delegation,
        "map_found_code_postal": place.code_postal,
    }


def candidate_from_ref(ref: ReferencePlace) -> dict:
    return {
        "candidate_region": ref.region,
        "candidate_gouvernorat": ref.gouvernorat,
        "candidate_delegation": ref.delegation,
        "candidate_localite": ref.localite,
        "candidate_code_postal": ref.code_postal,
    }


def candidate_from_map(place: MapPlace) -> dict:
    return {
        "candidate_region": UNKNOWN,
        "candidate_gouvernorat": place.gouvernorat,
        "candidate_delegation": place.delegation,
        "candidate_localite": place.name,
        "candidate_code_postal": place.code_postal,
    }


def empty_candidate() -> dict:
    return {
        "candidate_region": UNKNOWN,
        "candidate_gouvernorat": UNKNOWN,
        "candidate_delegation": UNKNOWN,
        "candidate_localite": UNKNOWN,
        "candidate_code_postal": UNKNOWN,
    }


def base_output(row: pd.Series) -> dict:
    return {
        "geo_sk": row.get("geo_sk", ""),
        "geo_key": row.get("geo_key", ""),
        "source_region": output_value(normalize_text(row.get("source_region"))),
        "source_gouvernorat": output_value(normalize_gouvernorat(row.get("source_gouvernorat"))),
        "source_localite": output_value(normalize_text(row.get("source_localite"))),
        "source_code_postal": output_value(normalize_code_postal(row.get("source_code_postal"))),
        "current_audit_status": row.get("current_audit_status", ""),
        "current_audit_reason": row.get("current_audit_reason", ""),
        "current_confidence_score": row.get("current_confidence_score", ""),
        "reviewer_comment": "",
    }


def finalize_decision(
    row: pd.Series,
    ref_candidates: list[ReferencePlace],
    ref_source_field: str,
    postal_gov: str | None,
    map_place: MapPlace | None,
) -> dict:
    source = source_values(row)
    source_gov = source["gouvernorat"]
    source_gov_valid = source_gov in VALID_GOVERNORATS

    result = base_output(row)
    result.update(place_map_fields(map_place))

    if ref_candidates:
        same_gov = [ref for ref in ref_candidates if ref.gouvernorat_norm == source_gov]
        distinct_govs = {ref.gouvernorat_norm for ref in ref_candidates}
        if len(distinct_govs) > 1 and not same_gov:
            result.update(empty_candidate())
            result.update(
                {
                    "map_investigation_status": STATUS_AMBIGUOUS,
                    "map_investigation_reason": "reference has multiple plausible governorates for the source term",
                    "confidence_score_map": 0.7,
                    "recommendation": REC_MANUAL,
                }
            )
            return result

        chosen = same_gov[0] if same_gov else ref_candidates[0]
        result.update(candidate_from_ref(chosen))
        if source_gov_valid and chosen.gouvernorat_norm != source_gov:
            score = 0.95 if ref_source_field == "localite" else 0.88
            if postal_gov and postal_gov != chosen.gouvernorat_norm:
                score = min(score, 0.78)
            result.update(
                {
                    "map_investigation_status": STATUS_CONFLICT,
                    "map_investigation_reason": (
                        f"source governorate {source_gov} conflicts with reference "
                        f"{chosen.gouvernorat_norm} for {ref_source_field}"
                    ),
                    "confidence_score_map": round(score * chosen.confidence, 4),
                    "recommendation": REC_APPROVE if score >= 0.85 else REC_MANUAL,
                }
            )
            return result

        if source_gov_valid and chosen.gouvernorat_norm == source_gov:
            result.update(
                {
                    "map_investigation_status": STATUS_VALIDATED,
                    "map_investigation_reason": f"source governorate agrees with administrative reference via {ref_source_field}",
                    "confidence_score_map": round(0.95 * chosen.confidence, 4),
                    "recommendation": REC_KEEP_SOURCE,
                }
            )
            return result

        result.update(
            {
                "map_investigation_status": STATUS_CANDIDATE,
                "map_investigation_reason": f"administrative reference proposes a governorate via {ref_source_field}",
                "confidence_score_map": round(0.9 * chosen.confidence, 4),
                "recommendation": REC_APPROVE,
            }
        )
        return result

    if map_place is not None:
        result.update(candidate_from_map(map_place))
        map_gov = normalize_gouvernorat(map_place.gouvernorat)
        if map_place.multiple_governorates:
            result.update(
                {
                    "map_investigation_status": STATUS_AMBIGUOUS,
                    "map_investigation_reason": "map search returned plausible places in multiple governorates",
                    "confidence_score_map": 0.7,
                    "recommendation": REC_MANUAL,
                }
            )
            return result
        if map_gov in VALID_GOVERNORATS:
            score = 0.88
            if postal_gov and postal_gov != map_gov:
                score = 0.72
            if source_gov_valid and map_gov != source_gov:
                result.update(
                    {
                        "map_investigation_status": STATUS_CONFLICT,
                        "map_investigation_reason": f"map result suggests {map_gov}, source governorate is {source_gov}",
                        "confidence_score_map": score,
                        "recommendation": REC_APPROVE if score >= 0.85 else REC_MANUAL,
                    }
                )
                return result
            if source_gov_valid and map_gov == source_gov:
                result.update(
                    {
                        "map_investigation_status": STATUS_VALIDATED,
                        "map_investigation_reason": "map result agrees with source governorate",
                        "confidence_score_map": score,
                        "recommendation": REC_KEEP_SOURCE,
                    }
                )
                return result
            result.update(
                {
                    "map_investigation_status": STATUS_CANDIDATE,
                    "map_investigation_reason": "map result proposes a governorate for an unconfirmed source governorate",
                    "confidence_score_map": score,
                    "recommendation": REC_APPROVE if score >= 0.85 else REC_MANUAL,
                }
            )
            return result

    result.update(empty_candidate())
    if build_search_queries(row):
        status = STATUS_NOT_FOUND if map_place is None and result["map_source"] == "NOMINATIM" else STATUS_MANUAL
        reason = "no administrative reference match and no safe map confirmation"
    else:
        status = STATUS_MANUAL
        reason = "insufficient searchable geography signal"
    result.update(
        {
            "map_investigation_status": status,
            "map_investigation_reason": reason,
            "confidence_score_map": 0.0,
            "recommendation": REC_MANUAL,
        }
    )
    return result


def investigate(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, Counter, Path, Path]:
    df_input, manual_path, conflicts_path = load_investigation_inputs(args)

    if not args.include_approved:
        approved_keys = load_approved_keys(args.approved_corrections_csv)
        if approved_keys:
            df_input = df_input[~df_input["geo_key"].str.upper().isin(approved_keys)].copy()

    ref_rows = load_reference(args.reference_csv)
    term_index, postal_prefix_index = build_reference_indexes(ref_rows)
    cache = GeocodingCache(args.geocoding_cache_csv)
    counters: Counter = Counter()
    search_log: list[dict] = []
    output_rows = []

    for _, row in df_input.iterrows():
        ref_candidates, ref_source_field = reference_match_for_row(row, term_index)
        source = source_values(row)
        postal_gov = postal_governorate_signal(source["code_postal"], postal_prefix_index)

        needs_map = not ref_candidates or args.map_confirm_conflicts
        map_place = run_geocoding(row, args, cache, counters, search_log) if needs_map else None
        output_rows.append(finalize_decision(row, ref_candidates, ref_source_field, postal_gov, map_place))

    cache.write()
    df_output = pd.DataFrame(output_rows, columns=OUTPUT_COLUMNS)
    df_log = pd.DataFrame(search_log)
    counters["rows_investigated"] = len(df_output)
    return df_output, df_log, counters, manual_path, conflicts_path


def write_reports(df: pd.DataFrame, df_log: pd.DataFrame) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_ALL, index=False, encoding="utf-8-sig")
    df[df["map_investigation_status"] == STATUS_VALIDATED].to_csv(
        OUTPUT_VALIDATED, index=False, encoding="utf-8-sig"
    )
    df[df["map_investigation_status"] == STATUS_CANDIDATE].to_csv(
        OUTPUT_CANDIDATES, index=False, encoding="utf-8-sig"
    )
    df[df["map_investigation_status"] == STATUS_CONFLICT].to_csv(
        OUTPUT_CONFLICTS, index=False, encoding="utf-8-sig"
    )
    df[df["map_investigation_status"].isin([STATUS_AMBIGUOUS, STATUS_NOT_FOUND, STATUS_MANUAL])].to_csv(
        OUTPUT_UNRESOLVED, index=False, encoding="utf-8-sig"
    )
    df_log.to_csv(OUTPUT_SEARCH_LOG, index=False, encoding="utf-8-sig")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Investigate dim_geo risky rows with reference and optional map checks.")
    parser.add_argument("--manual-review-csv", type=Path, default=None)
    parser.add_argument("--conflicts-csv", type=Path, default=None)
    parser.add_argument("--reference-csv", type=Path, default=REFERENCE_CSV)
    parser.add_argument("--approved-corrections-csv", type=Path, default=APPROVED_CORRECTIONS_CSV)
    parser.add_argument("--geocoding-cache-csv", type=Path, default=GEOCODING_CACHE_CSV)
    parser.add_argument("--include-approved", action="store_true")
    parser.add_argument("--map-confirm-conflicts", action="store_true")
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--use-geocoder", action="store_true")
    parser.add_argument(
        "--confirm-public-geocoder-risk",
        action="store_true",
        help="Required with --use-geocoder because source geography is sent to a public service.",
    )
    parser.add_argument("--max-geocode-queries", type=int, default=50)
    parser.add_argument("--sleep-seconds", type=float, default=1.1)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--nominatim-limit", type=int, default=5)
    parser.add_argument("--email", default="")
    parser.add_argument(
        "--user-agent",
        default="IRIS_AUTO_FRAUD_dim_geo_investigation/1.0",
    )
    return parser


def print_summary(df: pd.DataFrame, counters: Counter, manual_path: Path, conflicts_path: Path) -> None:
    status_counts = df["map_investigation_status"].value_counts()
    rec_counts = df["recommendation"].value_counts()
    print("=" * 72)
    print(f"manual review input       : {manual_path}")
    print(f"conflicts input           : {conflicts_path}")
    print(f"rows investigated         : {counters['rows_investigated']}")
    print(f"map queries executed      : {counters['map_queries_executed']}")
    print(f"cache hits                : {counters['cache_hits']}")
    print(f"cache misses              : {counters['cache_misses']}")
    print("-" * 72)
    for status in [
        STATUS_VALIDATED,
        STATUS_CANDIDATE,
        STATUS_CONFLICT,
        STATUS_AMBIGUOUS,
        STATUS_NOT_FOUND,
        STATUS_MANUAL,
    ]:
        print(f"{status:<34} {int(status_counts.get(status, 0))}")
    print("-" * 72)
    print("recommendations")
    for rec, count in rec_counts.items():
        print(f"{rec:<34} {int(count)}")
    print("-" * 72)
    print(f"all rows                  : {OUTPUT_ALL}")
    print(f"validated                 : {OUTPUT_VALIDATED}")
    print(f"correction candidates     : {OUTPUT_CANDIDATES}")
    print(f"confirmed conflicts       : {OUTPUT_CONFLICTS}")
    print(f"unresolved                : {OUTPUT_UNRESOLVED}")
    print(f"search log                : {OUTPUT_SEARCH_LOG}")
    print(f"geocoding cache           : {GEOCODING_CACHE_CSV}")
    print("=" * 72)


def main() -> None:
    args = build_arg_parser().parse_args()
    if args.nominatim_limit < 1:
        raise ValueError("--nominatim-limit must be >= 1")
    if args.use_geocoder and not args.confirm_public_geocoder_risk:
        raise RuntimeError(
            "--use-geocoder sends claim-derived geography strings to the public "
            "Nominatim service. Re-run with --confirm-public-geocoder-risk only "
            "after explicit project approval, or keep the default offline mode."
        )
    df, df_log, counters, manual_path, conflicts_path = investigate(args)
    write_reports(df, df_log)
    print_summary(df, counters, manual_path, conflicts_path)


if __name__ == "__main__":
    main()
