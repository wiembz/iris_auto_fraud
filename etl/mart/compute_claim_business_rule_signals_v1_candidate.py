"""
etl/mart/compute_claim_business_rule_signals_v1_candidate.py
============================================================
Builds deterministic claim business-rule attention signals.

This mart is an explainable, auditable layer for human claim review. It does
not prove fraud, does not make an automatic decision, does not modify VHS, and
does not modify Claim Attention Score V1.

Source:
  mart.fact_claim_scoring_features

Output:
  mart.fact_claim_business_rule_signal
  data/quality_reports/scoring/business_rules/v1_candidate/
"""
from __future__ import annotations

import json
import sys
from io import StringIO
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from sqlalchemy import text
except ModuleNotFoundError:  # Allows pure unit tests without DB dependencies.
    text = None


BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dwh"))

from etl.mart.compute_claim_scoring_features_v1 import FEATURE_VERSION


def _load_dwh_utils():
    import dwh_utils
    return dwh_utils


SIGNAL_VERSION = "IRIS_CLAIM_BUSINESS_RULE_SIGNAL_V1_CANDIDATE"
PROFILE_NAME = "CLAIM_BUSINESS_RULE_SIGNAL_V1_CANDIDATE"
REPORT_DIR = BASE_DIR / "data" / "quality_reports" / "scoring" / "business_rules" / "v1_candidate"

DDL_CREATE_SCHEMA = "CREATE SCHEMA IF NOT EXISTS mart;"

DDL_FACT_CLAIM_BUSINESS_RULE_SIGNAL = """
CREATE TABLE IF NOT EXISTS mart.fact_claim_business_rule_signal (
    business_rule_signal_sk BIGSERIAL PRIMARY KEY,
    signal_run_id           TEXT NOT NULL,
    signal_version          TEXT NOT NULL,
    source_feature_run_id   TEXT,
    claim_sk                BIGINT NOT NULL,
    claim_business_id       TEXT,
    client_sk               BIGINT,
    contrat_sk              BIGINT,
    vehicule_sk             BIGINT,
    rule_family             TEXT NOT NULL,
    rule_code               TEXT NOT NULL,
    rule_label              TEXT NOT NULL,
    rule_severity_rank      SMALLINT NOT NULL,
    attention_level         TEXT NOT NULL,
    confidence_level        TEXT NOT NULL,
    rule_threshold_value    TEXT,
    rule_observed_value     TEXT,
    candidate_points        INTEGER NOT NULL,
    business_explanation    TEXT NOT NULL,
    source_tables           TEXT NOT NULL,
    payload_json            TEXT,
    is_data_quality_signal  BOOLEAN NOT NULL DEFAULT FALSE,
    profile_name            TEXT NOT NULL,
    created_at              TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_claim_business_rule_signal_run UNIQUE
        (signal_run_id, signal_version, claim_sk, rule_code)
);
"""

SIGNAL_COLUMNS = [
    "signal_run_id",
    "signal_version",
    "source_feature_run_id",
    "claim_sk",
    "claim_business_id",
    "client_sk",
    "contrat_sk",
    "vehicule_sk",
    "rule_family",
    "rule_code",
    "rule_label",
    "rule_severity_rank",
    "attention_level",
    "confidence_level",
    "rule_threshold_value",
    "rule_observed_value",
    "candidate_points",
    "business_explanation",
    "source_tables",
    "payload_json",
    "is_data_quality_signal",
    "profile_name",
    "created_at",
]

GRAIN_COLUMNS = ["signal_run_id", "signal_version", "claim_sk", "rule_code"]

NON_ACCUSATORY_BLOCKLIST = (
    "fraud detected",
    "fraudulent",
    "proof of fraud",
    "fraude detectee",
    "fraude confirmee",
    "client fraudeur",
    "fraudeur",
)


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


def _text(value: Any) -> str | None:
    try:
        if value is None or pd.isna(value):
            return None
    except TypeError:
        pass
    text_value = str(value).strip()
    return text_value or None


def _json_payload(payload: dict[str, Any]) -> str:
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, (np.integer, np.floating)):
            value = value.item()
        if isinstance(value, float) and np.isnan(value):
            value = None
        cleaned[key] = value
    return json.dumps(cleaned, ensure_ascii=False, sort_keys=True)


def _is_missing_key(value: Any) -> bool:
    number = _num(value, np.nan)
    if np.isnan(number):
        return True
    return int(number) == 0


def _valid_key_mask(frame: pd.DataFrame, key_columns: list[str]) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    technical_key_columns = {
        "client_sk",
        "contrat_sk",
        "vehicle_sk",
        "vehicule_sk",
        "garantie_sk",
        "conducteur_sk",
        "tiers_sk",
        "camtier_sk",
    }
    for column in key_columns:
        if column not in frame.columns:
            return pd.Series(False, index=frame.index)
        if column in technical_key_columns or column.endswith("_sk"):
            mask &= ~frame[column].map(_is_missing_key)
        else:
            mask &= frame[column].map(_text).notna()
    return mask


