"""
Offline audit of staging sinistre GEO values against DimRegion.csv.

This script is read-only from a database perspective: it reads a CSV export
of staging.stg_sinistres GEO columns and writes audit reports under
data/quality_reports/staging_geo. It does not update staging or DWH tables.

Example:
  python etl/staging_area/audit_geo_staging_reference.py ^
    --input-csv "C:\\Users\\wiem\\Downloads\\dw pg admin\\iris_dw\\data-1783280034795.csv"
"""
from __future__ import annotations

import argparse
import csv
import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_REFERENCE_CSV = BASE_DIR / "data" / "reference" / "dim_geo" / "DimRegion.csv"
DEFAULT_OUTPUT_DIR = BASE_DIR / "data" / "quality_reports" / "staging_geo"

OUTPUT_ALL = "staging_geo_reference_audit_all.csv"
OUTPUT_CONFLICTS = "staging_geo_reference_conflicts.csv"
OUTPUT_ENRICHMENT = "staging_geo_reference_enrichment_candidates.csv"
OUTPUT_SUMMARY = "staging_geo_reference_summary.csv"

NULL_TOKENS = frozenset(
    {
        "",
        "NULL",
        "NAN",
        "NONE",
        "N/A",
        "NA",
        "-",
        "--",
        "---",
        ".",
        "..",
        "/",
        "UNKNOWN",
        "INCONNU",
        "INCONNUE",
        "NON RENSEIGNE",
        "NON RENSEIGNEE",
        "NON RENSEIGNÉ",
        "NON RENSEIGNÉE",
    }
)

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
    "AEN AROUS": "BEN AROUS",
    "B AROUS": "BEN AROUS",
    "BAN AROUS": "BEN AROUS",
    "BENA ROUS": "BEN AROUS",
    "BEN AOUS": "BEN AROUS",
    "BEN AROU": "BEN AROUS",
    "BEN AROUS": "BEN AROUS",
    "BEN ARUS": "BEN AROUS",
    "BENAROUS": "BEN AROUS",
    "BIZER": "BIZERTE",
    "BIZERT": "BIZERTE",
    "BIZERTA": "BIZERTE",
    "GABES VILLE": "GABES",
    "GAFES": "GAFSA",
    "JANDOUBA": "JENDOUBA",
    "JENDOUBAS": "JENDOUBA",
    "KAIROUEN": "KAIROUAN",
    "KASSERIEN": "KASSERINE",
    "KEBILLI": "KEBILI",
    "LA MANNOUBA": "MANOUBA",
    "MANNOUBA": "MANOUBA",
    "MANOUBA VILLE": "MANOUBA",
    "MEDNIN": "MEDENINE",
    "MEDNINE": "MEDENINE",
    "NABEL": "NABEUL",
    "NABEOUL": "NABEUL",
    "SAFX": "SFAX",
    "SFA": "SFAX",
    "SFGAX": "SFAX",
    "SFX": "SFAX",
    "SFXA": "SFAX",
    "SIDI BOUSID": "SIDI BOUZID",
    "SIDI BOUZAID": "SIDI BOUZID",
    "SOSSE": "SOUSSE",
    "SOUSS": "SOUSSE",
    "STUNIS": "TUNIS",
    "TUINS": "TUNIS",
    "TUIS": "TUNIS",
    "TUNID": "TUNIS",
    "TUNI": "TUNIS",
    "TUNISIE": "TUNIS",
    "ZAGHOUANE": "ZAGHOUAN",
}

