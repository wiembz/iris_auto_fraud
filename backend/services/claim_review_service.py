"""Aggregated read-only claim review service for the IRIS frontend API."""
from __future__ import annotations

from sqlalchemy import text

from backend.config import ApiConfig
from backend.services.claims_service import _latest_ml_run, _latest_post_inspection_run, _latest_score_run
from backend.services.serialization import row_to_dict, rows_to_dicts


def _timeline_from_feature_and_inspections(feature_row, inspection_rows) -> list[dict]:
    events = []
    if feature_row:
        data = feature_row._mapping
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
        if data.get("created_at"):
            events.append({
                "event_type": "Calcul IRIS",
                "event_date": data["created_at"],
                "description": "Date de calcul des indicateurs IRIS.",
            })

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

    return sorted(
        rows_to_dicts(events),
        key=lambda item: (item.get("event_date") or "", item.get("event_type") or ""),
    )


def get_claim_review(
    engine,
    config: ApiConfig,
    claim_sk: int,
    score_version: str | None = None,
    score_run_id: str | None = None,
    ml_signal_run_id: str | None = None,
    post_inspection_signal_run_id: str | None = None,
) -> dict | None:
    """Return the complete claim review payload with one database connection."""
    selected_version = score_version or config.default_score_version

    with engine.connect() as conn:
        selected_score_run_id = score_run_id or _latest_score_run(conn, selected_version)
        if not selected_score_run_id:
            return None

        ml_run_id = ml_signal_run_id or _latest_ml_run(conn, config)
        post_run_id = post_inspection_signal_run_id or _latest_post_inspection_run(conn, config)

        claim_row = conn.execute(
            text(
                """
                SELECT
                    s.claim_sk,
                    s.claim_business_id,
                    s.attention_score,
                    s.attention_level,
                    s.confidence_level,
                    s.main_reason_1,
                    s.main_reason_2,
                    s.main_reason_3,
                    s.score_version,
                    s.score_run_id,
                    s.feature_run_id,
                    s.created_at,
                    f.numero_sinistre,
                    f.code_garantie,
                    f.client_sk,
                    f.contrat_sk,
                    f.vehicle_sk,
                    f.claim_date,
                    f.declaration_date,
                    f.contract_start_date,
                    f.claim_amount,
                    f.client_claim_count_12m,
                    f.client_claim_count_24m,
                    f.days_claim_to_declaration,
                    f.days_contract_start_to_claim,
                    f.missing_keys_count,
                    f.unknown_dimensions_count,
                    f.missing_vehicle_flag,
                    f.vehicle_recurrence_ready_flag
                FROM mart.fact_claim_attention_score s
                LEFT JOIN mart.fact_claim_scoring_features f
                    ON f.claim_sk = s.claim_sk
                   AND f.feature_run_id = s.feature_run_id
                WHERE s.claim_sk = :claim_sk
                  AND s.score_version = :score_version
                  AND s.score_run_id = :score_run_id
                LIMIT 1
                """
            ),
            {
                "claim_sk": claim_sk,
                "score_version": selected_version,
                "score_run_id": selected_score_run_id,
            },
        ).first()
        if not claim_row:
            return None

        signal_rows = conn.execute(
            text(
                """
                SELECT
                    claim_sk,
                    claim_business_id,
                    signal_family,
                    signal_code,
                    signal_label,
                    signal_value,
                    points,
                    severity,
                    business_explanation,
                    score_version,
                    score_run_id,
                    created_at
                FROM mart.fact_claim_attention_signal_detail
                WHERE claim_sk = :claim_sk
                  AND score_version = :score_version
                  AND score_run_id = :score_run_id
                ORDER BY points DESC, signal_family, signal_code
                LIMIT 100
                """
            ),
            {
                "claim_sk": claim_sk,
                "score_version": selected_version,
                "score_run_id": selected_score_run_id,
            },
        ).fetchall()

        post_rows = []
        if post_run_id:
            post_rows = conn.execute(
                text(
                    """
                    SELECT
                        signal_run_id,
                        signal_version,
                        scenario_code,
                        scenario_label,
                        inspection_sk,
                        claim_sk,
                        contract_sk,
                        client_sk,
                        vehicule_sk,
                        immatriculation,
                        inspection_date,
                        claim_date,
                        days_inspection_to_claim,
                        delay_bucket,
                        defective_zone,
                        defective_checkpoint_count,
                        critical_checkpoint_count,
                        representative_checkpoint_labels,
                        claim_area,
                        claim_guarantee_code,
                        claim_guarantee_label,
                        zone_match_status,
                        linkage_method,
                        attention_level,
                        confidence_level,
                        business_explanation,
                        created_at
                    FROM mart.fact_post_inspection_attention_signal
                    WHERE claim_sk = :claim_sk
                      AND signal_version = :signal_version
                      AND signal_run_id = :signal_run_id
                    ORDER BY days_inspection_to_claim, defective_zone
                    LIMIT 50
                    """
                ),
                {
                    "claim_sk": claim_sk,
                    "signal_version": config.post_inspection_signal_version,
                    "signal_run_id": post_run_id,
                },
            ).fetchall()

        ml_row = None
        if ml_run_id:
            ml_row = conn.execute(
                text(
                    """
                    SELECT
                        claim_sk,
                        claim_business_id,
                        signal_version,
                        signal_run_id,
                        raw_anomaly_score,
                        anomaly_percentile_score,
                        score_ml,
                        ml_attention_points,
                        ml_attention_level,
                        top_variable_1,
                        top_variable_2,
                        top_variable_3,
                        created_at
                    FROM mart.fact_claim_ml_anomaly_signal
                    WHERE claim_sk = :claim_sk
                      AND signal_version = :signal_version
                      AND signal_run_id = :signal_run_id
                    LIMIT 1
                    """
                ),
                {
                    "claim_sk": claim_sk,
                    "signal_version": config.ml_signal_version,
                    "signal_run_id": ml_run_id,
                },
            ).first()

    claim_data = row_to_dict(claim_row)
    vehicle_data = {
        "claim_sk": claim_data.get("claim_sk"),
        "claim_business_id": claim_data.get("claim_business_id"),
        "vehicle_sk": claim_data.get("vehicle_sk"),
        "missing_vehicle_flag": claim_data.get("missing_vehicle_flag"),
        "vehicle_recurrence_ready_flag": claim_data.get("vehicle_recurrence_ready_flag"),
        "immatriculation": next(
            (row._mapping.get("immatriculation") for row in post_rows if row._mapping.get("immatriculation")),
            None,
        ),
        "post_inspection_signal_count": len(post_rows),
    }

    return {
        "claim": claim_data,
        "signals": {
            "score_version": selected_version,
            "score_run_id": selected_score_run_id,
            "items": rows_to_dicts(signal_rows),
        },
        "timeline": {
            "claim_sk": claim_sk,
            "items": _timeline_from_feature_and_inspections(claim_row, post_rows),
        },
        "post_inspection": {
            "signal_version": config.post_inspection_signal_version,
            "signal_run_id": post_run_id,
            "items": rows_to_dicts(post_rows),
        },
        "ml_anomaly": row_to_dict(ml_row) if ml_row else None,
        "vehicle": vehicle_data,
    }