def _add_prior_recurrence_features(
    features: pd.DataFrame,
    key_columns: list[str],
    prefix: str,
    window_days: int = 365,
) -> pd.DataFrame:
    """Add prior-only recurrence features without using the current claim."""
    out = features.copy()
    count_total_col = f"{prefix}_claim_count_total"
    count_12m_col = f"{prefix}_claim_count_12m"
    days_previous_col = f"{prefix}_days_since_previous_claim"
    out[count_total_col] = 0
    out[count_12m_col] = 0
    out[days_previous_col] = pd.NA

    if out.empty or "claim_date" not in out.columns:
        return out

    dates = pd.to_datetime(out["claim_date"], errors="coerce")
    valid = _valid_key_mask(out, key_columns) & dates.notna()
    if not valid.any():
        return out

    work = out.loc[valid, key_columns].copy()
    work["_row_pos"] = np.flatnonzero(valid.to_numpy())
    work["_claim_date"] = dates.loc[valid].dt.normalize()
    sort_columns = key_columns + ["_claim_date", "_row_pos"]
    work = work.sort_values(sort_columns)

    total_values = np.zeros(len(out), dtype=int)
    count_12m_values = np.zeros(len(out), dtype=int)
    days_previous_values = np.full(len(out), np.nan)
    one_day = np.timedelta64(1, "D")
    window = np.timedelta64(int(window_days), "D")

    for _, group in work.groupby(key_columns, sort=False):
        group = group.sort_values(["_claim_date", "_row_pos"])
        group_dates = group["_claim_date"].to_numpy(dtype="datetime64[D]")
        row_positions = group["_row_pos"].to_numpy(dtype=int)
        for idx, current_date in enumerate(group_dates):
            prior_end = int(np.searchsorted(group_dates, current_date, side="left"))
            window_start = current_date - window
            window_left = int(np.searchsorted(group_dates, window_start, side="left"))
            total_values[row_positions[idx]] = prior_end
            count_12m_values[row_positions[idx]] = max(0, prior_end - window_left)
            if prior_end > 0:
                previous_date = group_dates[prior_end - 1]
                days_previous_values[row_positions[idx]] = int((current_date - previous_date) / one_day)

    out[count_total_col] = total_values
    out[count_12m_col] = count_12m_values
    out[days_previous_col] = pd.Series(days_previous_values, index=out.index).astype("Float64")
    return out


def enrich_features_for_business_rules(features: pd.DataFrame) -> pd.DataFrame:
    """Compute additional candidate-only recurrence context from existing feature keys."""
    enriched = features.copy()
    for column in ["claim_date", "vehicle_sk", "conducteur_sk", "tiers_sk", "client_sk", "code_garantie"]:
        if column not in enriched.columns:
            enriched[column] = pd.NA

    recurrence_specs = [
        (["vehicle_sk"], "vehicle"),
        (["conducteur_sk"], "driver"),
        (["tiers_sk"], "third_party"),
        (["client_sk", "code_garantie"], "client_guarantee"),
    ]
    for key_columns, prefix in recurrence_specs:
        enriched = _add_prior_recurrence_features(enriched, key_columns, prefix)
    return enriched

def attention_label(severity_rank: int, confidence_level: str, is_data_quality_signal: bool = False) -> str:
    if is_data_quality_signal:
        return "Limite de confiance a documenter"
    if confidence_level == "NOT_READY":
        return "Non pret pour priorisation"
    if severity_rank >= 3:
        return "Verification prioritaire suggeree"
    if severity_rank == 2:
        return "Signal metier a examiner"
    if severity_rank == 1:
        return "Contexte a verifier"
    return "Contexte a documenter"


def _rule(
    *,
    row: pd.Series,
    rule_family: str,
    rule_code: str,
    rule_label: str,
    rule_severity_rank: int,
    rule_threshold_value: str,
    rule_observed_value: Any,
    candidate_points: int,
    business_explanation: str,
    payload: dict[str, Any] | None = None,
    is_data_quality_signal: bool = False,
) -> dict[str, Any]:
    confidence = _text(row.get("confidence_level")) or "LOW"
    observed_value = "" if rule_observed_value is None else str(rule_observed_value)
    return {
        "source_feature_run_id": _text(row.get("feature_run_id")),
        "claim_sk": row.get("claim_sk"),
        "claim_business_id": _text(row.get("claim_business_id")),
        "client_sk": row.get("client_sk"),
        "contrat_sk": row.get("contrat_sk"),
        "vehicule_sk": row.get("vehicle_sk"),
        "rule_family": rule_family,
        "rule_code": rule_code,
        "rule_label": rule_label,
        "rule_severity_rank": int(rule_severity_rank),
        "attention_level": attention_label(int(rule_severity_rank), confidence, is_data_quality_signal),
        "confidence_level": confidence,
        "rule_threshold_value": rule_threshold_value,
        "rule_observed_value": observed_value,
        "candidate_points": int(candidate_points),
        "business_explanation": business_explanation,
        "source_tables": "mart.fact_claim_scoring_features",
        "payload_json": _json_payload(payload or {}),
        "is_data_quality_signal": bool(is_data_quality_signal),
    }


