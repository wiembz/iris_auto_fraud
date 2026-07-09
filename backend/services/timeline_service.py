"""Timeline query service for claim detail pages."""
from __future__ import annotations

from sqlalchemy import text

from backend.config import ApiConfig
from backend.services.serialization import rows_to_dicts


def get_timeline(engine, config: ApiConfig, claim_sk: int) -> dict:
    """Build a simple claim timeline from feature and post-inspection marts."""
    events = []
    with engine.connect() as conn:
        feature = conn.execute(
            text(
                """
                SELECT
                    claim_sk,
                    claim_business_id,
                    contract_start_date,
                    claim_date,
                    declaration_date,
                    created_at AS iris_feature_created_at
                FROM mart.fact_claim_scoring_features
                WHERE claim_sk = :claim_sk
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"claim_sk": claim_sk},
        ).first()
        if feature:
            data = feature._mapping
            if data.get("contract_start_date"):
                events.append({
                    "event_type": "Debut contrat",
                    "event_date": data["contract_start_date"],
                    "description": "Date de debut de contrat disponible dans les features IRIS.",
                })
            if data.get("claim_date"):
                events.append({
                    "event_type": "Survenance sinistre",
                    "event_date": data["claim_date"],
                    "description": "Date de survenance du sinistre.",
                })
            if data.get("declaration_date"):
                events.append({
                    "event_type": "Declaration",
                    "event_date": data["declaration_date"],
                    "description": "Date de declaration du dossier.",
                })
            if data.get("iris_feature_created_at"):
                events.append({
                    "event_type": "Calcul IRIS",
                    "event_date": data["iris_feature_created_at"],
                    "description": "Date de calcul des indicateurs IRIS.",
                })

        inspection_rows = conn.execute(
            text(
                """
                SELECT
                    inspection_date,
                    days_inspection_to_claim,
                    defective_zone,
                    business_explanation
                FROM mart.fact_post_inspection_attention_signal
                WHERE claim_sk = :claim_sk
                  AND signal_version = :signal_version
                ORDER BY inspection_date, defective_zone
                """
            ),
            {
                "claim_sk": claim_sk,
                "signal_version": config.post_inspection_signal_version,
            },
        ).fetchall()

    for row in inspection_rows:
        item = row._mapping
        events.append({
            "event_type": "Inspection STAFFIM",
            "event_date": item["inspection_date"],
            "description": (
                f"Inspection avant sinistre, delai de {item['days_inspection_to_claim']} jours, "
                f"zone: {item['defective_zone']}."
            ),
            "business_explanation": item["business_explanation"],
        })

    events = sorted(
        rows_to_dicts(events),
        key=lambda item: (item.get("event_date") or "", item.get("event_type") or ""),
    )
    return {"claim_sk": claim_sk, "items": events}
