"""
etl/mart/compute_claim_scoring_features_v1.py
=============================================
Builds the Claim Attention V1 feature mart.

This module prepares explainable, claim-level indicators for prioritization.
It does not compute a fraud score and it does not make an automatic decision.

Sources:
  dwh.fact_sinistre
  dwh.fact_contrat

Output:
  mart.fact_claim_scoring_features
  data/quality_reports/scoring/claim_attention_v1/features/
"""
from __future__ import annotations

import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from sqlalchemy import text
except ModuleNotFoundError:  # Allows pure feature tests without DB dependencies.
    text = None

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dwh"))


def _load_dwh_utils():
    import dwh_utils
    return dwh_utils

BASE_DIR = Path(__file__).resolve().parent.parent.parent
REPORT_DIR = BASE_DIR / "data" / "quality_reports" / "scoring" / "claim_attention_v1" / "features"

FEATURE_VERSION = "IRIS_CLAIM_ATTENTION_FEATURES_V1_CANDIDATE"
PROFILE_NAME = "CLAIM_ATTENTION_FEATURES_V1_CANDIDATE"

DDL_CREATE_SCHEMA = "CREATE SCHEMA IF NOT EXISTS mart;"

DDL_FACT_CLAIM_SCORING_FEATURES = """
CREATE TABLE IF NOT EXISTS mart.fact_claim_scoring_features (
    claim_feature_sk                 BIGSERIAL PRIMARY KEY,
    claim_sk                         BIGINT NOT NULL,
    claim_business_id                TEXT,
    numero_sinistre                  TEXT,
    code_garantie                    TEXT,
    client_sk                        BIGINT,
    contrat_sk                       BIGINT,
    vehicle_sk                       BIGINT,
    garantie_sk                      BIGINT,
    conducteur_sk                    BIGINT,
    tiers_sk                         BIGINT,
    camtier_sk                       BIGINT,
    claim_geo_sk                     BIGINT,
    claim_date_sk                    BIGINT,
    declaration_date_sk              BIGINT,
    contract_start_date_sk           BIGINT,
    claim_date                       DATE,
    declaration_date                 DATE,
    contract_start_date              DATE,
    claim_amount                     NUMERIC(18,2),
    client_claim_count_total         INTEGER,
    client_claim_count_12m           INTEGER,
    client_claim_count_24m           INTEGER,
    days_since_previous_claim        INTEGER,
    client_claim_frequency_band      TEXT,
    amount_vs_guarantee_median_ratio NUMERIC(12,4),
    amount_percentile_by_guarantee   NUMERIC(8,6),
    high_amount_flag                 BOOLEAN,
    days_claim_to_declaration        INTEGER,
    days_contract_start_to_claim     INTEGER,
    claim_before_contract_start_flag BOOLEAN,
    contract_start_ready_flag        BOOLEAN,
    recent_contract_change_flag      BOOLEAN,
    recent_guarantee_change_flag     BOOLEAN,
    claim_after_recent_update_flag   BOOLEAN,
    chronology_ready_flag            BOOLEAN,
    missing_keys_count               INTEGER,
    unknown_dimensions_count         INTEGER,
    weak_join_flag                   BOOLEAN,
    migration_2019_flag              BOOLEAN,
    missing_client_flag              BOOLEAN,
    missing_contract_flag            BOOLEAN,
    missing_vehicle_flag             BOOLEAN,
    missing_guarantee_flag           BOOLEAN,
    missing_geo_flag                 BOOLEAN,
    missing_driver_flag              BOOLEAN,
    missing_third_party_flag         BOOLEAN,
    invalid_claim_date_flag          BOOLEAN,
    invalid_declaration_date_flag    BOOLEAN,
    future_claim_date_flag           BOOLEAN,
    vehicle_recurrence_ready_flag    BOOLEAN,
    third_party_signal_ready_flag    BOOLEAN,
    geo_signal_ready_flag            BOOLEAN,
    vhs_signal_ready_flag            BOOLEAN,
    confidence_level                 TEXT,
    scoring_feature_version          TEXT NOT NULL,
    feature_run_id                   TEXT NOT NULL,
    profile_name                     TEXT NOT NULL,
    source_system                    TEXT DEFAULT 'IRIS_CLAIM_ATTENTION',
    created_at                       TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_claim_scoring_features_run UNIQUE
        (claim_sk, scoring_feature_version, feature_run_id)
);
"""