def _client_recurrence_rules(row: pd.Series) -> list[dict[str, Any]]:
    count_12m = _int(row.get("client_claim_count_12m"))
    days_previous = _num(row.get("days_since_previous_claim"))
    rules: list[dict[str, Any]] = []

    if count_12m >= 3:
        rules.append(_rule(
            row=row,
            rule_family="Recurrence client",
            rule_code="CLIENT_CLAIMS_12M_HIGH",
            rule_label="Recurrence client elevee sur 12 mois",
            rule_severity_rank=3,
            rule_threshold_value="client_claim_count_12m >= 3",
            rule_observed_value=count_12m,
            candidate_points=20,
            business_explanation="Plusieurs sinistres client precedents sont observes sur les 12 derniers mois; le dossier peut etre priorise pour verification.",
            payload={"client_claim_count_12m": count_12m},
        ))
    elif count_12m == 2:
        rules.append(_rule(
            row=row,
            rule_family="Recurrence client",
            rule_code="CLIENT_CLAIMS_12M_MEDIUM",
            rule_label="Deux sinistres client sur 12 mois",
            rule_severity_rank=2,
            rule_threshold_value="client_claim_count_12m = 2",
            rule_observed_value=count_12m,
            candidate_points=12,
            business_explanation="Deux sinistres client precedents sont observes sur les 12 derniers mois; le dossier merite un examen contextualise.",
            payload={"client_claim_count_12m": count_12m},
        ))
    elif count_12m == 1:
        rules.append(_rule(
            row=row,
            rule_family="Recurrence client",
            rule_code="CLIENT_CLAIMS_12M_LOW",
            rule_label="Un sinistre client sur 12 mois",
            rule_severity_rank=1,
            rule_threshold_value="client_claim_count_12m = 1",
            rule_observed_value=count_12m,
            candidate_points=6,
            business_explanation="Un sinistre client precedent est observe sur les 12 derniers mois; ce contexte peut aider le gestionnaire.",
            payload={"client_claim_count_12m": count_12m},
        ))

    if not np.isnan(days_previous) and 0 <= days_previous <= 30:
        rules.append(_rule(
            row=row,
            rule_family="Recurrence client",
            rule_code="CLIENT_RECENT_PREVIOUS_CLAIM",
            rule_label="Sinistre client precedent recent",
            rule_severity_rank=1,
            rule_threshold_value="0 <= days_since_previous_claim <= 30",
            rule_observed_value=int(days_previous),
            candidate_points=5,
            business_explanation="Le dossier suit de pres un sinistre precedent du meme client; le delai court justifie une verification de contexte.",
            payload={"days_since_previous_claim": int(days_previous)},
        ))

    return rules


def _amount_rules(row: pd.Series) -> list[dict[str, Any]]:
    ratio = _num(row.get("amount_vs_guarantee_median_ratio"))
    percentile = _num(row.get("amount_percentile_by_guarantee"))
    high_amount = _is_true(row.get("high_amount_flag"))
    observed = {
        "ratio": None if np.isnan(ratio) else round(float(ratio), 4),
        "percentile": None if np.isnan(percentile) else round(float(percentile), 6),
        "high_amount_flag": high_amount,
    }

    if high_amount or (not np.isnan(percentile) and percentile >= 0.95) or (not np.isnan(ratio) and ratio >= 3.0):
        return [_rule(
            row=row,
            rule_family="Montant atypique",
            rule_code="AMOUNT_HIGH_BY_GUARANTEE",
            rule_label="Montant eleve dans la garantie",
            rule_severity_rank=3,
            rule_threshold_value="percentile >= 0.95 OR ratio >= 3.0 OR high_amount_flag",
            rule_observed_value=observed,
            candidate_points=20,
            business_explanation="Le montant evalue se situe nettement au-dessus du profil observe pour la garantie; une verification metier prioritaire est suggeree.",
            payload=observed,
        )]
    if (not np.isnan(percentile) and percentile >= 0.90) or (not np.isnan(ratio) and ratio >= 2.0):
        return [_rule(
            row=row,
            rule_family="Montant atypique",
            rule_code="AMOUNT_MEDIUM_BY_GUARANTEE",
            rule_label="Montant superieur au profil de garantie",
            rule_severity_rank=2,
            rule_threshold_value="percentile >= 0.90 OR ratio >= 2.0",
            rule_observed_value=observed,
            candidate_points=12,
            business_explanation="Le montant evalue est superieur au profil habituel de la garantie; le dossier merite une revue contextualisee.",
            payload=observed,
        )]
    if (not np.isnan(percentile) and percentile >= 0.80) or (not np.isnan(ratio) and ratio >= 1.5):
        return [_rule(
            row=row,
            rule_family="Montant atypique",
            rule_code="AMOUNT_LOW_BY_GUARANTEE",
            rule_label="Montant a surveiller dans la garantie",
            rule_severity_rank=1,
            rule_threshold_value="percentile >= 0.80 OR ratio >= 1.5",
            rule_observed_value=observed,
            candidate_points=6,
            business_explanation="Le montant evalue est au-dessus de la zone centrale observee pour la garantie; il peut enrichir l'analyse du gestionnaire.",
            payload=observed,
        )]
    return []


