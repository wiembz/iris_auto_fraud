"""
etl/mart/compute_post_inspection_attention_signal_v1_candidate.py
=================================================================
Builds the post-inspection attention signal mart candidate.

The mart is an explainable prioritization aid for human claim review. It does
not prove fraud, does not make an automatic decision, and is not integrated
into Claim Attention Score V1.

Scenario implemented:
  A_INSPECTION_TO_CLAIM

Sources:
  dwh.fact_inspection_vehicule
  dwh.fact_inspection_checkpoint
  dwh.fact_sinistre

Output:
  mart.fact_post_inspection_attention_signal
  data/quality_reports/scoring/post_inspection_signals/v1_candidate/
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from sqlalchemy import text
except ModuleNotFoundError:  # Allows pure unit tests without DB dependencies.
    text = None


BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dwh"))


def _load_dwh_utils():
    import dwh_utils
    return dwh_utils


SIGNAL_VERSION = "IRIS_POST_INSPECTION_SIGNAL_V1_CANDIDATE"
PROFILE_NAME = "POST_INSPECTION_SIGNAL_V1_CANDIDATE"
SCENARIO_A_CODE = "A_INSPECTION_TO_CLAIM"
SCENARIO_A_LABEL = "Inspection STAFFIM -> sinistre"

REPORT_DIR = BASE_DIR / "data" / "quality_reports" / "scoring" / "post_inspection_signals" / "v1_candidate"

DDL_CREATE_SCHEMA = "CREATE SCHEMA IF NOT EXISTS mart;"

DDL_FACT_POST_INSPECTION_ATTENTION_SIGNAL = """
CREATE TABLE IF NOT EXISTS mart.fact_post_inspection_attention_signal (
    post_inspection_signal_sk       BIGSERIAL PRIMARY KEY,
    signal_run_id                   TEXT NOT NULL,
    signal_version                  TEXT NOT NULL,
    scenario_code                   TEXT NOT NULL,
    scenario_label                  TEXT NOT NULL,
    inspection_sk                   BIGINT NOT NULL,
    claim_sk                        BIGINT NOT NULL,
    contract_sk                     BIGINT,
    client_sk                       BIGINT,
    vehicule_sk                     BIGINT NOT NULL,
    immatriculation                 TEXT,
    inspection_date                 DATE NOT NULL,
    claim_date                      DATE NOT NULL,
    avenant_date                    DATE,
    days_inspection_to_claim        INTEGER NOT NULL,
    days_inspection_to_avenant      INTEGER,
    delay_bucket                    TEXT NOT NULL,
    defective_zone                  TEXT NOT NULL,
    defective_checkpoint_count      INTEGER NOT NULL,
    critical_checkpoint_count       INTEGER NOT NULL,
    defective_checkpoint_codes      TEXT,
    representative_checkpoint_labels TEXT,
    claim_area                      TEXT,
    claim_guarantee_code            TEXT,
    claim_guarantee_label           TEXT,
    zone_match_status               TEXT NOT NULL,
    linkage_method                  TEXT NOT NULL,
    attention_level                 TEXT NOT NULL,
    confidence_level                TEXT NOT NULL,
    business_explanation            TEXT NOT NULL,
    profile_name                    TEXT NOT NULL,
    created_at                      TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_post_inspection_signal_run UNIQUE
        (signal_run_id, signal_version, scenario_code, inspection_sk, claim_sk, defective_zone)
);
"""

SIGNAL_COLUMNS = [
    "signal_run_id",
    "signal_version",
    "scenario_code",
    "scenario_label",
    "inspection_sk",
    "claim_sk",
    "contract_sk",
    "client_sk",
    "vehicule_sk",
    "immatriculation",
    "inspection_date",
    "claim_date",
    "avenant_date",
    "days_inspection_to_claim",
    "days_inspection_to_avenant",
    "delay_bucket",
    "defective_zone",
    "defective_checkpoint_count",
    "critical_checkpoint_count",
    "defective_checkpoint_codes",
    "representative_checkpoint_labels",
    "claim_area",
    "claim_guarantee_code",
    "claim_guarantee_label",
    "zone_match_status",
    "linkage_method",
    "attention_level",
    "confidence_level",
    "business_explanation",
    "profile_name",
    "created_at",
]

GRAIN_COLUMNS = [
    "signal_run_id",
    "signal_version",
    "scenario_code",
    "inspection_sk",
    "claim_sk",
    "defective_zone",
]

NON_ACCUSATORY_BLOCKLIST = (
    "fraud detected",
    "fraudulent",
    "proof of fraud",
    "fraude detectee",
    "fraude confirmee",
    "client fraudeur",
)


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


def _ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col not in out.columns:
            out[col] = pd.NA
    return out


def delay_bucket(days: object) -> str | None:
    try:
        days_int = int(days)
    except (TypeError, ValueError):
        return None
    if 0 <= days_int <= 7:
        return "DAYS_0_7"
    if 8 <= days_int <= 30:
        return "DAYS_8_30"
    if 31 <= days_int <= 90:
        return "DAYS_31_90"
    return None


def confidence_level(days: object, defective_checkpoint_count: object, defective_zone: object) -> str:
    try:
        days_int = int(days)
    except (TypeError, ValueError):
        return "LOW"
    try:
        defect_count = int(defective_checkpoint_count)
    except (TypeError, ValueError):
        defect_count = 0
    zone_text = "" if defective_zone is None or pd.isna(defective_zone) else str(defective_zone).strip()
    has_zone = bool(zone_text) and zone_text != "NO_DOCUMENTED_ANOMALY"
    has_documented_anomaly = defect_count > 0 and has_zone

    if has_documented_anomaly and 0 <= days_int <= 30:
        return "HIGH"
    if has_documented_anomaly and 31 <= days_int <= 90:
        return "MEDIUM"
    return "LOW"


def attention_level(confidence: object) -> str:
    if confidence == "HIGH":
        return "Verification prioritaire suggeree"
    if confidence == "MEDIUM":
        return "Signal post-inspection a examiner"
    return "Contexte technique documente"


def business_explanation(confidence: object, has_documented_anomaly: bool) -> str:
    if confidence in {"HIGH", "MEDIUM"} and has_documented_anomaly:
        return (
            "Un sinistre est survenu peu apres une inspection STAFFIM du meme vehicule. "
            "Des elements techniques documentes peuvent justifier une verification prioritaire."
        )
    return (
        "Un sinistre est survenu apres une inspection STAFFIM du meme vehicule. "
        "Le contexte technique est disponible pour aide a l'analyse."
    )


def contains_accusatory_wording(text_value: object) -> bool:
    text_lower = str(text_value or "").lower()
    return any(term in text_lower for term in NON_ACCUSATORY_BLOCKLIST)


def aggregate_checkpoint_anomalies(checkpoints: pd.DataFrame) -> pd.DataFrame:
    """Aggregate documented inspection anomalies by inspection key and zone."""
    required = [
        "inspection_key",
        "zone_controle",
        "checkpoint_code",
        "checkpoint_libelle",
        "est_anomalie",
        "est_anomalie_critique",
    ]
    cp = _ensure_columns(checkpoints, required).copy()
    if cp.empty:
        return pd.DataFrame(columns=[
            "inspection_key",
            "defective_zone",
            "defective_checkpoint_count",
            "critical_checkpoint_count",
            "defective_checkpoint_codes",
            "representative_checkpoint_labels",
        ])

    anomalies = cp[cp["est_anomalie"].eq(True)].copy()
    if anomalies.empty:
        return pd.DataFrame(columns=[
            "inspection_key",
            "defective_zone",
            "defective_checkpoint_count",
            "critical_checkpoint_count",
            "defective_checkpoint_codes",
            "representative_checkpoint_labels",
        ])

    anomalies["defective_zone"] = anomalies["zone_controle"].fillna("UNKNOWN_ZONE").astype(str)
    anomalies["checkpoint_code"] = anomalies["checkpoint_code"].astype("string")
    anomalies["checkpoint_libelle"] = anomalies["checkpoint_libelle"].astype("string")
    anomalies["_critical"] = anomalies["est_anomalie_critique"].eq(True).astype(int)

    def _join_values(series: pd.Series, limit: int = 12) -> str:
        values = [str(value) for value in series.dropna().astype(str).unique() if str(value).strip()]
        return "; ".join(values[:limit])

    grouped = (
        anomalies
        .groupby(["inspection_key", "defective_zone"], dropna=False)
        .agg(
            defective_checkpoint_count=("checkpoint_code", "size"),
            critical_checkpoint_count=("_critical", "sum"),
            defective_checkpoint_codes=("checkpoint_code", _join_values),
            representative_checkpoint_labels=("checkpoint_libelle", _join_values),
        )
        .reset_index()
    )
    return grouped


def _normalize_inspections(inspections: pd.DataFrame) -> pd.DataFrame:
    source = _ensure_columns(inspections, [
        "fact_inspection_vehicule_sk",
        "inspection_sk",
        "inspection_key",
        "vehicule_sk",
        "date_inspection_sk",
        "immatriculation_norm",
    ]).copy()
    if source["inspection_sk"].isna().all():
        source["inspection_sk"] = source["fact_inspection_vehicule_sk"]
    source = source.rename(columns={"immatriculation_norm": "immatriculation"})
    source["inspection_sk"] = _safe_int_series(source["inspection_sk"])
    source["vehicule_sk"] = _safe_int_series(source["vehicule_sk"])
    source["date_inspection_sk"] = _safe_int_series(source["date_inspection_sk"])
    source["inspection_date"] = date_key_series_to_timestamp(source["date_inspection_sk"])
    return source[["inspection_sk", "inspection_key", "vehicule_sk", "date_inspection_sk", "inspection_date", "immatriculation"]]


def _normalize_claims(claims: pd.DataFrame) -> pd.DataFrame:
    source = _ensure_columns(claims, [
        "fact_sinistre_sk",
        "claim_sk",
        "sinistre_garantie_key",
        "contract_sk",
        "client_sk",
        "vehicule_sk",
        "date_survenance_sk",
        "code_garantie",
        "motif_cloture_garantie",
        "etat_garantie_sinistre",
    ]).copy()
    if source["claim_sk"].isna().all():
        source["claim_sk"] = source["fact_sinistre_sk"]
    source["claim_sk"] = _safe_int_series(source["claim_sk"])
    source["contract_sk"] = _safe_int_series(source["contrat_sk"])
    source["client_sk"] = _safe_int_series(source["client_sk"])
    source["vehicule_sk"] = _safe_int_series(source["vehicule_sk"])
    source["date_survenance_sk"] = _safe_int_series(source["date_survenance_sk"])
    source["claim_date"] = date_key_series_to_timestamp(source["date_survenance_sk"])
    source["claim_guarantee_code"] = source["code_garantie"]
    source["claim_guarantee_label"] = pd.NA
    source["claim_area"] = pd.NA
    return source[[
        "claim_sk",
        "sinistre_garantie_key",
        "contract_sk",
        "client_sk",
        "vehicule_sk",
        "date_survenance_sk",
        "claim_date",
        "claim_area",
        "claim_guarantee_code",
        "claim_guarantee_label",
    ]]


def _candidate_exclusion_summary(inspections: pd.DataFrame, claims: pd.DataFrame, joined: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {
            "exclusion_reason": "INSPECTION_MISSING_VEHICULE_SK",
            "rows": int(inspections["vehicule_sk"].map(is_missing_key).sum()),
        },
        {
            "exclusion_reason": "CLAIM_MISSING_VEHICULE_SK",
            "rows": int(claims["vehicule_sk"].map(is_missing_key).sum()),
        },
        {
            "exclusion_reason": "INSPECTION_INVALID_DATE",
            "rows": int(joined["inspection_date"].isna().sum()) if "inspection_date" in joined else 0,
        },
        {
            "exclusion_reason": "CLAIM_INVALID_DATE",
            "rows": int(joined["claim_date"].isna().sum()) if "claim_date" in joined else 0,
        },
        {
            "exclusion_reason": "CLAIM_BEFORE_INSPECTION",
            "rows": int((joined["days_inspection_to_claim"] < 0).sum()) if "days_inspection_to_claim" in joined else 0,
        },
        {
            "exclusion_reason": "DELAY_OVER_90_DAYS",
            "rows": int((joined["days_inspection_to_claim"] > 90).sum()) if "days_inspection_to_claim" in joined else 0,
        },
    ]
    return pd.DataFrame(rows)


def compute_post_inspection_signals(
    inspections: pd.DataFrame,
    checkpoints: pd.DataFrame,
    claims: pd.DataFrame,
    signal_run_id: str | None = None,
    created_at: datetime | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Compute Scenario A post-inspection attention signals."""
    signal_run_id = signal_run_id or f"{SIGNAL_VERSION}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    created_at = created_at or datetime.now(timezone.utc).replace(tzinfo=None)

    norm_inspections = _normalize_inspections(inspections)
    norm_claims = _normalize_claims(claims)
    anomaly_by_zone = aggregate_checkpoint_anomalies(checkpoints)

    ready_inspections = norm_inspections[~norm_inspections["vehicule_sk"].map(is_missing_key)].copy()
    ready_claims = norm_claims[~norm_claims["vehicule_sk"].map(is_missing_key)].copy()

    joined = ready_inspections.merge(
        ready_claims,
        on="vehicule_sk",
        how="inner",
        suffixes=("_inspection", "_claim"),
    )
    if not joined.empty:
        joined["days_inspection_to_claim"] = (
            joined["claim_date"].dt.normalize() - joined["inspection_date"].dt.normalize()
        ).dt.days.astype("Int64")
    else:
        joined["days_inspection_to_claim"] = pd.Series(dtype="Int64")

    valid = joined[
        joined["inspection_date"].notna()
        & joined["claim_date"].notna()
        & joined["days_inspection_to_claim"].between(0, 90)
    ].copy()

    signals = valid.merge(anomaly_by_zone, on="inspection_key", how="left")
    missing_anomaly = signals["defective_zone"].isna()
    signals.loc[missing_anomaly, "defective_zone"] = "NO_DOCUMENTED_ANOMALY"
    signals.loc[missing_anomaly, "defective_checkpoint_count"] = 0
    signals.loc[missing_anomaly, "critical_checkpoint_count"] = 0
    signals.loc[missing_anomaly, "defective_checkpoint_codes"] = ""
    signals.loc[missing_anomaly, "representative_checkpoint_labels"] = ""

    if signals.empty:
        empty = pd.DataFrame(columns=SIGNAL_COLUMNS)
        validation = validate_signal_outputs(empty)
        validation.update({
            "source_inspection_rows": int(len(norm_inspections)),
            "source_claim_rows": int(len(norm_claims)),
            "joined_vehicle_pairs": int(len(joined)),
            "valid_0_90_pairs": int(len(valid)),
            "excluded_candidates": _candidate_exclusion_summary(norm_inspections, norm_claims, joined),
        })
        return empty, validation

    signals["delay_bucket"] = signals["days_inspection_to_claim"].map(delay_bucket)
    signals["confidence_level"] = signals.apply(
        lambda row: confidence_level(
            row["days_inspection_to_claim"],
            row["defective_checkpoint_count"],
            row["defective_zone"],
        ),
        axis=1,
    )
    signals["attention_level"] = signals["confidence_level"].map(attention_level)
    signals["scenario_code"] = SCENARIO_A_CODE
    signals["scenario_label"] = SCENARIO_A_LABEL
    signals["signal_version"] = SIGNAL_VERSION
    signals["signal_run_id"] = signal_run_id
    signals["avenant_date"] = pd.NaT
    signals["days_inspection_to_avenant"] = pd.NA
    signals["zone_match_status"] = "NOT_ASSESSED"
    signals["linkage_method"] = "VEHICULE_SK"
    signals["profile_name"] = PROFILE_NAME
    signals["created_at"] = created_at
    signals["business_explanation"] = signals.apply(
        lambda row: business_explanation(
            row["confidence_level"],
            int(row["defective_checkpoint_count"]) > 0,
        ),
        axis=1,
    )

    signals = signals[SIGNAL_COLUMNS].copy()
    signals = _normalize_signal_output_types(signals)
    validation = validate_signal_outputs(signals)
    validation.update({
        "source_inspection_rows": int(len(norm_inspections)),
        "source_claim_rows": int(len(norm_claims)),
        "joined_vehicle_pairs": int(len(joined)),
        "valid_0_90_pairs": int(len(valid)),
        "excluded_candidates": _candidate_exclusion_summary(norm_inspections, norm_claims, joined),
    })
    return signals, validation