SOURCE_COLUMNS = [
    "fact_sinistre_sk",
    "numero_sinistre",
    "code_garantie",
    "sinistre_garantie_key",
    "client_sk",
    "contrat_sk",
    "vehicule_sk",
    "garantie_sk",
    "conducteur_sk",
    "tiers_sk",
    "camtier_sk",
    "geo_sinistre_sk",
    "date_survenance_sk",
    "date_declaration_sk",
    "montant_evaluation",
]

FEATURE_COLUMNS = [
    "claim_sk",
    "claim_business_id",
    "numero_sinistre",
    "code_garantie",
    "client_sk",
    "contrat_sk",
    "vehicle_sk",
    "garantie_sk",
    "conducteur_sk",
    "tiers_sk",
    "camtier_sk",
    "claim_geo_sk",
    "claim_date_sk",
    "declaration_date_sk",
    "contract_start_date_sk",
    "claim_date",
    "declaration_date",
    "contract_start_date",
    "claim_amount",
    "client_claim_count_total",
    "client_claim_count_12m",
    "client_claim_count_24m",
    "days_since_previous_claim",
    "client_claim_frequency_band",
    "amount_vs_guarantee_median_ratio",
    "amount_percentile_by_guarantee",
    "high_amount_flag",
    "days_claim_to_declaration",
    "days_contract_start_to_claim",
    "claim_before_contract_start_flag",
    "contract_start_ready_flag",
    "recent_contract_change_flag",
    "recent_guarantee_change_flag",
    "claim_after_recent_update_flag",
    "chronology_ready_flag",
    "missing_keys_count",
    "unknown_dimensions_count",
    "weak_join_flag",
    "migration_2019_flag",
    "missing_client_flag",
    "missing_contract_flag",
    "missing_vehicle_flag",
    "missing_guarantee_flag",
    "missing_geo_flag",
    "missing_driver_flag",
    "missing_third_party_flag",
    "invalid_claim_date_flag",
    "invalid_declaration_date_flag",
    "future_claim_date_flag",
    "vehicle_recurrence_ready_flag",
    "third_party_signal_ready_flag",
    "geo_signal_ready_flag",
    "vhs_signal_ready_flag",
    "confidence_level",
    "scoring_feature_version",
    "feature_run_id",
    "profile_name",
    "source_system",
    "created_at",
]


def is_missing_key(value: object) -> bool:
    """Return True for DWH technical missing keys: NULL, NaN, or <= 0."""
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except TypeError:
        pass
    if isinstance(value, str):
        text_value = value.strip().upper()
        if text_value in {"", "0", "0.0", "NULL", "NAN", "NONE", "UNKNOWN"}:
            return True
        try:
            return float(text_value) <= 0
        except ValueError:
            return False
    try:
        return float(value) <= 0
    except (TypeError, ValueError):
        return False


def date_key_to_timestamp(value: object) -> pd.Timestamp | pd.NaT:
    """Convert an integer YYYYMMDD date key to Timestamp; 0/invalid -> NaT."""
    if is_missing_key(value):
        return pd.NaT
    try:
        numeric_value = int(float(value))
    except (TypeError, ValueError):
        return pd.NaT
    text_value = f"{numeric_value:08d}"
    if len(text_value) != 8:
        return pd.NaT
    return pd.to_datetime(text_value, format="%Y%m%d", errors="coerce")


def date_key_series_to_timestamp(series: pd.Series) -> pd.Series:
    return series.map(date_key_to_timestamp)


def _safe_int_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype("Int64")


def _safe_numeric_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col not in out.columns:
            out[col] = pd.NA
    return out