def _chronology_rules(row: pd.Series) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    claim_before_contract = _is_true(row.get("claim_before_contract_start_flag"))
    days_contract = _num(row.get("days_contract_start_to_claim"))
    days_declaration = _num(row.get("days_claim_to_declaration"))

    if claim_before_contract:
        rules.append(_rule(
            row=row,
            rule_family="Chronologie",
            rule_code="CLAIM_BEFORE_CONTRACT_START",
            rule_label="Sinistre avant debut contrat",
            rule_severity_rank=3,
            rule_threshold_value="claim_date < contract_start_date",
            rule_observed_value=days_contract if not np.isnan(days_contract) else None,
            candidate_points=15,
            business_explanation="La date de sinistre apparait anterieure au debut de contrat rattache; ce point doit etre verifie avant interpretation.",
            payload={"days_contract_start_to_claim": None if np.isnan(days_contract) else int(days_contract)},
        ))
    elif not np.isnan(days_contract) and 0 <= days_contract <= 30:
        rules.append(_rule(
            row=row,
            rule_family="Chronologie",
            rule_code="CLAIM_SOON_AFTER_CONTRACT_START",
            rule_label="Sinistre proche du debut contrat",
            rule_severity_rank=2,
            rule_threshold_value="0 <= days_contract_start_to_claim <= 30",
            rule_observed_value=int(days_contract),
            candidate_points=10,
            business_explanation="Le sinistre survient peu apres le debut du contrat; le dossier peut etre examine avec priorite moderee.",
            payload={"days_contract_start_to_claim": int(days_contract)},
        ))
    elif not np.isnan(days_contract) and 31 <= days_contract <= 90:
        rules.append(_rule(
            row=row,
            rule_family="Chronologie",
            rule_code="CLAIM_WITHIN_90D_CONTRACT_START",
            rule_label="Sinistre dans les 90 jours du debut contrat",
            rule_severity_rank=1,
            rule_threshold_value="31 <= days_contract_start_to_claim <= 90",
            rule_observed_value=int(days_contract),
            candidate_points=5,
            business_explanation="Le sinistre survient dans une fenetre proche du debut contrat; ce contexte peut etre utile a l'analyse.",
            payload={"days_contract_start_to_claim": int(days_contract)},
        ))

    if not np.isnan(days_declaration) and days_declaration < 0:
        rules.append(_rule(
            row=row,
            rule_family="Chronologie",
            rule_code="DECLARATION_BEFORE_CLAIM_DATE",
            rule_label="Declaration avant date de sinistre",
            rule_severity_rank=2,
            rule_threshold_value="days_claim_to_declaration < 0",
            rule_observed_value=int(days_declaration),
            candidate_points=8,
            business_explanation="La declaration apparait anterieure a la date de sinistre; il s'agit d'un point de coherence a controler.",
            payload={"days_claim_to_declaration": int(days_declaration)},
        ))
    elif not np.isnan(days_declaration) and days_declaration >= 90:
        rules.append(_rule(
            row=row,
            rule_family="Chronologie",
            rule_code="LONG_DECLARATION_DELAY_HIGH",
            rule_label="Delai de declaration long",
            rule_severity_rank=2,
            rule_threshold_value="days_claim_to_declaration >= 90",
            rule_observed_value=int(days_declaration),
            candidate_points=8,
            business_explanation="Le delai entre la date de sinistre et la declaration est long; une verification du contexte documentaire est recommandee.",
            payload={"days_claim_to_declaration": int(days_declaration)},
        ))
    elif not np.isnan(days_declaration) and 30 <= days_declaration < 90:
        rules.append(_rule(
            row=row,
            rule_family="Chronologie",
            rule_code="LONG_DECLARATION_DELAY_MEDIUM",
            rule_label="Delai de declaration a examiner",
            rule_severity_rank=1,
            rule_threshold_value="30 <= days_claim_to_declaration < 90",
            rule_observed_value=int(days_declaration),
            candidate_points=5,
            business_explanation="Le delai de declaration est superieur au delai court attendu; ce point peut etre examine par le gestionnaire.",
            payload={"days_claim_to_declaration": int(days_declaration)},
        ))

    return rules


