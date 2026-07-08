"""
etl/mart/compute_claim_attention_score_v1_candidate.py
======================================================
Computes the Claim Attention Score V1 candidate.

The score is an explainable prioritization aid for claim review. It is not a
fraud proof, not a legal conclusion, and not an automatic decision.

Source:
  mart.fact_claim_scoring_features

Outputs:
  mart.fact_claim_attention_score
  mart.fact_claim_attention_signal_detail
  data/quality_reports/scoring/claim_attention_v1/
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from sqlalchemy import text
except ModuleNotFoundError:  # Allows pure scoring tests without DB dependencies.
    text = None

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dwh"))

from etl.mart.compute_claim_scoring_features_v1 import FEATURE_VERSION


def _load_dwh_utils():
    import dwh_utils
    return dwh_utils


REPORT_DIR = BASE_DIR / "data" / "quality_reports" / "scoring" / "claim_attention_v1"

SCORE_VERSION = "IRIS_CLAIM_ATTENTION_V1_CANDIDATE"
PROFILE_NAME = "CLAIM_ATTENTION_SCORE_V1_CANDIDATE"

DDL_CREATE_SCHEMA = "CREATE SCHEMA IF NOT EXISTS mart;"

DDL_FACT_CLAIM_ATTENTION_SCORE = """
CREATE TABLE IF NOT EXISTS mart.fact_claim_attention_score (
    claim_attention_score_sk BIGSERIAL PRIMARY KEY,
    claim_sk                 BIGINT NOT NULL,
    claim_business_id        TEXT,
    score_version            TEXT NOT NULL,
    score_run_id             TEXT NOT NULL,
    feature_run_id           TEXT,
    attention_score          INTEGER NOT NULL,
    attention_level          TEXT NOT NULL,
    confidence_level         TEXT NOT NULL,
    main_reason_1            TEXT,
    main_reason_2            TEXT,
    main_reason_3            TEXT,
    profile_name             TEXT NOT NULL,
    source_system            TEXT DEFAULT 'IRIS_CLAIM_ATTENTION',
    created_at               TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_claim_attention_score_run UNIQUE
        (claim_sk, score_version, score_run_id)
);
"""

DDL_FACT_CLAIM_ATTENTION_SIGNAL_DETAIL = """
CREATE TABLE IF NOT EXISTS mart.fact_claim_attention_signal_detail (
    signal_detail_sk     BIGSERIAL PRIMARY KEY,
    claim_sk             BIGINT NOT NULL,
    claim_business_id    TEXT,
    score_run_id         TEXT NOT NULL,
    score_version        TEXT NOT NULL,
    signal_family        TEXT NOT NULL,
    signal_code          TEXT NOT NULL,
    signal_label         TEXT NOT NULL,
    signal_value         TEXT,
    points               INTEGER NOT NULL,
    severity             TEXT NOT NULL,
    business_explanation TEXT NOT NULL,
    profile_name         TEXT NOT NULL,
    created_at           TIMESTAMP DEFAULT NOW()
);
"""

SCORE_COLUMNS = [
    "claim_sk",
    "claim_business_id",
    "score_version",
    "score_run_id",
    "feature_run_id",
    "attention_score",
    "attention_level",
    "confidence_level",
    "main_reason_1",
    "main_reason_2",
    "main_reason_3",
    "profile_name",
    "source_system",
    "created_at",
]

DETAIL_COLUMNS = [
    "claim_sk",
    "claim_business_id",
    "score_run_id",
    "score_version",
    "signal_family",
    "signal_code",
    "signal_label",
    "signal_value",
    "points",
    "severity",
    "business_explanation",
    "profile_name",
    "created_at",
]


def _is_true(value: Any) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except TypeError:
        pass
    if isinstance(value, str):
        return value.strip().upper() in {"TRUE", "T", "YES", "Y", "1", "O", "OUI"}
    return bool(value)


def _num(value: Any, default: float = np.nan) -> float:
    try:
        if value is None or pd.isna(value):
            return default
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    number = _num(value, np.nan)
    if np.isnan(number):
        return default
    return int(number)


def attention_level(score: int | float) -> str:
    score_int = int(max(0, min(100, round(float(score)))))
    if score_int <= 24:
        return "Analyse standard"
    if score_int <= 49:
        return "Points a verifier"
    if score_int <= 74:
        return "Examen renforce suggere"
    return "Examen prioritaire suggere"


def _severity(points: int) -> str:
    if points >= 15:
        return "HIGH"
    if points >= 8:
        return "MEDIUM"
    if points > 0:
        return "LOW"
    return "INFO"


def _signal(
    family: str,
    code: str,
    label: str,
    value: Any,
    points: int,
    explanation: str,
) -> dict[str, Any]:
    return {
        "signal_family": family,
        "signal_code": code,
        "signal_label": label,
        "signal_value": "" if value is None or (isinstance(value, float) and np.isnan(value)) else str(value),
        "points": int(points),
        "severity": _severity(int(points)),
        "business_explanation": explanation,
    }


def _cap_family(signals: list[dict[str, Any]], cap: int) -> list[dict[str, Any]]:
    capped: list[dict[str, Any]] = []
    remaining = cap
    for signal in signals:
        if remaining <= 0:
            break
        points = min(int(signal["points"]), remaining)
        if points <= 0:
            continue
        adjusted = dict(signal)
        adjusted["points"] = points
        adjusted["severity"] = _severity(points)
        capped.append(adjusted)
        remaining -= points
    return capped


def _client_recurrence_signals(row: pd.Series) -> list[dict[str, Any]]:
    count_12m = _int(row.get("client_claim_count_12m"))
    days_previous = _num(row.get("days_since_previous_claim"))
    candidates: list[dict[str, Any]] = []

    if count_12m >= 3:
        candidates.append(_signal(
            "Recurrence client",
            "CLIENT_CLAIMS_12M_HIGH",
            "Recurrence client sur 12 mois",
            count_12m,
            20,
            "Plusieurs sinistres client precedents sont observes sur les 12 derniers mois.",
        ))
    elif count_12m == 2:
        candidates.append(_signal(
            "Recurrence client",
            "CLIENT_CLAIMS_12M_MEDIUM",
            "Deux sinistres client sur 12 mois",
            count_12m,
            12,
            "Deux sinistres client precedents sont observes sur les 12 derniers mois.",
        ))
    elif count_12m == 1:
        candidates.append(_signal(
            "Recurrence client",
            "CLIENT_CLAIMS_12M_LOW",
            "Un sinistre client sur 12 mois",
            count_12m,
            6,
            "Un sinistre client precedent est observe sur les 12 derniers mois.",
        ))

    if not np.isnan(days_previous) and days_previous <= 30:
        candidates.append(_signal(
            "Recurrence client",
            "CLIENT_RECENT_PREVIOUS_CLAIM",
            "Sinistre client precedent recent",
            int(days_previous),
            5,
            "Le dossier suit de pres un precedent sinistre du meme client.",
        ))

    return _cap_family(candidates, 25)


def _amount_signals(row: pd.Series) -> list[dict[str, Any]]:
    ratio = _num(row.get("amount_vs_guarantee_median_ratio"))
    percentile = _num(row.get("amount_percentile_by_guarantee"))
    high_amount = _is_true(row.get("high_amount_flag"))

    if high_amount:
        return [_signal(
            "Montant atypique",
            "AMOUNT_HIGH_BY_GUARANTEE",
            "Montant eleve par garantie",
            f"ratio={ratio:.2f}; percentile={percentile:.3f}",
            20,
            "Le montant est eleve par rapport aux dossiers comparables de la meme garantie.",
        )]
    if (not np.isnan(percentile) and percentile >= 0.90) or (not np.isnan(ratio) and ratio >= 2.0):
        return [_signal(
            "Montant atypique",
            "AMOUNT_MEDIUM_BY_GUARANTEE",
            "Montant superieur aux comparables",
            f"ratio={ratio:.2f}; percentile={percentile:.3f}",
            12,
            "Le montant est superieur a une part importante des dossiers comparables.",
        )]
    if (not np.isnan(percentile) and percentile >= 0.80) or (not np.isnan(ratio) and ratio >= 1.5):
        return [_signal(
            "Montant atypique",
            "AMOUNT_LOW_BY_GUARANTEE",
            "Montant a verifier",
            f"ratio={ratio:.2f}; percentile={percentile:.3f}",
            6,
            "Le montant merite une verification par rapport aux dossiers comparables.",
        )]
    return []


def _chronology_signals(row: pd.Series) -> list[dict[str, Any]]:
    days_contract = _num(row.get("days_contract_start_to_claim"))
    days_declaration = _num(row.get("days_claim_to_declaration"))
    candidates: list[dict[str, Any]] = []

    if _is_true(row.get("claim_before_contract_start_flag")):
        candidates.append(_signal(
            "Chronologie",
            "CLAIM_BEFORE_CONTRACT_START",
            "Sinistre avant debut contrat",
            int(days_contract) if not np.isnan(days_contract) else "",
            15,
            "La date du sinistre semble anterieure au debut du contrat rattache.",
        ))
    elif not np.isnan(days_contract) and 0 <= days_contract <= 30:
        candidates.append(_signal(
            "Chronologie",
            "CLAIM_SOON_AFTER_CONTRACT_START",
            "Sinistre proche du debut contrat",
            int(days_contract),
            10,
            "Le sinistre survient peu de temps apres le debut du contrat.",
        ))
    elif not np.isnan(days_contract) and 31 <= days_contract <= 90:
        candidates.append(_signal(
            "Chronologie",
            "CLAIM_WITHIN_90D_CONTRACT_START",
            "Sinistre dans les 90 jours contrat",
            int(days_contract),
            5,
            "Le sinistre survient dans les premiers mois du contrat.",
        ))

    if not np.isnan(days_declaration) and days_declaration < 0:
        candidates.append(_signal(
            "Chronologie",
            "DECLARATION_BEFORE_CLAIM_DATE",
            "Declaration avant sinistre",
            int(days_declaration),
            8,
            "La chronologie declaration/sinistre est incoherente et doit etre verifiee.",
        ))
    elif not np.isnan(days_declaration) and days_declaration >= 90:
        candidates.append(_signal(
            "Chronologie",
            "LONG_DECLARATION_DELAY_HIGH",
            "Delai de declaration tres long",
            int(days_declaration),
            8,
            "Le delai entre sinistre et declaration est tres long.",
        ))
    elif not np.isnan(days_declaration) and days_declaration >= 30:
        candidates.append(_signal(
            "Chronologie",
            "LONG_DECLARATION_DELAY_MEDIUM",
            "Delai de declaration long",
            int(days_declaration),
            5,
            "Le delai entre sinistre et declaration merite une verification.",
        ))

    return _cap_family(candidates, 20)


def _data_quality_signals(row: pd.Series) -> list[dict[str, Any]]:
    confidence = str(row.get("confidence_level") or "")
    if confidence not in {"LOW", "MEDIUM"}:
        return []

    return [_signal(
        "Qualite donnees",
        "CONFIDENCE_LIMITATION",
        "Limite de confiance des donnees",
        confidence,
        0,
        "Des cles, dates ou dimensions manquantes limitent la fiabilite de lecture du score.",
    )]


def score_claim_row(row: pd.Series) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    details: list[dict[str, Any]] = []
    details.extend(_client_recurrence_signals(row))
    details.extend(_amount_signals(row))
    details.extend(_chronology_signals(row))
    details.extend(_data_quality_signals(row))

    positive_details = [detail for detail in details if int(detail["points"]) > 0]
    score = int(max(0, min(100, sum(int(detail["points"]) for detail in positive_details))))
    reasons = [
        detail["signal_label"]
        for detail in sorted(positive_details, key=lambda d: (-int(d["points"]), d["signal_code"]))[:3]
    ]
    while len(reasons) < 3:
        reasons.append(None)
    if not positive_details:
        reasons[0] = "Aucun signal prioritaire V1"

    score_row = {
        "claim_sk": row.get("claim_sk"),
        "claim_business_id": row.get("claim_business_id"),
        "attention_score": score,
        "attention_level": attention_level(score),
        "confidence_level": row.get("confidence_level") or "LOW",
        "main_reason_1": reasons[0],
        "main_reason_2": reasons[1],
        "main_reason_3": reasons[2],
    }
    return score_row, details


def compute_claim_attention_scores(
    features: pd.DataFrame,
    score_run_id: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    score_run_id = score_run_id or f"{SCORE_VERSION}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    created_at = datetime.now(timezone.utc).replace(tzinfo=None)

    score_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []

    for _, row in features.iterrows():
        score_row, details = score_claim_row(row)
        score_row.update({
            "score_version": SCORE_VERSION,
            "score_run_id": score_run_id,
            "feature_run_id": row.get("feature_run_id"),
            "profile_name": PROFILE_NAME,
            "source_system": "IRIS_CLAIM_ATTENTION",
            "created_at": created_at,
        })
        score_rows.append(score_row)

        for detail in details:
            detail_row = {
                "claim_sk": row.get("claim_sk"),
                "claim_business_id": row.get("claim_business_id"),
                "score_run_id": score_run_id,
                "score_version": SCORE_VERSION,
                "profile_name": PROFILE_NAME,
                "created_at": created_at,
                **detail,
            }
            detail_rows.append(detail_row)

    score_df = pd.DataFrame(score_rows, columns=SCORE_COLUMNS)
    detail_df = pd.DataFrame(detail_rows, columns=DETAIL_COLUMNS)
    score_df["attention_score"] = pd.to_numeric(score_df["attention_score"], errors="coerce").fillna(0).astype(int)
    return score_df, detail_df


def validate_score_outputs(scores: pd.DataFrame, details: pd.DataFrame) -> dict[str, int]:
    if scores.empty:
        return {
            "score_rows": 0,
            "duplicate_score_rows": 0,
            "score_out_of_range_rows": 0,
            "null_level_rows": 0,
            "detail_point_mismatch_rows": 0,
        }

    detail_points = (
        details.groupby("claim_sk")["points"].sum()
        if not details.empty
        else pd.Series(dtype="int64")
    )
    positive_detail_points = (
        details.loc[pd.to_numeric(details["points"], errors="coerce") > 0]
        .groupby("claim_sk")["points"].sum()
        if not details.empty
        else pd.Series(dtype="int64")
    )
    comparison = scores.set_index("claim_sk")["attention_score"].subtract(positive_detail_points, fill_value=0)

    return {
        "score_rows": int(len(scores)),
        "duplicate_score_rows": int(scores.duplicated(["claim_sk", "score_version", "score_run_id"]).sum()),
        "score_out_of_range_rows": int((~scores["attention_score"].between(0, 100)).sum()),
        "null_level_rows": int(scores["attention_level"].isna().sum() + scores["confidence_level"].isna().sum()),
        "detail_rows": int(len(details)),
        "detail_points_total": int(detail_points.sum()) if len(detail_points) else 0,
        "detail_point_mismatch_rows": int(comparison.ne(0).sum()),
    }


def _write_score_reports(scores: pd.DataFrame, details: pd.DataFrame, score_run_id: str) -> dict[str, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    distribution = scores["attention_level"].value_counts(dropna=False).sort_index().rename_axis("attention_level").reset_index(name="rows")
    dist_csv = REPORT_DIR / "score_distribution_summary.csv"
    distribution.to_csv(dist_csv, index=False)
    paths["score_distribution_csv"] = dist_csv

    family_summary = (
        details.groupby("signal_family", dropna=False)
        .agg(signal_rows=("signal_code", "size"), total_points=("points", "sum"))
        .reset_index()
        if not details.empty
        else pd.DataFrame(columns=["signal_family", "signal_rows", "total_points"])
    )
    family_csv = REPORT_DIR / "signal_family_summary.csv"
    family_summary.to_csv(family_csv, index=False)
    paths["signal_family_summary"] = family_csv

    quality = scores["confidence_level"].value_counts(dropna=False).sort_index().rename_axis("confidence_level").reset_index(name="rows")
    quality_csv = REPORT_DIR / "data_quality_summary.csv"
    quality.to_csv(quality_csv, index=False)
    paths["data_quality_summary"] = quality_csv

    validation = validate_score_outputs(scores, details)
    summary_md = REPORT_DIR / "score_distribution_summary.md"
    lines = [
        "# Claim attention score V1 distribution",
        "",
        f"- **Run ID:** `{score_run_id}`",
        f"- **Score version:** `{SCORE_VERSION}`",
        f"- **Score rows:** {len(scores)}",
        f"- **Signal detail rows:** {len(details)}",
        "",
        "## Attention levels",
        "",
        "| Attention level | Rows |",
        "|---|---:|",
    ]
    for _, row in distribution.iterrows():
        lines.append(f"| {row['attention_level']} | {int(row['rows'])} |")
    lines.extend([
        "",
        "## Validation",
        "",
        "| Check | Rows |",
        "|---|---:|",
    ])
    for key, value in validation.items():
        lines.append(f"| {key} | {value} |")
    summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    paths["score_distribution_md"] = summary_md

    validation_md = REPORT_DIR / "claim_attention_validation_summary.md"
    validation_md.write_text(
        "\n".join([
            "# Claim attention V1 validation summary",
            "",
            f"- **Run ID:** `{score_run_id}`",
            f"- **Duplicate score rows:** {validation['duplicate_score_rows']}",
            f"- **Score out-of-range rows:** {validation['score_out_of_range_rows']}",
            f"- **Rows with null levels:** {validation['null_level_rows']}",
            f"- **Rows where detail points do not match score:** {validation['detail_point_mismatch_rows']}",
            "",
            "P2/P3 families are not used for attention points in V1.",
        ]) + "\n",
        encoding="utf-8",
    )
    paths["validation_summary"] = validation_md
    return paths


def _latest_feature_run_id(engine) -> str:
    query = text("""
        SELECT feature_run_id
        FROM mart.fact_claim_scoring_features
        WHERE scoring_feature_version = :feature_version
        GROUP BY feature_run_id
        ORDER BY MAX(created_at) DESC
        LIMIT 1
    """)
    with engine.connect() as conn:
        row = conn.execute(query, {"feature_version": FEATURE_VERSION}).fetchone()
    if row is None:
        raise RuntimeError("No feature run found in mart.fact_claim_scoring_features.")
    return str(row[0])


def _read_features(engine, feature_run_id: str) -> pd.DataFrame:
    query = text("""
        SELECT *
        FROM mart.fact_claim_scoring_features
        WHERE scoring_feature_version = :feature_version
          AND feature_run_id = :feature_run_id
    """)
    with engine.connect() as conn:
        return pd.read_sql(query, conn, params={
            "feature_version": FEATURE_VERSION,
            "feature_run_id": feature_run_id,
        })


def compute_claim_attention_score_v1_candidate(feature_run_id: str | None = None):
    if text is None:
        raise RuntimeError("SQLAlchemy is required to write claim attention score mart tables.")
    dwh_utils = _load_dwh_utils()

    today = datetime.now(timezone.utc).replace(tzinfo=None)
    score_run_id = f"{SCORE_VERSION}_{today.strftime('%Y%m%d_%H%M%S')}"
    logger = dwh_utils.setup_logging(score_run_id, log_name="compute_claim_attention_score_v1_candidate")
    logger.info("=" * 70)
    logger.info(f"[RUN] {score_run_id}")
    logger.info(f"      profile={PROFILE_NAME} version={SCORE_VERSION}")
    logger.info("      attention/prioritization score only; no fraud decision")
    logger.info("=" * 70)

    engine = dwh_utils.build_engine(logger)
    with engine.begin() as conn:
        conn.execute(text(DDL_CREATE_SCHEMA))
        conn.execute(text(DDL_FACT_CLAIM_ATTENTION_SCORE))
        conn.execute(text(DDL_FACT_CLAIM_ATTENTION_SIGNAL_DETAIL))
    logger.info("DDL ensured for claim attention score mart tables")

    feature_run_id = feature_run_id or _latest_feature_run_id(engine)
    features = _read_features(engine, feature_run_id)
    logger.info(f"feature_run_id loaded: {feature_run_id}")
    logger.info(f"feature rows loaded  : {len(features)}")

    scores, details = compute_claim_attention_scores(features, score_run_id=score_run_id)
    validation = validate_score_outputs(scores, details)
    logger.info(f"score rows computed : {len(scores)}")
    logger.info(f"detail rows computed: {len(details)}")
    logger.info(f"validation          : {validation}")

    with engine.begin() as conn:
        conn.execute(text("""
            DELETE FROM mart.fact_claim_attention_signal_detail
            WHERE score_version = :score_version
              AND score_run_id = :score_run_id
        """), {"score_version": SCORE_VERSION, "score_run_id": score_run_id})
        conn.execute(text("""
            DELETE FROM mart.fact_claim_attention_score
            WHERE score_version = :score_version
              AND score_run_id = :score_run_id
        """), {"score_version": SCORE_VERSION, "score_run_id": score_run_id})
        scores.to_sql(
            "fact_claim_attention_score",
            conn,
            schema="mart",
            if_exists="append",
            index=False,
            chunksize=5000,
            method="multi",
        )
        if not details.empty:
            details.to_sql(
                "fact_claim_attention_signal_detail",
                conn,
                schema="mart",
                if_exists="append",
                index=False,
                chunksize=5000,
                method="multi",
            )
    logger.info("inserted score and signal detail rows")

    report_paths = _write_score_reports(scores, details, score_run_id)
    for name, path in report_paths.items():
        logger.info(f"report {name}: {path}")

    print("=" * 70)
    print(f"  score_run_id       : {score_run_id}")
    print(f"  feature_run_id     : {feature_run_id}")
    print(f"  scored claims      : {len(scores)}")
    print(f"  signal detail rows : {len(details)}")
    print(f"  validation         : {validation}")
    print(f"  report folder      : {REPORT_DIR}")
    print("=" * 70)
    return scores, details


if __name__ == "__main__":
    compute_claim_attention_score_v1_candidate()
