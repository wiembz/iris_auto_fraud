"""
Build dwh.dim_vehicule from inspection and claim-side vehicle identifiers.

Grain: one row per normalized primary vehicle immatriculation.

The physical DWH schema is unchanged:
  vehicule_sk, immatriculation, vin, motorisation, source_system, created_at

Source flags are kept in quality reports only. After a future rebuild,
vehicule_sk values may change; dependent facts must be reloaded in the same
controlled run.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

DWH_DIR = Path(__file__).resolve().parent
BASE_DIR = DWH_DIR.parent.parent
sys.path.insert(0, str(DWH_DIR))
sys.path.insert(0, str(BASE_DIR))

import dwh_utils
from etl.utils.vehicle_normalization import normalize_immatriculation


TABLE_NAME = "dim_vehicule"
INSPECTION_SOURCE_TABLE = "staging.stg_inspection"
CLAIM_SOURCE_TABLE = "staging.stg_sinistres"
SOURCE_TABLE = INSPECTION_SOURCE_TABLE
SOURCE_SYSTEM_INSPECTION = "STAFIM"
SOURCE_SYSTEM_CLAIM = "BNA_ASSURANCES"
SOURCE_SYSTEM_BOTH = "STAFIM+BNA_ASSURANCES"

REPORT_DIR = BASE_DIR / "data" / "quality_reports" / "dim_vehicule"
LOAD_SUMMARY_PATH = REPORT_DIR / "dim_vehicule_load_summary.csv"
SOURCE_COVERAGE_PATH = REPORT_DIR / "dim_vehicule_source_coverage.csv"
INVALID_IMMAT_PATH = REPORT_DIR / "dim_vehicule_invalid_immatriculations.csv"
DUPLICATE_IMMAT_PATH = REPORT_DIR / "dim_vehicule_duplicate_normalized_immat.csv"

FINAL_COLS = [
    "vehicule_sk",
    "immatriculation",
    "vin",
    "motorisation",
    "source_system",
    "created_at",
]


def _clean_str(val: object) -> str | None:
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    s = " ".join(str(val).strip().upper().split())
    return s if s else None


def _table_exists(engine, schema: str, table: str) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = :schema
                      AND table_name = :table
                    """
                ),
                {"schema": schema, "table": table},
            ).fetchone()
        )


def _read_inspection_staging(engine, logger) -> pd.DataFrame:
    sql = text(
        """
        SELECT
            immatriculation,
            vin,
            motorisation,
            date_inspection,
            horodateur
        FROM staging.stg_inspection
        WHERE is_valid_for_join = TRUE
          AND immatriculation IS NOT NULL
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    logger.info(f"  inspection source rows read: {len(df)}")
    return df


def _read_claim_staging(engine, logger) -> pd.DataFrame:
    sql = text(
        """
        SELECT immat
        FROM staging.stg_sinistres
        WHERE immat IS NOT NULL
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    logger.info(f"  claim source rows read: {len(df)}")
    return df


def _empty_inspection_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["immatriculation", "vin", "motorisation", "date_inspection", "horodateur"]
    )


def _empty_claim_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["immat"])


def _prepare_inspection_candidates(df_inspection: pd.DataFrame) -> pd.DataFrame:
    df = df_inspection.copy()
    for col in ["immatriculation", "vin", "motorisation", "date_inspection", "horodateur"]:
        if col not in df.columns:
            df[col] = pd.NA

    df["raw_immatriculation"] = df["immatriculation"]
    df["immatriculation"] = df["immatriculation"].map(normalize_immatriculation)
    df["vin"] = df["vin"].map(_clean_str)
    df["motorisation"] = df["motorisation"].map(_clean_str)
    df["_has_inspection_source"] = True
    df["_has_claim_source"] = False
    return df[
        [
            "raw_immatriculation",
            "immatriculation",
            "vin",
            "motorisation",
            "date_inspection",
            "horodateur",
            "_has_inspection_source",
            "_has_claim_source",
        ]
    ]


def _prepare_claim_candidates(df_claims: pd.DataFrame) -> pd.DataFrame:
    df = df_claims.copy()
    if "immat" not in df.columns and "immatriculation" in df.columns:
        df["immat"] = df["immatriculation"]
    if "immat" not in df.columns:
        df["immat"] = pd.NA

    out = pd.DataFrame(index=df.index)
    out["raw_immatriculation"] = df["immat"]
    out["immatriculation"] = df["immat"].map(normalize_immatriculation)
    out["vin"] = pd.NA
    out["motorisation"] = pd.NA
    out["date_inspection"] = pd.NaT
    out["horodateur"] = pd.NaT
    out["_has_inspection_source"] = False
    out["_has_claim_source"] = True
    return out


def _build_vehicle_candidates(
    df_inspection: pd.DataFrame,
    df_claims: pd.DataFrame | None = None,
) -> pd.DataFrame:
    inspection = _prepare_inspection_candidates(df_inspection)
    claims = _prepare_claim_candidates(df_claims if df_claims is not None else _empty_claim_frame())
    candidates = pd.concat([inspection, claims], ignore_index=True)
    return candidates[candidates["immatriculation"].notna()].copy()