def _entity_recurrence_rules(
    row: pd.Series,
    *,
    prefix: str,
    family: str,
    high_code: str,
    medium_code: str | None,
    recent_code: str,
    high_label: str,
    medium_label: str | None,
    recent_label: str,
    high_threshold: int,
    medium_threshold: int | None,
    high_points: int,
    medium_points: int,
    recent_points: int,
    high_explanation: str,
    medium_explanation: str | None,
    recent_explanation: str,
) -> list[dict[str, Any]]:
    count_12m = _int(row.get(f"{prefix}_claim_count_12m"))
    days_previous = _num(row.get(f"{prefix}_days_since_previous_claim"))
    rules: list[dict[str, Any]] = []

    if count_12m >= high_threshold:
        rules.append(_rule(
            row=row,
            rule_family=family,
            rule_code=high_code,
            rule_label=high_label,
            rule_severity_rank=2,
            rule_threshold_value=f"{prefix}_claim_count_12m >= {high_threshold}",
            rule_observed_value=count_12m,
            candidate_points=high_points,
            business_explanation=high_explanation,
            payload={f"{prefix}_claim_count_12m": count_12m},
        ))
    elif medium_code and medium_label and medium_explanation and medium_threshold is not None and count_12m == medium_threshold:
        rules.append(_rule(
            row=row,
            rule_family=family,
            rule_code=medium_code,
            rule_label=medium_label,
            rule_severity_rank=1,
            rule_threshold_value=f"{prefix}_claim_count_12m = {medium_threshold}",
            rule_observed_value=count_12m,
            candidate_points=medium_points,
            business_explanation=medium_explanation,
            payload={f"{prefix}_claim_count_12m": count_12m},
        ))

    if not np.isnan(days_previous) and 0 <= days_previous <= 30:
        rules.append(_rule(
            row=row,
            rule_family=family,
            rule_code=recent_code,
            rule_label=recent_label,
            rule_severity_rank=1,
            rule_threshold_value=f"0 <= {prefix}_days_since_previous_claim <= 30",
            rule_observed_value=int(days_previous),
            candidate_points=recent_points,
            business_explanation=recent_explanation,
            payload={f"{prefix}_days_since_previous_claim": int(days_previous)},
        ))

    return rules


def _vehicle_recurrence_rules(row: pd.Series) -> list[dict[str, Any]]:
    return _entity_recurrence_rules(
        row,
        prefix="vehicle",
        family="Recurrence vehicule",
        high_code="VEHICLE_CLAIMS_12M_HIGH",
        medium_code="VEHICLE_CLAIMS_12M_MEDIUM",
        recent_code="VEHICLE_RECENT_PREVIOUS_CLAIM",
        high_label="Recurrence vehicule elevee sur 12 mois",
        medium_label="Deux sinistres vehicule sur 12 mois",
        recent_label="Sinistre vehicule precedent recent",
        high_threshold=3,
        medium_threshold=2,
        high_points=15,
        medium_points=10,
        recent_points=5,
        high_explanation="Plusieurs sinistres precedents sont observes sur le meme vehicule dans les 12 derniers mois; le dossier peut etre priorise pour verification contextualisee.",
        medium_explanation="Deux sinistres precedents sont observes sur le meme vehicule dans les 12 derniers mois; ce contexte merite une revue metier.",
        recent_explanation="Le dossier suit de pres un sinistre precedent du meme vehicule; le delai court justifie une verification de contexte.",
    )


def _driver_recurrence_rules(row: pd.Series) -> list[dict[str, Any]]:
    return _entity_recurrence_rules(
        row,
        prefix="driver",
        family="Recurrence conducteur",
        high_code="DRIVER_CLAIMS_12M_HIGH",
        medium_code=None,
        recent_code="DRIVER_RECENT_PREVIOUS_CLAIM",
        high_label="Recurrence conducteur sur 12 mois",
        medium_label=None,
        recent_label="Sinistre conducteur precedent recent",
        high_threshold=2,
        medium_threshold=None,
        high_points=10,
        medium_points=0,
        recent_points=5,
        high_explanation="Plusieurs sinistres precedents sont rattaches au meme conducteur dans les 12 derniers mois; ce signal sert a prioriser la verification.",
        medium_explanation=None,
        recent_explanation="Le dossier suit de pres un sinistre precedent rattache au meme conducteur; ce contexte peut etre examine.",
    )


def _third_party_recurrence_rules(row: pd.Series) -> list[dict[str, Any]]:
    return _entity_recurrence_rules(
        row,
        prefix="third_party",
        family="Recurrence tiers",
        high_code="THIRD_PARTY_CLAIMS_12M_HIGH",
        medium_code=None,
        recent_code="THIRD_PARTY_RECENT_PREVIOUS_CLAIM",
        high_label="Recurrence tiers sur 12 mois",
        medium_label=None,
        recent_label="Sinistre tiers precedent recent",
        high_threshold=2,
        medium_threshold=None,
        high_points=10,
        medium_points=0,
        recent_points=5,
        high_explanation="Plusieurs sinistres precedents impliquent le meme tiers dans les 12 derniers mois; le dossier peut etre examine avec attention.",
        medium_explanation=None,
        recent_explanation="Le dossier suit de pres un sinistre precedent impliquant le meme tiers; ce contexte peut etre documente.",
    )


