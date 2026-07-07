"""
Export Nominatim AUTO_APPROVABLE rows into dim_geo correction candidates.

The output is intentionally separate from data/reference/dim_geo/geo_dim_approved_corrections.csv.
It can be reviewed first, then merged into the approved corrections file only when the
business owner accepts the rule.

Safety rule:
  A source_geo_key is exported only when every AUTO_APPROVABLE row for that key
  points to the same approved DimRegion target. If rue/quartier hints produce
  different targets for the same source key, the key stays in manual review.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Iterable


BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_INPUT_CSV = BASE_DIR / "data" / "quality_reports" / "dim_geo" / "dim_geo_nominatim_verified_candidates.csv"
DEFAULT_EXISTING_CORRECTIONS_CSV = BASE_DIR / "data" / "reference" / "dim_geo" / "geo_dim_approved_corrections.csv"
DEFAULT_OUTPUT_CSV = BASE_DIR / "data" / "quality_reports" / "dim_geo" / "dim_geo_nominatim_auto_approvable_corrections.csv"
DEFAULT_SKIPPED_CSV = BASE_DIR / "data" / "quality_reports" / "dim_geo" / "dim_geo_nominatim_auto_approvable_skipped_ambiguous_keys.csv"

OUTPUT_COLUMNS = [
    "geo_sk",
    "geo_key",
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

SKIPPED_COLUMNS = [
    "source_geo_key",
    "auto_approvable_rows",
    "distinct_approved_targets",
    "skip_reason",
    "target_summary",
]

TARGET_COLUMNS = [
    "approved_region",
    "approved_gouvernorat",
    "approved_delegation",
    "approved_localite",
    "approved_code_postal",
]


def _clean(value: object) -> str:
    return str(value or "").strip()


def _key(value: object) -> str:
    return _clean(value).upper()


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def _write_csv(path: Path, rows: Iterable[dict[str, str]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def existing_correction_keys(path: Path) -> set[str]:
    rows, _ = _read_csv(path)
    keys: set[str] = set()
    for row in rows:
        for name in ("source_geo_key", "geo_key"):
            key = _key(row.get(name))
            if key:
                keys.add(key)
    return keys


def is_auto_approvable(row: dict[str, str], min_confidence: float) -> bool:
    try:
        confidence = float(_clean(row.get("confidence_score")) or "0")
    except ValueError:
        confidence = 0.0
    return (
        _key(row.get("nominatim_decision")) == "AUTO_APPROVABLE"
        and _key(row.get("nominatim_status")) == "NOMINATIM_CONFIRMED"
        and _key(row.get("nominatim_governorate_match")) == "YES"
        and _key(row.get("nominatim_place_match")) == "YES"
        and confidence >= min_confidence
    )


def target_key(row: dict[str, str]) -> tuple[str, ...]:
    return tuple(_key(row.get(col)) for col in TARGET_COLUMNS)


def _target_summary(targets: Iterable[tuple[str, ...]]) -> str:
    parts = []
    for target in sorted(set(targets)):
        parts.append("|".join(target))
    return " ; ".join(parts)


def _correction_row(row: dict[str, str], source_key: str, approval_status: str) -> dict[str, str]:
    nominatim_place = _clean(row.get("nominatim_display_name"))
    nominatim_place_id = _clean(row.get("nominatim_place_id"))
    query = _clean(row.get("nominatim_query"))
    comment = (
        "Nominatim/OpenStreetMap confirmed Tunisia, expected governorate, and expected place; "
        f"query='{query}'; place_id='{nominatim_place_id}'; result='{nominatim_place}'."
    )
    return {
        "geo_sk": "",
        "geo_key": source_key,
        "current_region": _clean(row.get("current_region")),
        "current_gouvernorat": _clean(row.get("current_gouvernorat")),
        "current_localite": _clean(row.get("current_localite")),
        "current_code_postal": _clean(row.get("current_code_postal")),
        "approved_region": _clean(row.get("approved_region")),
        "approved_gouvernorat": _clean(row.get("approved_gouvernorat")),
        "approved_delegation": _clean(row.get("approved_delegation")),
        "approved_localite": _clean(row.get("approved_localite")),
        "approved_code_postal": _clean(row.get("approved_code_postal")),
        "approval_status": _clean(approval_status).upper() or "PENDING",
        "reviewer_comment": comment,
        "review_decision_rule": "NOMINATIM_AUTO_APPROVABLE_DIMREGION_RUE_TERM_UNIQUE_SOURCE_KEY",
        "geo_audit_status": _clean(row.get("geo_audit_status")),
        "confidence_score": _clean(row.get("confidence_score")),
        "matched_source_field": _clean(row.get("matched_source_field")),
        "matched_reference_key": _clean(row.get("matched_reference_key")),
    }


def build_auto_approval_export(
    rows: Iterable[dict[str, str]],
    existing_keys: set[str],
    approval_status: str,
    min_confidence: float,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    groups: dict[str, list[dict[str, str]]] = {}
    source_key_by_norm: dict[str, str] = {}
    for row in rows:
        if not is_auto_approvable(row, min_confidence):
            continue
        source_key = _clean(row.get("source_geo_key"))
        normalized_key = _key(source_key)
        if not normalized_key or normalized_key in existing_keys:
            continue
        groups.setdefault(normalized_key, []).append(row)
        source_key_by_norm.setdefault(normalized_key, source_key)

    output: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for normalized_key, grouped_rows in groups.items():
        targets = [target_key(row) for row in grouped_rows]
        distinct_targets = set(targets)
        source_key = source_key_by_norm[normalized_key]
        if len(distinct_targets) != 1:
            skipped.append({
                "source_geo_key": source_key,
                "auto_approvable_rows": str(len(grouped_rows)),
                "distinct_approved_targets": str(len(distinct_targets)),
                "skip_reason": "same source_geo_key has multiple approved DimRegion targets from rue/quartier hints",
                "target_summary": _target_summary(distinct_targets),
            })
            continue
        output.append(_correction_row(grouped_rows[0], source_key, approval_status))
    return output, skipped


def build_auto_approval_rows(
    rows: Iterable[dict[str, str]],
    existing_keys: set[str],
    approval_status: str,
    min_confidence: float,
) -> list[dict[str, str]]:
    output, _ = build_auto_approval_export(rows, existing_keys, approval_status, min_confidence)
    return output


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export Nominatim AUTO_APPROVABLE GEO corrections for review.")
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--existing-corrections-csv", type=Path, default=DEFAULT_EXISTING_CORRECTIONS_CSV)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--skipped-csv", type=Path, default=DEFAULT_SKIPPED_CSV)
    parser.add_argument("--approval-status", default="PENDING", help="Use APPROVED only after business acceptance of the bulk rule.")
    parser.add_argument("--min-confidence", type=float, default=0.70)
    parser.add_argument("--include-existing-duplicates", action="store_true")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    rows, _ = _read_csv(args.input_csv)
    existing_keys = set() if args.include_existing_duplicates else existing_correction_keys(args.existing_corrections_csv)
    output_rows, skipped_rows = build_auto_approval_export(rows, existing_keys, args.approval_status, args.min_confidence)
    _write_csv(args.output_csv, output_rows, OUTPUT_COLUMNS)
    _write_csv(args.skipped_csv, skipped_rows, SKIPPED_COLUMNS)

    print("=" * 72)
    print(f"input rows              : {len(rows)}")
    print(f"existing correction keys: {len(existing_keys)}")
    print(f"exported rows           : {len(output_rows)}")
    print(f"skipped ambiguous keys  : {len(skipped_rows)}")
    print(f"approval_status         : {_clean(args.approval_status).upper() or 'PENDING'}")
    print(f"output                  : {args.output_csv}")
    print(f"skipped                 : {args.skipped_csv}")
    print("=" * 72)


if __name__ == "__main__":
    main()