def _select_best_per_immat(candidates: pd.DataFrame, logger) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame(columns=FINAL_COLS + ["_has_inspection_source", "_has_claim_source"])

    df = candidates.copy()
    df["_score"] = (
        df["_has_inspection_source"].astype(int) * 4
        + df["vin"].notna().astype(int) * 2
        + df["motorisation"].notna().astype(int)
    )
    df["_date_sort"] = pd.to_datetime(df["date_inspection"], errors="coerce")
    df["_hora_sort"] = pd.to_datetime(df["horodateur"], errors="coerce")

    df_sorted = df.sort_values(
        by=["immatriculation", "_score", "_date_sort", "_hora_sort"],
        ascending=[True, False, False, False],
        na_position="last",
    )
    best = df_sorted.drop_duplicates(subset=["immatriculation"], keep="first").copy()

    flags = (
        df.groupby("immatriculation", as_index=False)[
            ["_has_inspection_source", "_has_claim_source"]
        ]
        .any()
    )
    best = best.drop(columns=["_has_inspection_source", "_has_claim_source"]).merge(
        flags,
        on="immatriculation",
        how="left",
    )

    n_total = len(df)
    n_uniq = len(best)
    logger.info(
        f"  vehicle deduplication: {n_total} candidates -> {n_uniq} distinct immatriculations "
        f"({n_total - n_uniq} duplicate candidate rows removed)"
    )
    return best.drop(columns=["_score", "_date_sort", "_hora_sort"])


def _source_system_from_flags(row: pd.Series) -> str:
    has_inspection = bool(row.get("_has_inspection_source", False))
    has_claim = bool(row.get("_has_claim_source", False))
    if has_inspection and has_claim:
        return SOURCE_SYSTEM_BOTH
    if has_inspection:
        return SOURCE_SYSTEM_INSPECTION
    return SOURCE_SYSTEM_CLAIM


def transform_dim_vehicule(
    df_inspection: pd.DataFrame,
    logger,
    df_claims: pd.DataFrame | None = None,
) -> pd.DataFrame:
    candidates = _build_vehicle_candidates(df_inspection, df_claims)
    df = _select_best_per_immat(candidates, logger)

    if df.empty:
        return pd.DataFrame(columns=FINAL_COLS)

    df = df.sort_values("immatriculation", na_position="last").reset_index(drop=True)
    df.insert(0, "vehicule_sk", range(1, len(df) + 1))
    df["source_system"] = df.apply(_source_system_from_flags, axis=1)
    df["created_at"] = datetime.now(timezone.utc).replace(tzinfo=None)

    for col in FINAL_COLS:
        if col not in df.columns:
            df[col] = None

    df_final = df[FINAL_COLS].copy()

    n_claim_only = int((df["_has_claim_source"] & ~df["_has_inspection_source"]).sum())
    n_inspection_only = int((df["_has_inspection_source"] & ~df["_has_claim_source"]).sum())
    n_both = int((df["_has_claim_source"] & df["_has_inspection_source"]).sum())
    n_vin = int(df_final["vin"].notna().sum())
    n_motor = int(df_final["motorisation"].notna().sum())

    logger.info(f"  vehicles prepared: {len(df_final)}")
    logger.info(f"  source coverage: inspection_only={n_inspection_only}, claim_only={n_claim_only}, both={n_both}")
    logger.info(f"  with VIN={n_vin}, with motorisation={n_motor}")

    return df_final


def _invalid_immatriculation_report(
    df_inspection: pd.DataFrame,
    df_claims: pd.DataFrame | None,
) -> pd.DataFrame:
    rows = []
    if not df_inspection.empty and "immatriculation" in df_inspection.columns:
        insp = df_inspection[["immatriculation"]].copy()
        insp["source"] = SOURCE_SYSTEM_INSPECTION
        insp = insp.rename(columns={"immatriculation": "raw_immatriculation"})
        rows.append(insp)
    if df_claims is not None and not df_claims.empty and "immat" in df_claims.columns:
        claims = df_claims[["immat"]].copy()
        claims["source"] = SOURCE_SYSTEM_CLAIM
        claims = claims.rename(columns={"immat": "raw_immatriculation"})
        rows.append(claims)
    if not rows:
        return pd.DataFrame(columns=["source", "raw_immatriculation", "normalized_immatriculation"])

    raw = pd.concat(rows, ignore_index=True)
    raw["normalized_immatriculation"] = raw["raw_immatriculation"].map(normalize_immatriculation)
    invalid = raw[
        raw["raw_immatriculation"].notna()
        & raw["raw_immatriculation"].astype(str).str.strip().ne("")
        & raw["normalized_immatriculation"].isna()
    ].copy()
    return invalid[["source", "raw_immatriculation", "normalized_immatriculation"]]