def _client_guarantee_recurrence_rules(row: pd.Series) -> list[dict[str, Any]]:
    return _entity_recurrence_rules(
        row,
        prefix="client_guarantee",
        family="Repetition garantie",
        high_code="CLIENT_GUARANTEE_REPEAT_12M_HIGH",
        medium_code="CLIENT_GUARANTEE_REPEAT_12M_MEDIUM",
        recent_code="CLIENT_GUARANTEE_RECENT_PREVIOUS_CLAIM",
        high_label="Repetition client garantie elevee",
        medium_label="Repetition client garantie a examiner",
        recent_label="Sinistre precedent recent sur meme garantie",
        high_threshold=3,
        medium_threshold=2,
        high_points=12,
        medium_points=8,
        recent_points=4,
        high_explanation="Plusieurs sinistres precedents du meme client concernent la meme garantie sur 12 mois; ce contexte peut renforcer la priorisation.",
        medium_explanation="Deux sinistres precedents du meme client concernent la meme garantie sur 12 mois; ce point merite une revue contextualisee.",
        recent_explanation="Un sinistre precedent du meme client sur la meme garantie est recent; ce contexte peut etre utile au gestionnaire.",
    )

def _data_quality_rules(row: pd.Series) -> list[dict[str, Any]]:
    missing_flags = [
        flag for flag in [
            "missing_client_flag",
            "missing_contract_flag",
            "missing_vehicle_flag",
            "missing_guarantee_flag",
            "invalid_claim_date_flag",
            "invalid_declaration_date_flag",
            "future_claim_date_flag",
        ]
        if _is_true(row.get(flag))
    ]
    rules: list[dict[str, Any]] = []
    confidence = _text(row.get("confidence_level")) or "LOW"

    if missing_flags:
        rules.append(_rule(
            row=row,
            rule_family="Qualite donnees",
            rule_code="DATA_QUALITY_LIMITATION",
            rule_label="Donnees a completer pour interpretation",
            rule_severity_rank=0,
            rule_threshold_value="missing or invalid critical fields",
            rule_observed_value=", ".join(missing_flags),
            candidate_points=0,
            business_explanation="Des donnees structurantes sont manquantes ou invalides; cela limite la confiance et ne doit pas augmenter l'attention metier.",
            payload={"missing_or_invalid_flags": missing_flags},
            is_data_quality_signal=True,
        ))
    elif confidence in {"LOW", "NOT_READY"}:
        rules.append(_rule(
            row=row,
            rule_family="Qualite donnees",
            rule_code="LOW_CONFIDENCE_CONTEXT",
            rule_label="Confiance limitee",
            rule_severity_rank=0,
            rule_threshold_value="confidence_level IN (LOW, NOT_READY)",
            rule_observed_value=confidence,
            candidate_points=0,
            business_explanation="Le niveau de confiance disponible limite l'interpretation; le signal sert uniquement a documenter la qualite des donnees.",
            payload={"confidence_level": confidence},
            is_data_quality_signal=True,
        ))

    return rules


def claim_business_rules_for_row(row: pd.Series) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    rules.extend(_client_recurrence_rules(row))
    rules.extend(_vehicle_recurrence_rules(row))
    rules.extend(_driver_recurrence_rules(row))
    rules.extend(_third_party_recurrence_rules(row))
    rules.extend(_client_guarantee_recurrence_rules(row))
    rules.extend(_amount_rules(row))
    rules.extend(_chronology_rules(row))
    rules.extend(_data_quality_rules(row))
    return rules


def contains_accusatory_wording(text_value: object) -> bool:
    if text_value is None:
        return False
    lowered = str(text_value).lower()
    return any(term in lowered for term in NON_ACCUSATORY_BLOCKLIST)


def compute_claim_business_rule_signals(
    features: pd.DataFrame,
    signal_run_id: str | None = None,
    created_at: datetime | None = None,
) -> pd.DataFrame:
    signal_run_id = signal_run_id or f"{SIGNAL_VERSION}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    created_at = created_at or datetime.now(timezone.utc).replace(tzinfo=None)

    features = enrich_features_for_business_rules(features)

    signal_rows: list[dict[str, Any]] = []
    for _, row in features.iterrows():
        for rule in claim_business_rules_for_row(row):
            signal_rows.append({
                "signal_run_id": signal_run_id,
                "signal_version": SIGNAL_VERSION,
                "profile_name": PROFILE_NAME,
                "created_at": created_at,
                **rule,
            })

    signals = pd.DataFrame(signal_rows, columns=SIGNAL_COLUMNS)
    if signals.empty:
        return signals

    signals["candidate_points"] = pd.to_numeric(signals["candidate_points"], errors="coerce").fillna(0).astype(int)
    signals["rule_severity_rank"] = pd.to_numeric(signals["rule_severity_rank"], errors="coerce").fillna(0).astype(int)
    signals["is_data_quality_signal"] = signals["is_data_quality_signal"].astype(bool)
    return signals


