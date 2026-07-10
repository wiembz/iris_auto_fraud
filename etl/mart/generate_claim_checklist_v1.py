"""Dynamic checklist generation for IRIS claim review."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from etl.mart.compute_claim_business_rules_v2_candidate import KNOWN_ACTION_CODES
from etl.utils.business_language import contains_forbidden_business_wording

ACTION_LABELS = {
    "ACT_VERIFY_CHRONOLOGY": "Verifier la chronologie du dossier",
    "ACT_REVIEW_CLIENT_HISTORY": "Consulter l'historique recent du client",
    "ACT_COMPARE_ESTIMATE": "Comparer le montant avec les dossiers comparables",
    "ACT_REQUEST_REQUIRED_DOCUMENTS": "Demander ou documenter les pieces manquantes",
    "ACT_COMPLETE_INFORMATION": "Completer les informations limitant l'analyse",
}

CHECKLIST_COLUMNS = [
    "claim_sk",
    "claim_business_id",
    "score_run_id",
    "checklist_item_id",
    "action_code",
    "label",
    "priority",
    "status",
    "generated_by_rules",
    "generated_at",
]


def _validate_action_code(action_code: object) -> str:
    if action_code is None or pd.isna(action_code):
        raise ValueError("Missing checklist action_code")
    code = str(action_code)
    if code not in KNOWN_ACTION_CODES or code not in ACTION_LABELS:
        raise ValueError(f"Unknown checklist action_code: {code}")
    if contains_forbidden_business_wording(ACTION_LABELS[code]):
        raise ValueError(f"Forbidden wording in checklist label for action_code: {code}")
    return code


def generate_claim_checklist(details: pd.DataFrame, *, generated_at: datetime | None = None) -> pd.DataFrame:
    """Generate one checklist item per score run, claim and action."""
    generated_at = generated_at or datetime.now(timezone.utc)
    if details.empty:
        return pd.DataFrame(columns=CHECKLIST_COLUMNS)

    rows = []
    grouped = details.groupby(["score_run_id", "claim_sk", "suggested_action_code"], dropna=False)
    for (score_run_id, claim_sk, action_code), group in grouped:
        code = _validate_action_code(action_code)
        ordered = group.sort_values(["awarded_points" if "awarded_points" in group.columns else "points", "rule_code"], ascending=[False, True])
        point_col = "awarded_points" if "awarded_points" in ordered.columns else "points"
        max_points = int(pd.to_numeric(ordered[point_col], errors="coerce").fillna(0).max())
        priority = "HIGH" if max_points >= 15 else "MEDIUM" if max_points >= 8 else "LOW"
        rows.append({
            "claim_sk": claim_sk,
            "claim_business_id": ordered.iloc[0].get("claim_business_id"),
            "score_run_id": score_run_id,
            "checklist_item_id": f"{score_run_id}:{claim_sk}:{code}",
            "action_code": code,
            "label": ACTION_LABELS[code],
            "priority": priority,
            "status": "TO_CHECK",
            "generated_by_rules": ",".join(ordered["rule_code"].astype(str).drop_duplicates().tolist()),
            "generated_at": generated_at,
        })
    return pd.DataFrame(rows, columns=CHECKLIST_COLUMNS)