CONFLICT_FLAGS = frozenset(
    {
        "POSTAL_GOUV_CONFLICT",
        "POSTAL_LOCALITE_CONFLICT",
    }
)
ENRICHMENT_FLAGS = frozenset(
    {
        "MISSING_GOUV_FROM_CP_UNIQUE",
        "MISSING_LOCALITE_FROM_CP_UNIQUE",
        "MISSING_CP_FROM_GOUV_LOCALITE_UNIQUE",
        "MISSING_CP_FROM_GOUV_REGSINI_UNIQUE",
        "MISSING_CP_FROM_LOCALITE_UNIQUE",
    }
)
AMBIGUOUS_FLAGS = frozenset(
    {
        "MISSING_GOUV_FROM_CP_AMBIGUOUS",
        "MISSING_LOCALITE_FROM_CP_AMBIGUOUS",
        "MISSING_CP_FROM_GOUV_LOCALITE_AMBIGUOUS",
        "MISSING_CP_FROM_GOUV_REGSINI_AMBIGUOUS",
        "MISSING_CP_FROM_LOCALITE_AMBIGUOUS",
    }
)
DIAGNOSTIC_FLAGS = frozenset(
    {
        "REGSINI_LOOKS_LIKE_LOCALITE_OR_DELEGATION",
        "GOUVSINI_NOT_OFFICIAL_GOVERNORATE",
    }
)

AUDIT_COLUMNS = [
    "raw_cpostsini",
    "raw_regsini",
    "raw_gouvsini",
    "raw_citesini",
    "raw_rue",
    "cpostsini_norm",
    "regsini_norm",
    "gouvsini_norm",
    "citesini_norm",
    "rue_norm",
    "audit_status",
    "flags",
    "candidate_gouvernorat",
    "candidate_delegation",
    "candidate_localite",
    "candidate_code_postal",
    "candidate_source",
    "candidate_reason",
]


@dataclass(frozen=True)
class ReferenceRow:
    gouvernorat: str
    delegation: str
    localite: str
    code_postal: str


@dataclass(frozen=True)
class ReferenceIndex:
    rows: tuple[ReferenceRow, ...]
    by_cp: dict[str, tuple[ReferenceRow, ...]]
    by_gouv_localite: dict[tuple[str, str], tuple[ReferenceRow, ...]]
    by_gouv_delegation: dict[tuple[str, str], tuple[ReferenceRow, ...]]
    by_localite: dict[str, tuple[ReferenceRow, ...]]
    localite_or_delegation_terms: frozenset[str]


def normalize_match_text(value: object) -> str | None:
    """Normalize text for reference matching, including accent removal."""
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
    return None if not text or text in NULL_TOKENS else text


def normalize_gouvernorat(value: object) -> str | None:
    text = normalize_match_text(value)
    if text is None:
        return None
    return GOVERNORAT_ALIASES.get(text, text)