def normalize_claim_source(df_claims: pd.DataFrame) -> pd.DataFrame:
    """Normalize dwh.fact_sinistre column names into feature-source names."""
    df = _ensure_columns(df_claims, SOURCE_COLUMNS).copy()
    df = df.rename(columns={
        "fact_sinistre_sk": "claim_sk",
        "sinistre_garantie_key": "claim_business_id",
        "vehicule_sk": "vehicle_sk",
        "geo_sinistre_sk": "claim_geo_sk",
        "date_survenance_sk": "claim_date_sk",
        "date_declaration_sk": "declaration_date_sk",
        "montant_evaluation": "claim_amount",
    })
    for col in [
        "claim_sk",
        "client_sk",
        "contrat_sk",
        "vehicle_sk",
        "garantie_sk",
        "conducteur_sk",
        "tiers_sk",
        "camtier_sk",
        "claim_geo_sk",
        "claim_date_sk",
        "declaration_date_sk",
    ]:
        df[col] = _safe_int_series(df[col])
    df["claim_amount"] = _safe_numeric_series(df["claim_amount"])
    df["claim_date"] = date_key_series_to_timestamp(df["claim_date_sk"])
    df["declaration_date"] = date_key_series_to_timestamp(df["declaration_date_sk"])
    return df


def build_contract_start_lookup(df_contracts: pd.DataFrame | None) -> pd.DataFrame:
    """Build earliest nonzero contract start date per contrat_sk."""
    if df_contracts is None or df_contracts.empty:
        return pd.DataFrame(columns=["contrat_sk", "contract_start_date_sk", "contract_start_date"])

    contracts = _ensure_columns(df_contracts, ["contrat_sk", "date_debut_contrat_sk"]).copy()
    contracts["contrat_sk"] = _safe_int_series(contracts["contrat_sk"])
    contracts["date_debut_contrat_sk"] = _safe_int_series(contracts["date_debut_contrat_sk"])
    contracts = contracts[
        ~contracts["contrat_sk"].map(is_missing_key)
        & ~contracts["date_debut_contrat_sk"].map(is_missing_key)
    ].copy()
    if contracts.empty:
        return pd.DataFrame(columns=["contrat_sk", "contract_start_date_sk", "contract_start_date"])

    lookup = (
        contracts
        .groupby("contrat_sk", as_index=False)["date_debut_contrat_sk"]
        .min()
        .rename(columns={"date_debut_contrat_sk": "contract_start_date_sk"})
    )
    lookup["contract_start_date"] = date_key_series_to_timestamp(lookup["contract_start_date_sk"])
    return lookup


def add_contract_start(df: pd.DataFrame, df_contracts: pd.DataFrame | None) -> pd.DataFrame:
    lookup = build_contract_start_lookup(df_contracts)
    out = df.merge(lookup, on="contrat_sk", how="left")
    out["contract_start_date_sk"] = _safe_int_series(out["contract_start_date_sk"]).fillna(0).astype("Int64")
    out["contract_start_date"] = pd.to_datetime(out["contract_start_date"], errors="coerce")
    return out


def compute_client_recurrence(df: pd.DataFrame) -> pd.DataFrame:
    """Compute prior client claims using only claim_date < current claim_date."""
    out = df.copy()
    out["client_claim_count_total"] = pd.Series(0, index=out.index, dtype="Int64")
    out["client_claim_count_12m"] = pd.Series(0, index=out.index, dtype="Int64")
    out["client_claim_count_24m"] = pd.Series(0, index=out.index, dtype="Int64")
    out["days_since_previous_claim"] = pd.Series(pd.NA, index=out.index, dtype="Int64")

    valid = out[
        ~out["client_sk"].map(is_missing_key)
        & out["claim_date"].notna()
    ][["client_sk", "claim_date"]].copy()
    if valid.empty:
        out["client_claim_frequency_band"] = "NO_HISTORY"
        return out

    valid["_row_index"] = valid.index
    for _, group in valid.sort_values(["client_sk", "claim_date", "_row_index"]).groupby("client_sk", sort=False):
        dates = group["claim_date"].dt.normalize().to_numpy(dtype="datetime64[D]")
        current_left = np.searchsorted(dates, dates, side="left")
        cutoff_12 = dates - np.timedelta64(365, "D")
        cutoff_24 = dates - np.timedelta64(730, "D")
        left_12 = np.searchsorted(dates, cutoff_12, side="left")
        left_24 = np.searchsorted(dates, cutoff_24, side="left")

        unique_dates = np.unique(dates)
        previous_positions = np.searchsorted(unique_dates, dates, side="left") - 1
        previous_days = np.full(len(group), np.nan)
        has_previous = previous_positions >= 0
        previous_days[has_previous] = (
            dates[has_previous] - unique_dates[previous_positions[has_previous]]
        ).astype("timedelta64[D]").astype(float)

        row_indexes = group["_row_index"].to_numpy()
        out.loc[row_indexes, "client_claim_count_total"] = current_left
        out.loc[row_indexes, "client_claim_count_12m"] = current_left - left_12
        out.loc[row_indexes, "client_claim_count_24m"] = current_left - left_24
        out.loc[row_indexes, "days_since_previous_claim"] = pd.Series(previous_days, index=row_indexes).astype("Int64")

    out["client_claim_frequency_band"] = pd.cut(
        out["client_claim_count_total"].astype("int64"),
        bins=[-1, 0, 1, 3, math.inf],
        labels=["NO_HISTORY", "ONE_PRIOR", "TWO_TO_THREE_PRIOR", "FOUR_PLUS_PRIOR"],
    ).astype("string")
    return out


