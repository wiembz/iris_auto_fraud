"""Deterministic business explanations for Claim Attention V2."""
from __future__ import annotations

from typing import Iterable

import pandas as pd

from etl.utils.business_language import contains_forbidden_business_wording


def contains_forbidden_language(text: object) -> bool:
    return contains_forbidden_business_wording(text)


def _sentence_join(items: Iterable[str]) -> str:
    clean = [str(item).strip().rstrip(".") for item in items if str(item or "").strip()]
    if not clean:
        return "Aucun signal principal n'est affiche pour ce dossier."
    return "; ".join(clean) + "."


def generate_claim_explanation(score_row: pd.Series, detail_rows: pd.DataFrame) -> str:
    """Generate a stable non-accusatory explanation from score details."""
    level = score_row.get("attention_level") or "niveau non renseigne"
    confidence = score_row.get("confidence_level") or "confiance non renseignee"
    sort_column = "awarded_points" if "awarded_points" in detail_rows.columns else "points"
    top_details = detail_rows.sort_values([sort_column, "business_label"], ascending=[False, True]).head(3)
    signals = _sentence_join(top_details.get("business_label", pd.Series(dtype=str)).tolist())
    text = (
        f"Le dossier est classe en '{level}'. Principaux elements a examiner : {signals} "
        f"Niveau de confiance des donnees : {confidence}. "
        "Les elements presentes constituent une aide a l'analyse et ne remplacent pas la decision du gestionnaire."
    )
    if contains_forbidden_business_wording(text):
        raise ValueError("Forbidden business wording detected in generated explanation")
    return text


def generate_claim_explanations(scores: pd.DataFrame, details: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, score in scores.iterrows():
        claim_details = details[details["claim_sk"].eq(score["claim_sk"])] if not details.empty else details
        rows.append({
            "claim_sk": score["claim_sk"],
            "claim_business_id": score.get("claim_business_id"),
            "score_run_id": score.get("score_run_id"),
            "score_version": score.get("score_version"),
            "business_summary": generate_claim_explanation(score, claim_details),
        })
    return pd.DataFrame(rows)