def validate_business_rule_signals(signals: pd.DataFrame) -> dict[str, int]:
    if signals.empty:
        return {
            "signal_rows": 0,
            "duplicate_grain_rows": 0,
            "null_required_rows": 0,
            "negative_candidate_point_rows": 0,
            "data_quality_positive_point_rows": 0,
            "null_explanation_rows": 0,
            "accusatory_wording_rows": 0,
        }

    required_columns = [
        "signal_run_id",
        "signal_version",
        "claim_sk",
        "rule_family",
        "rule_code",
        "rule_label",
        "attention_level",
        "confidence_level",
        "business_explanation",
    ]
    null_required = int(signals[required_columns].isna().any(axis=1).sum())
    explanation_text = signals["business_explanation"].fillna("")
    data_quality_positive = signals.loc[
        signals["is_data_quality_signal"].astype(bool)
        & (pd.to_numeric(signals["candidate_points"], errors="coerce").fillna(0) > 0)
    ]

    return {
        "signal_rows": int(len(signals)),
        "duplicate_grain_rows": int(signals.duplicated(GRAIN_COLUMNS).sum()),
        "null_required_rows": null_required,
        "negative_candidate_point_rows": int((pd.to_numeric(signals["candidate_points"], errors="coerce").fillna(0) < 0).sum()),
        "data_quality_positive_point_rows": int(len(data_quality_positive)),
        "null_explanation_rows": int(explanation_text.str.strip().eq("").sum()),
        "accusatory_wording_rows": int(explanation_text.map(contains_accusatory_wording).sum()),
    }