def compute_amount_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["amount_vs_guarantee_median_ratio"] = np.nan
    out["amount_percentile_by_guarantee"] = np.nan
    out["high_amount_flag"] = False

    valid = (
        out["claim_amount"].notna()
        & (out["claim_amount"] > 0)
        & out["code_garantie"].notna()
        & out["code_garantie"].astype(str).str.strip().ne("")
    )
    if not valid.any():
        return out

    group_amounts = out.loc[valid].groupby("code_garantie")["claim_amount"]
    medians = group_amounts.transform("median")
    percentiles = group_amounts.rank(method="average", pct=True)
    ratios = out.loc[valid, "claim_amount"] / medians.replace(0, np.nan)

    out.loc[valid, "amount_vs_guarantee_median_ratio"] = ratios
    out.loc[valid, "amount_percentile_by_guarantee"] = percentiles
    out.loc[valid, "high_amount_flag"] = (percentiles >= 0.95) | (ratios >= 3.0)
    return out


def compute_chronology_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["days_claim_to_declaration"] = (
        out["declaration_date"].dt.normalize() - out["claim_date"].dt.normalize()
    ).dt.days.astype("Int64")
    out.loc[out["declaration_date"].isna() | out["claim_date"].isna(), "days_claim_to_declaration"] = pd.NA

    out["days_contract_start_to_claim"] = (
        out["claim_date"].dt.normalize() - out["contract_start_date"].dt.normalize()
    ).dt.days.astype("Int64")
    out.loc[out["claim_date"].isna() | out["contract_start_date"].isna(), "days_contract_start_to_claim"] = pd.NA

    out["claim_before_contract_start_flag"] = out["days_contract_start_to_claim"].lt(0).fillna(False)
    out["contract_start_ready_flag"] = out["contract_start_date"].notna()
    out["recent_contract_change_flag"] = pd.NA
    out["recent_guarantee_change_flag"] = pd.NA
    out["claim_after_recent_update_flag"] = pd.NA
    out["chronology_ready_flag"] = out["claim_date"].notna() & out["declaration_date"].notna()
    return out


def compute_confidence_features(df: pd.DataFrame, as_of_date: date | datetime | None = None) -> pd.DataFrame:
    out = df.copy()
    as_of_ts = pd.Timestamp(as_of_date or datetime.now(timezone.utc).date()).normalize()

    out["missing_client_flag"] = out["client_sk"].map(is_missing_key)
    out["missing_contract_flag"] = out["contrat_sk"].map(is_missing_key)
    out["missing_vehicle_flag"] = out["vehicle_sk"].map(is_missing_key)
    out["missing_guarantee_flag"] = out["garantie_sk"].map(is_missing_key) | out["code_garantie"].isna()
    out["missing_geo_flag"] = out["claim_geo_sk"].map(is_missing_key)
    out["missing_driver_flag"] = out["conducteur_sk"].map(is_missing_key)
    out["missing_third_party_flag"] = out["tiers_sk"].map(is_missing_key)
    out["invalid_claim_date_flag"] = out["claim_date"].isna()
    out["invalid_declaration_date_flag"] = out["declaration_date"].isna()
    out["future_claim_date_flag"] = out["claim_date"].notna() & (out["claim_date"].dt.normalize() > as_of_ts)
    out["migration_2019_flag"] = out["claim_date"].notna() & (out["claim_date"].dt.normalize() < pd.Timestamp("2019-01-01"))

    critical_flags = [
        "missing_client_flag",
        "missing_contract_flag",
        "missing_guarantee_flag",
        "invalid_claim_date_flag",
    ]
    dimension_flags = [
        "missing_client_flag",
        "missing_contract_flag",
        "missing_vehicle_flag",
        "missing_guarantee_flag",
        "missing_geo_flag",
        "missing_driver_flag",
        "missing_third_party_flag",
    ]
    out["missing_keys_count"] = out[critical_flags].astype(int).sum(axis=1).astype("Int64")
    out["unknown_dimensions_count"] = out[dimension_flags].astype(int).sum(axis=1).astype("Int64")
    out["weak_join_flag"] = (
        out["invalid_claim_date_flag"]
        | out["missing_client_flag"]
        | out["missing_contract_flag"]
        | out["missing_guarantee_flag"]
        | (out["missing_keys_count"] >= 2)
    )

    confidence = np.where(
        out["weak_join_flag"] | out["future_claim_date_flag"],
        "LOW",
        np.where(
            (out["missing_keys_count"] > 0)
            | (out["unknown_dimensions_count"] >= 3)
            | out["migration_2019_flag"],
            "MEDIUM",
            "HIGH",
        ),
    )
    out["confidence_level"] = confidence

    out["vehicle_recurrence_ready_flag"] = False
    out["third_party_signal_ready_flag"] = False
    out["geo_signal_ready_flag"] = False
    out["vhs_signal_ready_flag"] = False
    return out