def _write_quality_reports(
    df_inspection: pd.DataFrame,
    df_claims: pd.DataFrame | None,
    df_final: pd.DataFrame,
) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    candidates = _build_vehicle_candidates(df_inspection, df_claims)

    if candidates.empty:
        source_flags = pd.DataFrame(
            columns=["immatriculation", "has_inspection_source", "has_claim_source"]
        )
    else:
        source_flags = (
            candidates.groupby("immatriculation", as_index=False)[
                ["_has_inspection_source", "_has_claim_source"]
            ]
            .any()
            .rename(
                columns={
                    "_has_inspection_source": "has_inspection_source",
                    "_has_claim_source": "has_claim_source",
                }
            )
        )

    coverage = df_final[["immatriculation", "vin", "motorisation", "source_system"]].merge(
        source_flags,
        on="immatriculation",
        how="left",
    )
    coverage.to_csv(SOURCE_COVERAGE_PATH, index=False, encoding="utf-8-sig")

    invalid = _invalid_immatriculation_report(df_inspection, df_claims)
    invalid.to_csv(INVALID_IMMAT_PATH, index=False, encoding="utf-8-sig")

    duplicates = (
        candidates.groupby("immatriculation")
        .size()
        .rename("candidate_rows")
        .reset_index()
        .query("candidate_rows > 1")
        .sort_values(["candidate_rows", "immatriculation"], ascending=[False, True])
    )
    duplicates.to_csv(DUPLICATE_IMMAT_PATH, index=False, encoding="utf-8-sig")

    metrics = {
        "inspection_source_rows": len(df_inspection),
        "claim_source_rows": 0 if df_claims is None else len(df_claims),
        "candidate_rows_after_normalization": len(candidates),
        "distinct_vehicle_rows": len(df_final),
        "inspection_source_vehicle_rows": int(coverage["has_inspection_source"].fillna(False).sum()),
        "claim_source_vehicle_rows": int(coverage["has_claim_source"].fillna(False).sum()),
        "claim_only_vehicle_rows": int(
            (coverage["has_claim_source"].fillna(False) & ~coverage["has_inspection_source"].fillna(False)).sum()
        ),
        "vehicles_with_vin": int(df_final["vin"].notna().sum()),
        "vehicles_with_motorisation": int(df_final["motorisation"].notna().sum()),
        "invalid_immatriculation_rows": len(invalid),
        "duplicate_normalized_immat_rows": len(duplicates),
    }
    pd.DataFrame([{"metric": k, "value": v} for k, v in sorted(metrics.items())]).to_csv(
        LOAD_SUMMARY_PATH,
        index=False,
        encoding="utf-8-sig",
    )


def load_dim_vehicule(run_id: str, engine, logger) -> int:
    logger.info(f"[RUN {run_id}] {INSPECTION_SOURCE_TABLE} + {CLAIM_SOURCE_TABLE} -> dwh.{TABLE_NAME}")

    inspection_exists = _table_exists(engine, "staging", "stg_inspection")
    claim_exists = _table_exists(engine, "staging", "stg_sinistres")
    if not inspection_exists and not claim_exists:
        raise RuntimeError(
            "Neither staging.stg_inspection nor staging.stg_sinistres exists. "
            "Run staging loaders first."
        )

    if inspection_exists:
        df_inspection = _read_inspection_staging(engine, logger)
    else:
        logger.warning("  staging.stg_inspection not found; building claim-only vehicle candidates")
        df_inspection = _empty_inspection_frame()

    if claim_exists:
        df_claims = _read_claim_staging(engine, logger)
    else:
        logger.warning("  staging.stg_sinistres not found; building inspection-only vehicle candidates")
        df_claims = _empty_claim_frame()

    if df_inspection.empty and df_claims.empty:
        logger.warning("  no vehicle identifiers available; load cancelled")
        return 0

    df_final = transform_dim_vehicule(df_inspection, logger, df_claims)
    _write_quality_reports(df_inspection, df_claims, df_final)

    n_rows, elapsed = dwh_utils.write_to_dwh(df_final, engine, TABLE_NAME, logger)

    logger.info("=" * 60)
    logger.info(f"  vehicles loaded: {n_rows}")
    logger.info(f"  load duration: {elapsed:.1f}s")
    logger.info(f"  source coverage report: {SOURCE_COVERAGE_PATH}")
    logger.info(f"  invalid immatriculation report: {INVALID_IMMAT_PATH}")
    logger.info(f"  duplicate normalized immat report: {DUPLICATE_IMMAT_PATH}")
    logger.info(f"  load summary report: {LOAD_SUMMARY_PATH}")
    logger.info(
        "  note: vehicule_sk values may change after rebuild; reload dependent facts in the same controlled run"
    )
    logger.info("=" * 60)

    return n_rows


if __name__ == "__main__":
    _run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    _logger = dwh_utils.setup_logging(_run_id, log_name="load_dim_vehicule")
    _engine = dwh_utils.build_engine(_logger)
    dwh_utils.create_dwh_schema(_engine, _logger)
    _n = load_dim_vehicule(_run_id, _engine, _logger)
    _logger.info(f"Done: {_n} rows -> dwh.{TABLE_NAME}")