def _nullable_int_for_sql(series: pd.Series) -> pd.Series:
    values = _safe_int_series(series)
    return values.astype(object).where(values.notna(), None)


def _timestamp_date_for_sql(series: pd.Series) -> pd.Series:
    timestamps = pd.to_datetime(series, errors="coerce")
    return timestamps.dt.date.astype(object).where(timestamps.notna(), None)


def _normalize_signal_output_types(signals: pd.DataFrame) -> pd.DataFrame:
    out = signals.copy()
    int_cols = [
        "inspection_sk",
        "claim_sk",
        "contract_sk",
        "client_sk",
        "vehicule_sk",
        "days_inspection_to_claim",
        "days_inspection_to_avenant",
        "defective_checkpoint_count",
        "critical_checkpoint_count",
    ]
    date_cols = ["inspection_date", "claim_date", "avenant_date"]
    for col in int_cols:
        out[col] = _nullable_int_for_sql(out[col])
    for col in date_cols:
        out[col] = _timestamp_date_for_sql(out[col])
    for col in SIGNAL_COLUMNS:
        if col not in out.columns:
            out[col] = None
    return out[SIGNAL_COLUMNS].copy()


def validate_signal_outputs(signals: pd.DataFrame) -> dict[str, int]:
    if signals.empty:
        return {
            "signal_rows": 0,
            "duplicate_grain_rows": 0,
            "negative_delay_rows": 0,
            "delay_over_90_rows": 0,
            "missing_vehicle_rows": 0,
            "null_level_rows": 0,
            "null_explanation_rows": 0,
            "accusatory_wording_rows": 0,
        }

    delay = pd.to_numeric(signals["days_inspection_to_claim"], errors="coerce")
    return {
        "signal_rows": int(len(signals)),
        "duplicate_grain_rows": int(signals.duplicated(GRAIN_COLUMNS).sum()),
        "negative_delay_rows": int((delay < 0).sum()),
        "delay_over_90_rows": int((delay > 90).sum()),
        "missing_vehicle_rows": int(signals["vehicule_sk"].map(is_missing_key).sum()),
        "null_level_rows": int(signals["attention_level"].isna().sum() + signals["confidence_level"].isna().sum()),
        "null_explanation_rows": int(signals["business_explanation"].isna().sum() + signals["business_explanation"].astype(str).str.strip().eq("").sum()),
        "accusatory_wording_rows": int(signals["business_explanation"].map(contains_accusatory_wording).sum()),
    }


