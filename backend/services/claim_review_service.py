"""Aggregated read-only claim review service for the IRIS frontend API."""
from __future__ import annotations

import ast
import json
from sqlalchemy import text

from backend.config import ApiConfig
from backend.services.claims_service import _latest_ml_run, _latest_post_inspection_run, _latest_score_run
from backend.services.serialization import row_to_dict, rows_to_dicts


def _parse_signal_value(val) -> dict:
    if not val:
        return {}
    if isinstance(val, dict):
        return val
    val_str = str(val).strip()
    if val_str.startswith("{"):
        try:
            return json.loads(val_str)
        except Exception:
            try:
                return ast.literal_eval(val_str)
            except Exception:
                pass
    # Parse key=value; key=value
    res = {}
    for part in val_str.split(";"):
        if "=" in part:
            parts = part.split("=", 1)
            k = parts[0].strip()
            v = parts[1].strip()
            try:
                if v.lower() in ("true", "false"):
                    res[k] = v.lower() == "true"
                else:
                    res[k] = float(v)
            except Exception:
                res[k] = v
    return res



def _confidence_explanation(
    conf_level,
    missing_keys: int,
    unknown_dims: int,
    weak_join: bool,
    missing_driver: bool,
    missing_client: bool,
) -> str:
    """Build the human-readable data-quality badge text.

    An unresolved driver/client identity is a material limitation even when
    confidence_level is HIGH (that tier only checks missing_keys_count and
    unknown_dimensions_count, not driver identity specifically) -- never
    claim "qualite optimale" in that case.
    """
    identity_gaps = []
    if missing_driver:
        identity_gaps.append("conducteur non identifié")
    if missing_client:
        identity_gaps.append("client non identifié")

    if identity_gaps:
        return f"Qualité partielle — {', '.join(identity_gaps)}."

    if conf_level == "HIGH" or conf_level == "Elevee":
        return "Qualité de données optimale : aucune clé manquante, jointures complètes, géolocalisation cohérente."

    reasons = []
    if missing_keys > 0:
        reasons.append(f"{missing_keys} clé(s) manquante(s)")
    if unknown_dims > 0:
        reasons.append(f"{unknown_dims} dimension(s) non mappée(s)")

    if conf_level == "MEDIUM" or conf_level == "Moyenne":
        if weak_join:
            reasons.append("jointures faibles détectées")
        return f"Confiance modérée : {', '.join(reasons)}."

    if weak_join:
        reasons.append("jointures défaillantes")
    return f"Confiance limitée : {', '.join(reasons)}."


def _contract_validity_at_claim_date(contract_row, claim_date) -> dict | None:
    """Was the contract in effect on the day the claim occurred?

    Prefers date_debut_effet/date_fin_effet (the actual coverage window, which
    can differ from the nominal contract term after avenants) and falls back
    to date_debut_contrat/date_fin_contrat when effet dates are missing. Both
    the computed answer and the raw statut_contrat are returned so a manager
    can spot a discrepancy (e.g. dates say valid but statut says resilie)
    instead of trusting a single ambiguous label.
    """
    if not contract_row or not claim_date:
        return None
    data = contract_row._mapping
    debut = data.get("date_debut_effet") or data.get("date_debut_contrat")
    fin = data.get("date_fin_effet") or data.get("date_fin_contrat")
    if not debut:
        return {
            "is_valid_at_claim_date": None,
            "reference": None,
            "statut_contrat": data.get("statut_contrat"),
        }
    reference = "effet" if data.get("date_debut_effet") else "contrat"
    # dwh.fact_sinistre.claim_date is a DATE column but dwh.dim_contrat's dates
    # are TIMESTAMP -- comparing date to datetime raises TypeError, so normalize
    # everything to date() before comparing.
    _as_date = lambda v: v.date() if hasattr(v, "date") else v
    claim_date, debut, fin = _as_date(claim_date), _as_date(debut), _as_date(fin)
    is_valid = debut <= claim_date and (fin is None or claim_date <= fin)
    return {
        "is_valid_at_claim_date": is_valid,
        "reference": reference,
        "statut_contrat": data.get("statut_contrat"),
    }