def _write_business_rule_reports(signals: pd.DataFrame, signal_run_id: str) -> dict[str, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    validation = validate_business_rule_signals(signals)

    load_summary = pd.DataFrame([{
        "signal_run_id": signal_run_id,
        "signal_version": SIGNAL_VERSION,
        "signal_rows": len(signals),
        "distinct_claims": int(signals["claim_sk"].nunique()) if not signals.empty else 0,
        "positive_candidate_point_rows": int((signals["candidate_points"] > 0).sum()) if not signals.empty else 0,
        "data_quality_signal_rows": int(signals["is_data_quality_signal"].sum()) if not signals.empty else 0,
    }])
    load_summary_path = REPORT_DIR / "business_rule_load_summary.csv"
    load_summary.to_csv(load_summary_path, index=False)
    paths["load_summary"] = load_summary_path

    duplicate_check = (
        signals.loc[signals.duplicated(GRAIN_COLUMNS, keep=False), GRAIN_COLUMNS + ["rule_family", "rule_label"]]
        if not signals.empty
        else pd.DataFrame(columns=GRAIN_COLUMNS + ["rule_family", "rule_label"])
    )
    duplicate_path = REPORT_DIR / "business_rule_duplicate_grain_check.csv"
    duplicate_check.to_csv(duplicate_path, index=False)
    paths["duplicate_grain_check"] = duplicate_path

    attention_distribution = (
        signals["attention_level"].value_counts(dropna=False).rename_axis("attention_level").reset_index(name="rows")
        if not signals.empty
        else pd.DataFrame(columns=["attention_level", "rows"])
    )
    attention_path = REPORT_DIR / "business_rule_attention_distribution.csv"
    attention_distribution.to_csv(attention_path, index=False)
    paths["attention_distribution"] = attention_path

    confidence_distribution = (
        signals["confidence_level"].value_counts(dropna=False).rename_axis("confidence_level").reset_index(name="rows")
        if not signals.empty
        else pd.DataFrame(columns=["confidence_level", "rows"])
    )
    confidence_path = REPORT_DIR / "business_rule_confidence_distribution.csv"
    confidence_distribution.to_csv(confidence_path, index=False)
    paths["confidence_distribution"] = confidence_path

    family_distribution = (
        signals.groupby("rule_family", dropna=False)
        .agg(signal_rows=("rule_code", "size"), total_candidate_points=("candidate_points", "sum"))
        .reset_index()
        if not signals.empty
        else pd.DataFrame(columns=["rule_family", "signal_rows", "total_candidate_points"])
    )
    family_path = REPORT_DIR / "business_rule_family_distribution.csv"
    family_distribution.to_csv(family_path, index=False)
    paths["family_distribution"] = family_path

    not_ready = (
        signals.loc[signals["is_data_quality_signal"], [
            "claim_sk",
            "claim_business_id",
            "rule_code",
            "rule_observed_value",
            "confidence_level",
            "business_explanation",
        ]]
        if not signals.empty
        else pd.DataFrame(columns=[
            "claim_sk",
            "claim_business_id",
            "rule_code",
            "rule_observed_value",
            "confidence_level",
            "business_explanation",
        ])
    )
    not_ready_path = REPORT_DIR / "business_rule_not_ready_reasons.csv"
    not_ready.to_csv(not_ready_path, index=False)
    paths["not_ready_reasons"] = not_ready_path

    threshold_breaches = (
        signals.loc[signals["candidate_points"] > 0, [
            "claim_sk",
            "claim_business_id",
            "rule_family",
            "rule_code",
            "rule_threshold_value",
            "rule_observed_value",
            "candidate_points",
            "attention_level",
            "confidence_level",
        ]]
        if not signals.empty
        else pd.DataFrame(columns=[
            "claim_sk",
            "claim_business_id",
            "rule_family",
            "rule_code",
            "rule_threshold_value",
            "rule_observed_value",
            "candidate_points",
            "attention_level",
            "confidence_level",
        ])
    )
    threshold_path = REPORT_DIR / "business_rule_threshold_breaches.csv"
    threshold_breaches.to_csv(threshold_path, index=False)
    paths["threshold_breaches"] = threshold_path

    validation_path = REPORT_DIR / "business_rule_validation_summary.csv"
    pd.DataFrame([validation]).to_csv(validation_path, index=False)
    paths["validation_summary_csv"] = validation_path

    validation_md = REPORT_DIR / "business_rule_validation_summary.md"
    lines = [
        "# Claim business rule signal V1 candidate validation",
        "",
        f"- **Run ID:** `{signal_run_id}`",
        f"- **Signal version:** `{SIGNAL_VERSION}`",
        f"- **Signal rows:** {len(signals)}",
        "",
        "This layer provides deterministic attention signals for review. It does not modify Claim Attention Score V1.",
        "",
        "## Validation",
        "",
        "| Check | Rows |",
        "|---|---:|",
    ]
    for key, value in validation.items():
        lines.append(f"| {key} | {value} |")
    validation_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    paths["validation_summary_md"] = validation_md

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


def _copy_signals_to_db(engine, signals: pd.DataFrame, chunksize: int = 100000) -> None:
    if signals.empty:
        return

    columns_sql = ", ".join(SIGNAL_COLUMNS)
    copy_sql = f"""
        COPY mart.fact_claim_business_rule_signal ({columns_sql})
        FROM STDIN WITH (FORMAT CSV, HEADER FALSE, DELIMITER E'\\t', NULL '\\N')
    """

    export = signals[SIGNAL_COLUMNS].copy()
    export["created_at"] = pd.to_datetime(export["created_at"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")

    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cursor:
            for start in range(0, len(export), chunksize):
                chunk = export.iloc[start:start + chunksize]
                buffer = StringIO()
                chunk.to_csv(
                    buffer,
                    sep="\t",
                    header=False,
                    index=False,
                    na_rep="\\N",
                    lineterminator="\n",
                )
                buffer.seek(0)
                cursor.copy_expert(copy_sql, buffer)
        raw_conn.commit()
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        raw_conn.close()

def compute_claim_business_rule_signals_v1_candidate(feature_run_id: str | None = None) -> pd.DataFrame:
    if text is None:
        raise RuntimeError("SQLAlchemy is required to write mart.fact_claim_business_rule_signal.")

    dwh_utils = _load_dwh_utils()
    today = datetime.now(timezone.utc).replace(tzinfo=None)
    signal_run_id = f"{SIGNAL_VERSION}_{today.strftime('%Y%m%d_%H%M%S')}"
    logger = dwh_utils.setup_logging(signal_run_id, log_name="compute_claim_business_rule_signals_v1_candidate")
    logger.info("=" * 70)
    logger.info(f"[RUN] {signal_run_id}")
    logger.info(f"      profile={PROFILE_NAME} version={SIGNAL_VERSION}")
    logger.info("      deterministic attention signals only; no automatic decision")
    logger.info("=" * 70)

    engine = dwh_utils.build_engine(logger)
    with engine.begin() as conn:
        conn.execute(text(DDL_CREATE_SCHEMA))
        conn.execute(text(DDL_FACT_CLAIM_BUSINESS_RULE_SIGNAL))
    logger.info("DDL ensured for mart.fact_claim_business_rule_signal")

    feature_run_id = feature_run_id or _latest_feature_run_id(engine)
    features = _read_features(engine, feature_run_id)
    logger.info(f"feature rows loaded: {len(features)}")

    signals = compute_claim_business_rule_signals(features, signal_run_id=signal_run_id, created_at=today)
    validation = validate_business_rule_signals(signals)
    logger.info(f"business rule signal rows: {len(signals)}")
    logger.info(f"validation: {validation}")

    blocking_checks = [
        "duplicate_grain_rows",
        "null_required_rows",
        "negative_candidate_point_rows",
        "data_quality_positive_point_rows",
        "null_explanation_rows",
        "accusatory_wording_rows",
    ]
    failed_checks = {key: validation[key] for key in blocking_checks if validation.get(key, 0) > 0}
    if failed_checks:
        raise RuntimeError(f"Business rule signal validation failed: {failed_checks}")

    with engine.begin() as conn:
        conn.execute(text("""
            DELETE FROM mart.fact_claim_business_rule_signal
            WHERE signal_version = :version
              AND signal_run_id = :run_id
        """), {"version": SIGNAL_VERSION, "run_id": signal_run_id})
    _copy_signals_to_db(engine, signals)
    logger.info(f"inserted -> mart.fact_claim_business_rule_signal: {len(signals)} rows")

    report_paths = _write_business_rule_reports(signals, signal_run_id)
    for name, path in report_paths.items():
        logger.info(f"report {name}: {path}")

    print("=" * 70)
    print(f"  signal_run_id      : {signal_run_id}")
    print(f"  feature_run_id     : {feature_run_id}")
    print(f"  signal rows        : {len(signals)}")
    print(f"  distinct claims    : {signals['claim_sk'].nunique() if not signals.empty else 0}")
    print(f"  validation         : {validation}")
    print(f"  report folder      : {REPORT_DIR}")
    print("=" * 70)
    return signals


if __name__ == "__main__":
    compute_claim_business_rule_signals_v1_candidate()