def compute_claim_scoring_features(
    df_claims: pd.DataFrame,
    df_contracts: pd.DataFrame | None = None,
    run_id: str | None = None,
    as_of_date: date | datetime | None = None,
) -> pd.DataFrame:
    """Return one V1 feature row per claim."""
    run_id = run_id or f"{FEATURE_VERSION}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    created_at = datetime.now(timezone.utc).replace(tzinfo=None)

    features = normalize_claim_source(df_claims)
    features = add_contract_start(features, df_contracts)
    features = compute_client_recurrence(features)
    features = compute_amount_features(features)
    features = compute_chronology_features(features)
    features = compute_confidence_features(features, as_of_date=as_of_date)

    features["scoring_feature_version"] = FEATURE_VERSION
    features["feature_run_id"] = run_id
    features["profile_name"] = PROFILE_NAME
    features["source_system"] = "IRIS_CLAIM_ATTENTION"
    features["created_at"] = created_at

    features = features[FEATURE_COLUMNS].copy()
    return _normalize_feature_output_types(features)


def _nullable_int_for_sql(series: pd.Series) -> pd.Series:
    return _safe_int_series(series).astype(object).where(lambda s: s.notna(), None)


def _nullable_float_for_sql(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.astype(object).where(numeric.notna(), None)


def _timestamp_date_for_sql(series: pd.Series) -> pd.Series:
    timestamps = pd.to_datetime(series, errors="coerce")
    return timestamps.dt.date.astype(object).where(timestamps.notna(), None)


def _normalize_feature_output_types(features: pd.DataFrame) -> pd.DataFrame:
    out = features.copy()
    int_cols = [
        "claim_sk",
        "client_sk",
        "contrat_sk",
        "vehicle_sk",
        "garantie_sk",
        "conducteur_sk",
        "tiers_sk",
        "camtier_sk",
        "claim_geo_sk",
        "claim_date_sk",
        "declaration_date_sk",
        "contract_start_date_sk",
        "client_claim_count_total",
        "client_claim_count_12m",
        "client_claim_count_24m",
        "days_since_previous_claim",
        "days_claim_to_declaration",
        "days_contract_start_to_claim",
        "missing_keys_count",
        "unknown_dimensions_count",
    ]
    float_cols = [
        "claim_amount",
        "amount_vs_guarantee_median_ratio",
        "amount_percentile_by_guarantee",
    ]
    date_cols = ["claim_date", "declaration_date", "contract_start_date"]
    bool_cols = [
        "high_amount_flag",
        "claim_before_contract_start_flag",
        "contract_start_ready_flag",
        "chronology_ready_flag",
        "missing_client_flag",
        "missing_contract_flag",
        "missing_vehicle_flag",
        "missing_guarantee_flag",
        "missing_geo_flag",
        "missing_driver_flag",
        "missing_third_party_flag",
        "invalid_claim_date_flag",
        "invalid_declaration_date_flag",
        "future_claim_date_flag",
        "weak_join_flag",
        "migration_2019_flag",
        "vehicle_recurrence_ready_flag",
        "third_party_signal_ready_flag",
        "geo_signal_ready_flag",
        "vhs_signal_ready_flag",
    ]
    nullable_bool_cols = [
        "recent_contract_change_flag",
        "recent_guarantee_change_flag",
        "claim_after_recent_update_flag",
    ]
    for col in int_cols:
        out[col] = _nullable_int_for_sql(out[col])
    for col in float_cols:
        out[col] = _nullable_float_for_sql(out[col])
    for col in date_cols:
        out[col] = _timestamp_date_for_sql(out[col])
    for col in bool_cols:
        out[col] = out[col].fillna(False).astype(bool)
    for col in nullable_bool_cols:
        out[col] = out[col].astype(object).where(out[col].notna(), None)
    return out


def _write_feature_reports(features: pd.DataFrame, source_count: int, run_id: str) -> dict[str, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    summary_path = REPORT_DIR / "claim_scoring_features_summary.md"
    confidence_counts = features["confidence_level"].value_counts(dropna=False).sort_index()
    summary = [
        "# Claim scoring features V1 summary",
        "",
        f"- **Run ID:** `{run_id}`",
        f"- **Feature version:** `{FEATURE_VERSION}`",
        f"- **Source rows:** {source_count}",
        f"- **Feature rows:** {len(features)}",
        f"- **Duplicate claim_sk rows in run:** {int(features['claim_sk'].duplicated().sum())}",
        "",
        "## Confidence distribution",
        "",
        "| Confidence | Rows |",
        "|---|---:|",
    ]
    for level, count in confidence_counts.items():
        summary.append(f"| {level} | {int(count)} |")
    summary.extend([
        "",
        "## V1 scope",
        "",
        "GEO, VHS, vehicle recurrence, and third-party/driver recurrence are carried as readiness flags only.",
        "They do not add attention points in V1.",
    ])
    summary_path.write_text("\n".join(summary) + "\n", encoding="utf-8")
    paths["summary"] = summary_path

    key_quality = pd.DataFrame([{
        "total_rows": len(features),
        "missing_client_count": int(features["missing_client_flag"].sum()),
        "missing_contract_count": int(features["missing_contract_flag"].sum()),
        "missing_vehicle_count": int(features["missing_vehicle_flag"].sum()),
        "missing_guarantee_count": int(features["missing_guarantee_flag"].sum()),
        "missing_geo_count": int(features["missing_geo_flag"].sum()),
        "invalid_claim_date_count": int(features["invalid_claim_date_flag"].sum()),
        "future_claim_date_count": int(features["future_claim_date_flag"].sum()),
        "migration_2019_count": int(features["migration_2019_flag"].sum()),
    }])
    key_path = REPORT_DIR / "claim_scoring_features_key_quality.csv"
    key_quality.to_csv(key_path, index=False)
    paths["key_quality"] = key_path

    confidence_path = REPORT_DIR / "claim_scoring_features_confidence_distribution.csv"
    confidence_counts.rename_axis("confidence_level").reset_index(name="rows").to_csv(confidence_path, index=False)
    paths["confidence_distribution"] = confidence_path

    amount_path = REPORT_DIR / "claim_scoring_features_amount_distribution.csv"
    amount_summary = features[["claim_amount", "amount_vs_guarantee_median_ratio", "amount_percentile_by_guarantee"]].describe(
        percentiles=[0.5, 0.9, 0.95, 0.99]
    ).T
    amount_summary.to_csv(amount_path)
    paths["amount_distribution"] = amount_path

    chronology_path = REPORT_DIR / "claim_scoring_features_chronology_quality.csv"
    chronology = pd.DataFrame([{
        "total_rows": len(features),
        "negative_claim_to_declaration_count": int((pd.to_numeric(features["days_claim_to_declaration"], errors="coerce") < 0).sum()),
        "claim_before_contract_start_count": int(features["claim_before_contract_start_flag"].sum()),
        "contract_start_ready_count": int(features["contract_start_ready_flag"].sum()),
    }])
    chronology.to_csv(chronology_path, index=False)
    paths["chronology_quality"] = chronology_path

    return paths


def _read_claim_source(engine) -> pd.DataFrame:
    # IRIS est scope automobile (regle AUTO_SCOPE_001, deja calculee dans
    # staging.stg_sinistres.is_auto_scope a partir du produit reel du contrat,
    # plus fiable que le codfam declare sur la ligne sinistre). Sans ce filtre,
    # les sinistres hors auto (sante "MALA", transport, etc.) fuient dans tout
    # le pipeline de scoring et jusque dans l'application.
    # is_auto_scope est calcule au niveau sinistre (un seul valeur par numsnt) ;
    # bool_or + GROUP BY dedoublonne le cote multi-garantie de stg_sinistres
    # pour eviter un fan-out du JOIN.
    cols = ", ".join(f"f.{c}" for c in SOURCE_COLUMNS)
    query = text(f"""
        SELECT {cols}
        FROM dwh.fact_sinistre f
        JOIN (
            SELECT UPPER(TRIM(numsnt)) AS numero_sinistre, bool_or(is_auto_scope) AS is_auto_scope
            FROM staging.stg_sinistres
            GROUP BY 1
        ) scope ON scope.numero_sinistre = f.numero_sinistre
        WHERE scope.is_auto_scope
    """)
    with engine.connect() as conn:
        return pd.read_sql(query, conn)


def _read_contract_source(engine) -> pd.DataFrame:
    query = text("""
        SELECT contrat_sk, date_debut_contrat_sk
        FROM dwh.fact_contrat
    """)
    with engine.connect() as conn:
        return pd.read_sql(query, conn)


def compute_claim_scoring_features_v1():
    if text is None:
        raise RuntimeError("SQLAlchemy is required to write mart.fact_claim_scoring_features.")
    dwh_utils = _load_dwh_utils()

    today = datetime.now(timezone.utc).replace(tzinfo=None)
    run_id = f"{FEATURE_VERSION}_{today.strftime('%Y%m%d_%H%M%S')}"
    logger = dwh_utils.setup_logging(run_id, log_name="compute_claim_scoring_features_v1")
    logger.info("=" * 70)
    logger.info(f"[RUN] {run_id}")
    logger.info(f"      profile={PROFILE_NAME} version={FEATURE_VERSION}")
    logger.info("      attention/prioritization features only; no fraud decision")
    logger.info("=" * 70)

    engine = dwh_utils.build_engine(logger)
    with engine.begin() as conn:
        conn.execute(text(DDL_CREATE_SCHEMA))
        conn.execute(text(DDL_FACT_CLAIM_SCORING_FEATURES))
    logger.info("DDL ensured for mart.fact_claim_scoring_features")

    df_claims = _read_claim_source(engine)
    df_contracts = _read_contract_source(engine)
    logger.info(f"fact_sinistre rows loaded: {len(df_claims)}")
    logger.info(f"fact_contrat rows loaded : {len(df_contracts)}")

    features = compute_claim_scoring_features(df_claims, df_contracts, run_id=run_id, as_of_date=today.date())
    logger.info(f"feature rows computed    : {len(features)}")
    logger.info(f"duplicate claim_sk rows  : {int(features['claim_sk'].duplicated().sum())}")

    with engine.begin() as conn:
        conn.execute(text("""
            DELETE FROM mart.fact_claim_scoring_features
            WHERE scoring_feature_version = :version
              AND feature_run_id = :run_id
        """), {"version": FEATURE_VERSION, "run_id": run_id})
        features.to_sql(
            "fact_claim_scoring_features",
            conn,
            schema="mart",
            if_exists="append",
            index=False,
            chunksize=5000,
            method="multi",
        )
    logger.info(f"inserted -> mart.fact_claim_scoring_features: {len(features)} rows")

    report_paths = _write_feature_reports(features, source_count=len(df_claims), run_id=run_id)
    for name, path in report_paths.items():
        logger.info(f"report {name}: {path}")

    print("=" * 70)
    print(f"  run_id                  : {run_id}")
    print(f"  source fact_sinistre rows: {len(df_claims)}")
    print(f"  feature rows             : {len(features)}")
    print(f"  duplicate claim_sk rows   : {int(features['claim_sk'].duplicated().sum())}")
    print(f"  report folder             : {REPORT_DIR}")
    print("=" * 70)
    return features


if __name__ == "__main__":
    compute_claim_scoring_features_v1()