def _timeline_from_feature_and_inspections(feature_row, inspection_rows) -> list[dict]:
    events = []
    if feature_row:
        data = feature_row._mapping
        if data.get("contract_start_date"):
            events.append({
                "event_type": "Debut contrat",
                "event_date": data["contract_start_date"],
                "description": "Debut du contrat couvrant le vehicule.",
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
                "event_type": "Analyse IRIS",
                "event_date": data["created_at"],
                "description": "Derniere analyse du dossier par IRIS.",
            })

    # Une inspection STAFIM produit un signal par zone de checkpoint defectueuse
    # (meme inspection_sk) : regrouper en UN seul evenement chronologique, sinon
    # les zones d'une meme inspection apparaissent comme des inspections
    # distinctes separees par un faux delai "0 jour".
    inspections_by_key: dict[object, list] = {}
    inspection_order: list[object] = []
    for row in inspection_rows:
        item = row._mapping
        key = item.get("inspection_sk") or (item.get("inspection_date"), item.get("vehicule_sk"))
        if key not in inspections_by_key:
            inspections_by_key[key] = []
            inspection_order.append(key)
        inspections_by_key[key].append(item)

    for key in inspection_order:
        items = inspections_by_key[key]
        first = items[0]
        zones = sorted({it["defective_zone"] for it in items if it.get("defective_zone")})
        events.append({
            "event_type": "Inspection STAFFIM",
            "event_date": first["inspection_date"],
            "description": (
                f"Inspection avant sinistre, delai de {first['days_inspection_to_claim']} jours, "
                f"zone(s): {', '.join(zones) if zones else 'non renseignee'}."
            ),
            "business_explanation": first["business_explanation"],
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
                    f.missing_driver_flag,
                    f.missing_client_flag,
                    f.weak_join_flag,
                    f.vehicle_recurrence_ready_flag,
                    f.conducteur_sk,
                    f.tiers_sk,
                    f.claim_geo_sk
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

        # Financial/guarantee fields are descriptive, not scoring inputs: they
        # are read from the LATEST feature row for this claim, independently
        # of the score's pinned feature_run_id. Pinning them the same way as
        # the scoring fields would leave them NULL for every already-scored
        # claim whenever these columns are added or refreshed without a full
        # rescore (ALTER TABLE backfills existing rows with NULL, and a new
        # feature run gets a feature_run_id the score row doesn't reference).
        financial_row = conn.execute(
            text(
                """
                SELECT reserve_amount, paid_amount, recourse_amount, franchise_amount,
                       guarantee_status, is_closed
                FROM mart.fact_claim_scoring_features
                WHERE claim_sk = :claim_sk
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"claim_sk": claim_sk},
        ).first()

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

        # DWH context queries
        client_row = None
        if claim_row and claim_row._mapping.get("client_sk"):
            client_row = conn.execute(
                text(
                    """
                    SELECT client_sk, idclt, nature_client, date_naissance, situation_familiale, sexe, localite, gouvernor
                    FROM dwh.dim_client
                    WHERE client_sk = :client_sk
                    """
                ),
                {"client_sk": claim_row._mapping["client_sk"]},
            ).first()

        contract_row = None
        if claim_row and claim_row._mapping.get("contrat_sk"):
            contract_row = conn.execute(
                text(
                    """
                    SELECT contrat_sk, numero_contrat, date_debut_contrat, date_fin_contrat,
                           date_debut_effet, date_fin_effet, statut_contrat,
                           type_resiliation, libelle_resiliation
                    FROM dwh.dim_contrat
                    WHERE contrat_sk = :contrat_sk
                    """
                ),
                {"contrat_sk": claim_row._mapping["contrat_sk"]},
            ).first()

        conducteur_row = None
        if claim_row and claim_row._mapping.get("conducteur_sk"):
            conducteur_row = conn.execute(
                text(
                    """
                    SELECT conducteur_sk, nom_conducteur, numero_permis, age_conducteur, categorie_permis, date_permis
                    FROM dwh.dim_conducteur
                    WHERE conducteur_sk = :conducteur_sk
                    """
                ),
                {"conducteur_sk": claim_row._mapping["conducteur_sk"]},
            ).first()

        tiers_row = None
        if claim_row and claim_row._mapping.get("tiers_sk"):
            tiers_row = conn.execute(
                text(
                    """
                    SELECT tiers_sk, nom_tiers, immatriculation_vehicule_tiers, numero_contrat_tiers
                    FROM dwh.dim_tiers
                    WHERE tiers_sk = :tiers_sk
                    """
                ),
                {"tiers_sk": claim_row._mapping["tiers_sk"]},
            ).first()

        geo_row = None
        if claim_row and claim_row._mapping.get("claim_geo_sk"):
            geo_row = conn.execute(
                text(
                    """
                    SELECT geo_sk, region, gouvernorat, localite, pays
                    FROM dwh.dim_geo
                    WHERE geo_sk = :geo_sk
                    """
                ),
                {"geo_sk": claim_row._mapping["claim_geo_sk"]},
            ).first()

        same_sinistre_rows = []
        client_history_rows = []
        claim_map = claim_row._mapping if claim_row else {}
        if claim_map.get("numero_sinistre"):
            
            same_sinistre_rows = conn.execute(
                text(
                    """
                    SELECT
                        f.claim_sk,
                        f.claim_business_id,
                        f.numero_sinistre,
                        f.code_garantie,
                        f.claim_date,
                        f.claim_amount,
                        s.attention_score,
                        s.attention_level
                    FROM mart.fact_claim_scoring_features f
                    LEFT JOIN mart.fact_claim_attention_score s
                      ON s.claim_sk = f.claim_sk
                     AND s.feature_run_id = f.feature_run_id
                     AND s.score_version = :score_version
                     AND s.score_run_id = :score_run_id
                    WHERE f.feature_run_id = :feature_run_id
                      AND f.numero_sinistre = :numero_sinistre
                    ORDER BY f.code_garantie NULLS LAST, f.claim_sk
                    """
                ),
                {
                    "feature_run_id": claim_map.get("feature_run_id"),
                    "numero_sinistre": claim_map.get("numero_sinistre"),
                    "score_version": selected_version,
                    "score_run_id": selected_score_run_id,
                },
            ).fetchall()

        if claim_map.get("client_sk") and claim_map.get("claim_date"):
            
            client_history_rows = conn.execute(
                text(
                    """
                    SELECT
                        f.claim_sk,
                        f.claim_business_id,
                        f.numero_sinistre,
                        f.code_garantie,
                        f.claim_date,
                        f.claim_amount,
                        f.days_claim_to_declaration
                    FROM mart.fact_claim_scoring_features f
                    WHERE f.feature_run_id = :feature_run_id
                      AND f.client_sk = :client_sk
                      AND f.claim_date < :claim_date
                      AND f.claim_date >= (CAST(:claim_date AS date) - INTERVAL '24 months')
                    ORDER BY f.claim_date DESC, f.numero_sinistre, f.code_garantie
                    LIMIT 50
                    """
                ),
                {
                    "feature_run_id": claim_map.get("feature_run_id"),
                    "client_sk": claim_map.get("client_sk"),
                    "claim_date": claim_map.get("claim_date"),
                },
            ).fetchall()

        vhs_row = None
        if claim_row and claim_row._mapping.get("vehicle_sk"):
            vhs_row = conn.execute(
                text(
                    """
                    SELECT vhs_final_score, safety_grade, decision, kilometrage, nb_anomalies_total, nb_anomalies_critiques
                    FROM mart.fact_vhs_score
                    WHERE vehicule_sk = :vehicle_sk
                    ORDER BY date_inspection_sk DESC, calculated_at DESC
                    LIMIT 1
                    """
                ),
                {"vehicle_sk": claim_row._mapping["vehicle_sk"]},
            ).first()

    claim_data = row_to_dict(claim_row)
    if financial_row:
        claim_data.update(row_to_dict(financial_row))

    # 1. Parse and enrich signals
    signal_items = rows_to_dicts(signal_rows)
    for sig in signal_items:
        if sig.get("signal_code") == "AMOUNT_HIGH_BY_GUARANTEE":
            parsed_val = _parse_signal_value(sig.get("signal_value"))
            ratio = parsed_val.get("ratio")
            percentile = parsed_val.get("percentile")
            amount = claim_data.get("claim_amount")
            garantie = claim_data.get("code_garantie", "CAS")
            
            explanation_parts = []
            if amount is not None:
                explanation_parts.append(f"Montant réclamé : {amount:,.0f} TND")
            if ratio is not None:
                try:
                    f_ratio = float(ratio)
                    explanation_parts.append(f"{f_ratio:.1f}x la médiane observée pour la garantie {garantie}")
                except Exception:
                    explanation_parts.append(f"{ratio} la médiane")
            if percentile is not None:
                try:
                    f_pct = float(percentile)
                    explanation_parts.append(f"supérieur à {f_pct * 100:.1f}% des sinistres comparables")
                except Exception:
                    explanation_parts.append(f"percentile {percentile}")
            
            if explanation_parts:
                sig["business_explanation"] = f"{sig.get('business_explanation', '')} (Détails : {', '.join(explanation_parts)})."

    # 2. Confidence Level explanation
    confidence_explanation = _confidence_explanation(
        claim_data.get("confidence_level"),
        claim_data.get("missing_keys_count", 0),
        claim_data.get("unknown_dimensions_count", 0),
        claim_data.get("weak_join_flag", False),
        claim_data.get("missing_driver_flag", False),
        claim_data.get("missing_client_flag", False),
    )
    claim_data["confidence_explanation"] = confidence_explanation

    # 3. Dynamic Checklist
    checklist = []
    active_codes = {sig.get("signal_code") for sig in signal_items}
    
    # 3.1. Post-inspection check
    post_inspection_active = any(code.startswith("POST_INSPECTION") for code in active_codes)
    if post_inspection_active and len(post_rows) > 0:
        latest_pi = max(post_rows, key=lambda pi: pi._mapping.get("inspection_date") or "")
        pi_date = latest_pi._mapping.get("inspection_date")
        if pi_date:
            formatted_date = pi_date.strftime("%d/%m/%Y") if hasattr(pi_date, "strftime") else str(pi_date)[:10]
            checklist.append(f"Comparer les dommages déclarés avec les observations de l'inspection STAFIM du {formatted_date}.")
        else:
            checklist.append("Comparer les dommages déclarés avec les observations de l'inspection STAFIM.")
    else:
        checklist.append("Vérifier la cohérence des dommages déclarés avec les photos du sinistre.")
        
    # 3.2. Delay check
    if "CH01_LONG_DELAY_DECLARATION" in active_codes or (claim_data.get("days_claim_to_declaration") and claim_data.get("days_claim_to_declaration", 0) > 30):
        days = claim_data.get("days_claim_to_declaration", 99)
        checklist.append(f"Demander la justification du délai de déclaration long de {days} jours.")
        
    # 3.3. Client recurrence check
    if "CLIENT_CLAIMS_12M_HIGH" in active_codes or (claim_data.get("client_claim_count_24m") and claim_data.get("client_claim_count_24m", 0) > 3):
        client_count = claim_data.get("client_claim_count_24m", 5)
        garantie = claim_data.get("code_garantie", "CAS")
        checklist.append(f"Vérifier l'historique des garanties {garantie} du client sur les 24 derniers mois ({client_count} sinistres trouvés).")
        
    # 3.4. Vehicle frequency check
    if "VEHICLE_CLAIMS_12M_HIGH" in active_codes:
        checklist.append("Vérifier l'historique des sinistres de ce véhicule (fréquence élevée).")
        
    # 3.5. Amount check
    if "AMOUNT_HIGH_BY_GUARANTEE" in active_codes:
        amount = claim_data.get("claim_amount")
        garantie = claim_data.get("code_garantie", "CAS")
        if amount:
            checklist.append(f"Vérifier la cohérence du montant réclamé de {amount:,.0f} TND avec la nature des dommages.")
        else:
            checklist.append("Vérifier la cohérence du montant réclamé.")
            
    # 3.6. ML atypicity check
    if "ML_ANOMALY_HIGH" in active_codes or (ml_row and ml_row._mapping.get("anomaly_percentile_score", 0) > 0.9):
        checklist.append("Analyser les variables atypiques détectées par l'Isolation Forest.")

    # Generic checklist fallbacks to ensure at least 3 checklist items
    if len(checklist) < 3:
        checklist.append("Contrôler la validité et la lisibilité des pièces justificatives (constat, permis).")
    if len(checklist) < 3:
        checklist.append("Rechercher d'éventuels liens d'intérêt entre le conducteur et le tiers impliqué.")

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
            "items": signal_items,
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
        "related_claims": {
            "same_sinistre_guarantees": rows_to_dicts(same_sinistre_rows),
            "client_history_24m": rows_to_dicts(client_history_rows),
        },
        "checklist": checklist,
        "client_context": row_to_dict(client_row) if client_row else None,
        "contract_context": {
            **(row_to_dict(contract_row) if contract_row else {}),
            "validity_at_claim_date": _contract_validity_at_claim_date(
                contract_row, claim_row._mapping.get("claim_date") if claim_row else None
            ),
        } if contract_row else None,
        "conducteur_context": row_to_dict(conducteur_row) if conducteur_row else None,
        "tiers_context": row_to_dict(tiers_row) if tiers_row else None,
        "geo_context": row_to_dict(geo_row) if geo_row else None,
        "vhs_context": row_to_dict(vhs_row) if vhs_row else None,
    }