def _distribution(df: pd.DataFrame, column: str) -> pd.DataFrame:
    if df.empty or column not in df:
        return pd.DataFrame(columns=[column, "rows"])
    return df[column].value_counts(dropna=False).sort_index().rename_axis(column).reset_index(name="rows")


def _write_signal_reports(signals: pd.DataFrame, validation: dict[str, Any], signal_run_id: str) -> dict[str, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    load_summary = pd.DataFrame([{
        "signal_run_id": signal_run_id,
        "signal_version": SIGNAL_VERSION,
        "source_inspection_rows": validation.get("source_inspection_rows", 0),
        "source_claim_rows": validation.get("source_claim_rows", 0),
        "joined_vehicle_pairs": validation.get("joined_vehicle_pairs", 0),
        "valid_0_90_pairs": validation.get("valid_0_90_pairs", 0),
        "signal_rows": validation.get("signal_rows", 0),
        "duplicate_grain_rows": validation.get("duplicate_grain_rows", 0),
    }])
    path = REPORT_DIR / "post_inspection_signal_load_summary.csv"
    load_summary.to_csv(path, index=False, encoding="utf-8-sig")
    paths["load_summary"] = path

    duplicates = (
        signals.loc[signals.duplicated(GRAIN_COLUMNS, keep=False), GRAIN_COLUMNS + ["days_inspection_to_claim", "confidence_level"]]
        if not signals.empty
        else pd.DataFrame(columns=GRAIN_COLUMNS + ["days_inspection_to_claim", "confidence_level"])
    )
    path = REPORT_DIR / "post_inspection_duplicate_grain_check.csv"
    duplicates.to_csv(path, index=False, encoding="utf-8-sig")
    paths["duplicate_grain_check"] = path

    for filename, column, key in [
        ("post_inspection_delay_distribution.csv", "delay_bucket", "delay_distribution"),
        ("post_inspection_confidence_distribution.csv", "confidence_level", "confidence_distribution"),
        ("post_inspection_zone_distribution.csv", "defective_zone", "zone_distribution"),
    ]:
        path = REPORT_DIR / filename
        _distribution(signals, column).to_csv(path, index=False, encoding="utf-8-sig")
        paths[key] = path

    excluded = validation.get("excluded_candidates")
    if not isinstance(excluded, pd.DataFrame):
        excluded = pd.DataFrame(columns=["exclusion_reason", "rows"])
    path = REPORT_DIR / "post_inspection_excluded_candidates.csv"
    excluded.to_csv(path, index=False, encoding="utf-8-sig")
    paths["excluded_candidates"] = path

    validation_rows = {k: v for k, v in validation.items() if not isinstance(v, pd.DataFrame)}
    validation_df = pd.DataFrame([validation_rows])
    path = REPORT_DIR / "post_inspection_validation_summary.csv"
    validation_df.to_csv(path, index=False, encoding="utf-8-sig")
    paths["validation_summary_csv"] = path

    md_lines = [
        "# Post-inspection signal V1 candidate validation summary",
        "",
        f"- **Run ID:** `{signal_run_id}`",
        f"- **Signal version:** `{SIGNAL_VERSION}`",
        f"- **Scenario implemented:** `{SCENARIO_A_CODE}`",
        f"- **Signal rows:** {validation.get('signal_rows', 0)}",
        f"- **Duplicate grain rows:** {validation.get('duplicate_grain_rows', 0)}",
        f"- **Negative delay rows:** {validation.get('negative_delay_rows', 0)}",
        f"- **Delay over 90 rows:** {validation.get('delay_over_90_rows', 0)}",
        f"- **Missing vehicle rows:** {validation.get('missing_vehicle_rows', 0)}",
        f"- **Null level rows:** {validation.get('null_level_rows', 0)}",
        f"- **Null explanation rows:** {validation.get('null_explanation_rows', 0)}",
        "",
        "Scenario B remains PARTIAL/readiness-only and is not written as a business signal in this candidate.",
        "This output is for prioritization support only and does not modify Claim Attention Score V1 or VHS.",
    ]
    path = REPORT_DIR / "post_inspection_validation_summary.md"
    path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    paths["validation_summary_md"] = path
    return paths


def _read_inspections(engine) -> pd.DataFrame:
    query = text("""
        SELECT
            fact_inspection_vehicule_sk,
            inspection_key,
            vehicule_sk,
            date_inspection_sk,
            immatriculation_norm
        FROM dwh.fact_inspection_vehicule
    """)
    with engine.connect() as conn:
        return pd.read_sql(query, conn)


def _read_checkpoints(engine) -> pd.DataFrame:
    query = text("""
        SELECT
            inspection_key,
            zone_controle,
            checkpoint_code,
            checkpoint_libelle,
            est_anomalie,
            est_anomalie_critique
        FROM dwh.fact_inspection_checkpoint
    """)
    with engine.connect() as conn:
        return pd.read_sql(query, conn)


def _read_claims(engine) -> pd.DataFrame:
    query = text("""
        SELECT
            fact_sinistre_sk,
            sinistre_garantie_key,
            contrat_sk,
            client_sk,
            vehicule_sk,
            date_survenance_sk,
            code_garantie,
            motif_cloture_garantie,
            etat_garantie_sinistre
        FROM dwh.fact_sinistre
    """)
    with engine.connect() as conn:
        return pd.read_sql(query, conn)


def compute_post_inspection_attention_signal_v1_candidate() -> pd.DataFrame:
    if text is None:
        raise RuntimeError("SQLAlchemy is required to write mart.fact_post_inspection_attention_signal.")
    dwh_utils = _load_dwh_utils()

    today = datetime.now(timezone.utc).replace(tzinfo=None)
    signal_run_id = f"{SIGNAL_VERSION}_{today.strftime('%Y%m%d_%H%M%S')}"
    logger = dwh_utils.setup_logging(signal_run_id, log_name="compute_post_inspection_attention_signal_v1_candidate")
    logger.info("=" * 70)
    logger.info(f"[RUN] {signal_run_id}")
    logger.info(f"      profile={PROFILE_NAME} version={SIGNAL_VERSION}")
    logger.info("      post-inspection prioritization signals only; no automatic decision")
    logger.info("=" * 70)

    engine = dwh_utils.build_engine(logger)
    with engine.begin() as conn:
        conn.execute(text(DDL_CREATE_SCHEMA))
        conn.execute(text(DDL_FACT_POST_INSPECTION_ATTENTION_SIGNAL))
    logger.info("DDL ensured for mart.fact_post_inspection_attention_signal")

    inspections = _read_inspections(engine)
    checkpoints = _read_checkpoints(engine)
    claims = _read_claims(engine)
    logger.info(f"fact_inspection_vehicule rows loaded : {len(inspections)}")
    logger.info(f"fact_inspection_checkpoint rows loaded: {len(checkpoints)}")
    logger.info(f"fact_sinistre rows loaded             : {len(claims)}")

    signals, validation = compute_post_inspection_signals(
        inspections,
        checkpoints,
        claims,
        signal_run_id=signal_run_id,
        created_at=today,
    )
    logger.info(f"signals computed      : {len(signals)}")
    logger.info(f"validation            : { {k: v for k, v in validation.items() if not isinstance(v, pd.DataFrame)} }")

    with engine.begin() as conn:
        conn.execute(text("""
            DELETE FROM mart.fact_post_inspection_attention_signal
            WHERE signal_version = :signal_version
              AND signal_run_id = :signal_run_id
        """), {"signal_version": SIGNAL_VERSION, "signal_run_id": signal_run_id})
        if not signals.empty:
            signals.to_sql(
                "fact_post_inspection_attention_signal",
                conn,
                schema="mart",
                if_exists="append",
                index=False,
                chunksize=5000,
                method="multi",
            )
    logger.info(f"inserted -> mart.fact_post_inspection_attention_signal: {len(signals)} rows")

    report_paths = _write_signal_reports(signals, validation, signal_run_id)
    for name, path in report_paths.items():
        logger.info(f"report {name}: {path}")

    delay_dist = _distribution(signals, "delay_bucket")
    confidence_dist = _distribution(signals, "confidence_level")
    zone_dist = _distribution(signals, "defective_zone")

    print("=" * 70)
    print(f"  signal_run_id          : {signal_run_id}")
    print(f"  signal_version         : {SIGNAL_VERSION}")
    print(f"  mart rows              : {len(signals)}")
    print(f"  duplicate grain rows   : {validation.get('duplicate_grain_rows', 0)}")
    print(f"  report folder          : {REPORT_DIR}")
    print("  delay distribution:")
    print(delay_dist.to_string(index=False) if not delay_dist.empty else "  <empty>")
    print("  confidence distribution:")
    print(confidence_dist.to_string(index=False) if not confidence_dist.empty else "  <empty>")
    print("  zone distribution:")
    print(zone_dist.to_string(index=False) if not zone_dist.empty else "  <empty>")
    print(f"  validation             : { {k: v for k, v in validation.items() if not isinstance(v, pd.DataFrame)} }")
    print("=" * 70)
    return signals


if __name__ == "__main__":
    compute_post_inspection_attention_signal_v1_candidate()