def normalize_postal_code(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    compact = re.sub(r"\s+", "", text.upper())
    if compact in NULL_TOKENS:
        return None
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


def _join(values: Iterable[str | None], limit: int = 8) -> str:
    unique_values = _unique(values)
    clipped = unique_values[:limit]
    suffix = f" (+{len(unique_values) - limit})" if len(unique_values) > limit else ""
    return "|".join(clipped) + suffix


def _tuple_index(index: dict) -> dict:
    return {key: tuple(values) for key, values in index.items()}


def read_reference(path: Path) -> tuple[ReferenceRow, ...]:
    if not path.exists():
        raise FileNotFoundError(f"Reference file not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        required = {"Gouvernorat", "Delegation", "Localite", "Code postal"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} missing columns: {sorted(missing)}")

        rows: list[ReferenceRow] = []
        for raw in reader:
            gouvernorat = normalize_gouvernorat(raw.get("Gouvernorat"))
            delegation = normalize_match_text(raw.get("Delegation"))
            localite = normalize_match_text(raw.get("Localite"))
            code_postal = normalize_postal_code(raw.get("Code postal"))
            if not gouvernorat or not localite or not code_postal:
                continue
            rows.append(
                ReferenceRow(
                    gouvernorat=gouvernorat,
                    delegation=delegation or "",
                    localite=localite,
                    code_postal=code_postal,
                )
            )

    if not rows:
        raise ValueError(f"No usable reference rows in {path}")
    return tuple(rows)


def build_reference_index(ref_rows: Iterable[ReferenceRow]) -> ReferenceIndex:
    rows = tuple(ref_rows)
    by_cp: defaultdict[str, list[ReferenceRow]] = defaultdict(list)
    by_gouv_localite: defaultdict[tuple[str, str], list[ReferenceRow]] = defaultdict(list)
    by_gouv_delegation: defaultdict[tuple[str, str], list[ReferenceRow]] = defaultdict(list)
    by_localite: defaultdict[str, list[ReferenceRow]] = defaultdict(list)
    terms: set[str] = set()

    for row in rows:
        by_cp[row.code_postal].append(row)
        by_gouv_localite[(row.gouvernorat, row.localite)].append(row)
        by_localite[row.localite].append(row)
        terms.add(row.localite)
        if row.delegation:
            by_gouv_delegation[(row.gouvernorat, row.delegation)].append(row)
            terms.add(row.delegation)

    return ReferenceIndex(
        rows=rows,
        by_cp=_tuple_index(by_cp),
        by_gouv_localite=_tuple_index(by_gouv_localite),
        by_gouv_delegation=_tuple_index(by_gouv_delegation),
        by_localite=_tuple_index(by_localite),
        localite_or_delegation_terms=frozenset(terms),
    )


def _input_value(row: dict[str, object], column: str) -> object:
    return row.get(column) if column in row else row.get(column.upper())


def _append_unique(values: list[str], *items: str | None) -> None:
    for item in items:
        if item and item not in values:
            values.append(item)


def _classify(flags: list[str]) -> str:
    flag_set = set(flags)
    if flag_set.intersection(CONFLICT_FLAGS):
        return "CONFLICT"
    if "CP_NOT_IN_REFERENCE" in flag_set:
        return "REFERENCE_GAP"
    if flag_set.intersection(ENRICHMENT_FLAGS):
        return "ENRICHMENT_CANDIDATE"
    if flag_set.intersection(AMBIGUOUS_FLAGS):
        return "AMBIGUOUS_REFERENCE"
    if flag_set.intersection(DIAGNOSTIC_FLAGS):
        return "FIELD_MISUSE"
    return "REFERENCE_COHERENT_OR_NO_ACTION"


def audit_one_row(row: dict[str, object], ref_index: ReferenceIndex) -> dict[str, str]:
    raw_cp = _input_value(row, "cpostsini")
    raw_reg = _input_value(row, "regsini")
    raw_gouv = _input_value(row, "gouvsini")
    raw_cite = _input_value(row, "citesini")
    raw_rue = _input_value(row, "rue")

    cp = normalize_postal_code(raw_cp)
    regsini = normalize_match_text(raw_reg)
    gouv = normalize_gouvernorat(raw_gouv)
    cite = normalize_match_text(raw_cite)
    rue = normalize_match_text(raw_rue)

    flags: list[str] = []
    candidate_gouvs: list[str] = []
    candidate_delegations: list[str] = []
    candidate_localites: list[str] = []
    candidate_cps: list[str] = []
    candidate_sources: list[str] = []
    reasons: list[str] = []

    if regsini and regsini in ref_index.localite_or_delegation_terms:
        flags.append("REGSINI_LOOKS_LIKE_LOCALITE_OR_DELEGATION")
        reasons.append("regsini matches a DimRegion localite/delegation term")

    if gouv and gouv not in VALID_GOVERNORATS:
        flags.append("GOUVSINI_NOT_OFFICIAL_GOVERNORATE")
        reasons.append("gouvsini is not one of the 24 official governorates after alias normalization")

    refs_for_cp = ref_index.by_cp.get(cp or "", ())
    if cp:
        if not refs_for_cp:
            flags.append("CP_NOT_IN_REFERENCE")
            reasons.append("cpostsini is not present in DimRegion.csv")
        else:
            ref_gouvs = _unique(ref.gouvernorat for ref in refs_for_cp)
            ref_localites = _unique(ref.localite for ref in refs_for_cp)
            ref_delegations = _unique(ref.delegation for ref in refs_for_cp)

            if gouv and gouv in VALID_GOVERNORATS and gouv not in ref_gouvs:
                flags.append("POSTAL_GOUV_CONFLICT")
                _append_unique(candidate_gouvs, *ref_gouvs)
                _append_unique(candidate_sources, "DimRegion.code_postal")
                reasons.append("cpostsini maps to different governorate(s) in DimRegion.csv")
            elif not gouv:
                if len(ref_gouvs) == 1:
                    flags.append("MISSING_GOUV_FROM_CP_UNIQUE")
                    _append_unique(candidate_gouvs, ref_gouvs[0])
                    _append_unique(candidate_sources, "DimRegion.code_postal")
                    reasons.append("missing gouvsini can be proposed from a unique postal-code governorate")
                elif len(ref_gouvs) > 1:
                    flags.append("MISSING_GOUV_FROM_CP_AMBIGUOUS")
                    _append_unique(candidate_gouvs, *ref_gouvs)

            if cite and cite not in ref_localites:
                flags.append("POSTAL_LOCALITE_CONFLICT")
                _append_unique(candidate_localites, *ref_localites)
                _append_unique(candidate_delegations, *ref_delegations)
                _append_unique(candidate_sources, "DimRegion.code_postal")
                reasons.append("cpostsini maps to different localite(s) in DimRegion.csv")
            elif not cite:
                if len(ref_localites) == 1:
                    flags.append("MISSING_LOCALITE_FROM_CP_UNIQUE")
                    _append_unique(candidate_localites, ref_localites[0])
                    _append_unique(candidate_delegations, *ref_delegations)
                    _append_unique(candidate_sources, "DimRegion.code_postal")
                    reasons.append("missing citesini can be proposed from a unique postal-code localite")
                elif len(ref_localites) > 1:
                    flags.append("MISSING_LOCALITE_FROM_CP_AMBIGUOUS")
                    _append_unique(candidate_localites, *ref_localites)
                    _append_unique(candidate_delegations, *ref_delegations)

    if not cp:
        if gouv and cite:
            refs = ref_index.by_gouv_localite.get((gouv, cite), ())
            cps = _unique(ref.code_postal for ref in refs)
            if len(cps) == 1:
                flags.append("MISSING_CP_FROM_GOUV_LOCALITE_UNIQUE")
                _append_unique(candidate_cps, cps[0])
                _append_unique(candidate_sources, "DimRegion.gouvernorat_localite")
                reasons.append("missing cpostsini can be proposed from unique governorate/localite")
            elif len(cps) > 1:
                flags.append("MISSING_CP_FROM_GOUV_LOCALITE_AMBIGUOUS")
                _append_unique(candidate_cps, *cps)

        if gouv and regsini:
            refs = ref_index.by_gouv_delegation.get((gouv, regsini), ())
            cps = _unique(ref.code_postal for ref in refs)
            if len(cps) == 1:
                flags.append("MISSING_CP_FROM_GOUV_REGSINI_UNIQUE")
                _append_unique(candidate_cps, cps[0])
                _append_unique(candidate_sources, "DimRegion.gouvernorat_regsini")
                reasons.append("missing cpostsini can be proposed from unique governorate/regsini delegation")
            elif len(cps) > 1:
                flags.append("MISSING_CP_FROM_GOUV_REGSINI_AMBIGUOUS")
                _append_unique(candidate_cps, *cps)

        if cite and not gouv:
            refs = ref_index.by_localite.get(cite, ())
            gouvs = _unique(ref.gouvernorat for ref in refs)
            cps = _unique(ref.code_postal for ref in refs)
            if len(gouvs) == 1 and len(cps) == 1:
                flags.append("MISSING_CP_FROM_LOCALITE_UNIQUE")
                _append_unique(candidate_gouvs, gouvs[0])
                _append_unique(candidate_cps, cps[0])
                _append_unique(candidate_sources, "DimRegion.localite")
                reasons.append("missing cpostsini/gouvsini can be proposed from unique localite")
            elif refs:
                flags.append("MISSING_CP_FROM_LOCALITE_AMBIGUOUS")
                _append_unique(candidate_gouvs, *gouvs)
                _append_unique(candidate_cps, *cps)

    flags = list(dict.fromkeys(flags))
    return {
        "raw_cpostsini": "" if raw_cp is None else str(raw_cp),
        "raw_regsini": "" if raw_reg is None else str(raw_reg),
        "raw_gouvsini": "" if raw_gouv is None else str(raw_gouv),
        "raw_citesini": "" if raw_cite is None else str(raw_cite),
        "raw_rue": "" if raw_rue is None else str(raw_rue),
        "cpostsini_norm": cp or "",
        "regsini_norm": regsini or "",
        "gouvsini_norm": gouv or "",
        "citesini_norm": cite or "",
        "rue_norm": rue or "",
        "audit_status": _classify(flags),
        "flags": "|".join(flags),
        "candidate_gouvernorat": _join(candidate_gouvs),
        "candidate_delegation": _join(candidate_delegations),
        "candidate_localite": _join(candidate_localites),
        "candidate_code_postal": _join(candidate_cps),
        "candidate_source": "|".join(candidate_sources),
        "candidate_reason": " | ".join(dict.fromkeys(reasons)),
    }


def audit_source_rows(rows: Iterable[dict[str, object]], ref_index: ReferenceIndex) -> list[dict[str, str]]:
    return [audit_one_row(row, ref_index) for row in rows]


def read_source_csv(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        raise FileNotFoundError(f"Input CSV not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for raw in reader:
            rows.append({str(key).strip().lower(): value for key, value in raw.items()})
    return rows


def write_csv(path: Path, rows: Iterable[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def summarize(results: list[dict[str, str]], reference_rows: tuple[ReferenceRow, ...]) -> list[dict[str, str]]:
    status_counts = Counter(row["audit_status"] for row in results)
    flag_counts: Counter[str] = Counter()
    for row in results:
        for flag in row["flags"].split("|"):
            if flag:
                flag_counts[flag] += 1

    summary = [
        {"metric": "input_rows", "value": str(len(results))},
        {"metric": "reference_rows_usable", "value": str(len(reference_rows))},
    ]
    summary.extend(
        {"metric": f"status.{status}", "value": str(count)}
        for status, count in sorted(status_counts.items())
    )
    summary.extend(
        {"metric": f"flag.{flag}", "value": str(count)}
        for flag, count in sorted(flag_counts.items())
    )
    return summary


def write_reports(results: list[dict[str, str]], reference_rows: tuple[ReferenceRow, ...], output_dir: Path) -> None:
    write_csv(output_dir / OUTPUT_ALL, results, AUDIT_COLUMNS)

    conflicts = [row for row in results if row["audit_status"] == "CONFLICT"]
    write_csv(output_dir / OUTPUT_CONFLICTS, conflicts, AUDIT_COLUMNS)

    enrichment = [row for row in results if row["audit_status"] == "ENRICHMENT_CANDIDATE"]
    write_csv(output_dir / OUTPUT_ENRICHMENT, enrichment, AUDIT_COLUMNS)

    write_csv(output_dir / OUTPUT_SUMMARY, summarize(results, reference_rows), ["metric", "value"])


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit a staging.stg_sinistres GEO CSV export against DimRegion.csv."
    )
    parser.add_argument("--input-csv", type=Path, required=True, help="CSV export to audit.")
    parser.add_argument(
        "--reference-csv",
        type=Path,
        default=DEFAULT_REFERENCE_CSV,
        help="DimRegion.csv path.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where audit CSV reports are written.",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    reference_rows = read_reference(args.reference_csv)
    ref_index = build_reference_index(reference_rows)
    source_rows = read_source_csv(args.input_csv)
    results = audit_source_rows(source_rows, ref_index)
    write_reports(results, reference_rows, args.output_dir)

    status_counts = Counter(row["audit_status"] for row in results)
    print("=" * 72)
    print(f"input rows audited       : {len(results)}")
    print(f"reference rows usable    : {len(reference_rows)}")
    for status, count in sorted(status_counts.items()):
        print(f"{status:<28}: {count}")
    print("-" * 72)
    print(f"all rows                 : {args.output_dir / OUTPUT_ALL}")
    print(f"conflicts                : {args.output_dir / OUTPUT_CONFLICTS}")
    print(f"enrichment candidates    : {args.output_dir / OUTPUT_ENRICHMENT}")
    print(f"summary                  : {args.output_dir / OUTPUT_SUMMARY}")
    print("=" * 72)


if __name__ == "__main__":
    main()
