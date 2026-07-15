"""Vehicle Health Score (VHS) read-only service for the IRIS frontend API.

Serves the latest VHS run only: scores per inspection (mart.fact_vhs_score)
and per-checkpoint penalties (mart.fact_vhs_penalty_detail). The VHS informs
the claim review with the technical condition of inspected vehicles; it never
takes any decision by itself.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from backend.services.serialization import rows_to_dicts

ALLOWED_DECISIONS = {"OK", "DEGRADE", "CRITIQUE", "IMMOBILISE"}

_LATEST_RUN_SQL = """
    SELECT run_id
    FROM mart.fact_vhs_score
    ORDER BY created_at DESC, run_id DESC
    LIMIT 1
"""

_LIST_COLUMN_NAMES = [
    "vhs_score_sk",
    "inspection_key",
    "vehicule_sk",
    "immatriculation_norm",
    "date_inspection_sk",
    "kilometrage",
    "vhs_final_score",
    "safety_score",
    "functional_score",
    "cosmetic_score",
    "safety_grade",
    "decision",
    "is_drivable",
    "hard_cap_applied",
    "hard_cap_type",
    "nb_anomalies_total",
    "nb_anomalies_critiques",
    "nb_checkpoints_scored",
    "nb_ok",
    "nb_worn",
    "nb_worn_strong",
    "nb_broken",
    # V4-specific columns:
    "nb_systems_penalized",
    "penalty_raw_before_cap",
    "penalty_after_system_cap",
]

_LIST_COLUMNS = ", ".join(_LIST_COLUMN_NAMES)
_LIST_COLUMNS_QUALIFIED = ", ".join(f"s.{name}" for name in _LIST_COLUMN_NAMES)


def _latest_run(conn) -> str | None:
    return conn.execute(text(_LATEST_RUN_SQL)).scalar_one_or_none()


def get_vhs_overview(engine) -> dict[str, Any]:
    """Portfolio-level view of the latest VHS run."""
    with engine.connect() as conn:
        run_id = _latest_run(conn)
        if not run_id:
            return {
                "run_id": None,
                "total_vehicles": 0,
                "average_score": None,
                "decision_distribution": [],
                "grade_distribution": [],
                "score_bands": [],
                "zone_penalties": [],
            }

        params = {"run_id": run_id}

        stats = conn.execute(
            text(
                """
                SELECT COUNT(*) AS total_vehicles,
                       ROUND(AVG(vhs_final_score), 1) AS average_score,
                       COUNT(*) FILTER (WHERE NOT is_drivable) AS not_drivable,
                       COUNT(*) FILTER (WHERE nb_anomalies_critiques > 0) AS with_critical_anomalies
                FROM mart.fact_vhs_score
                WHERE run_id = :run_id
                """
            ),
            params,
        ).first()

        decision_distribution = conn.execute(
            text(
                """
                SELECT decision, COUNT(*) AS vehicles, ROUND(AVG(vhs_final_score), 1) AS average_score
                FROM mart.fact_vhs_score
                WHERE run_id = :run_id
                GROUP BY decision
                """
            ),
            params,
        ).fetchall()

        grade_distribution = conn.execute(
            text(
                """
                SELECT safety_grade, COUNT(*) AS vehicles
                FROM mart.fact_vhs_score
                WHERE run_id = :run_id
                GROUP BY safety_grade
                ORDER BY safety_grade
                """
            ),
            params,
        ).fetchall()

        score_bands = conn.execute(
            text(
                """
                SELECT
                    (LEAST(FLOOR(vhs_final_score / 20), 4) * 20)::int AS band_start,
                    COUNT(*) AS vehicles
                FROM mart.fact_vhs_score
                WHERE run_id = :run_id
                GROUP BY 1
                ORDER BY 1
                """
            ),
            params,
        ).fetchall()

        zone_penalties = conn.execute(
            text(
                """
                SELECT
                    COALESCE(p.zone_controle, d.zone_controle) AS zone_controle,
                    COUNT(*) AS penalty_count,
                    ROUND(SUM(p.penalty_applied), 1) AS total_penalty,
                    COUNT(*) FILTER (WHERE p.est_anomalie_critique) AS critical_count
                FROM mart.fact_vhs_penalty_detail p
                LEFT JOIN mart.dim_checkpoint d ON d.checkpoint_code = p.checkpoint_code
                WHERE p.run_id = :run_id
                  AND p.penalty_applied > 0
                  AND COALESCE(p.zone_controle, d.zone_controle) IS NOT NULL
                GROUP BY 1
                ORDER BY total_penalty DESC
                """
            ),
            params,
        ).fetchall()

    return {
        "run_id": run_id,
        "total_vehicles": stats.total_vehicles,
        "average_score": float(stats.average_score) if stats.average_score is not None else None,
        "not_drivable": stats.not_drivable,
        "with_critical_anomalies": stats.with_critical_anomalies,
        "decision_distribution": rows_to_dicts(decision_distribution),
        "grade_distribution": rows_to_dicts(grade_distribution),
        "score_bands": rows_to_dicts(score_bands),
        "zone_penalties": rows_to_dicts(zone_penalties),
    }


def list_vhs_vehicles(
    engine,
    *,
    decision: str | None = None,
    search: str | None = None,
    limit: int = 300,
) -> dict[str, Any]:
    """Inspected vehicles of the latest run, worst score first."""
    limit = max(1, min(int(limit or 300), 500))
    with engine.connect() as conn:
        run_id = _latest_run(conn)
        if not run_id:
            return {"run_id": None, "items": []}

        where = ["s.run_id = :run_id"]
        params: dict[str, Any] = {"run_id": run_id, "limit": limit}
        if decision in ALLOWED_DECISIONS:
            where.append("s.decision = :decision")
            params["decision"] = decision
        if search:
            where.append("s.immatriculation_norm ILIKE :search")
            params["search"] = f"%{search.strip()}%"

        # total_penalty restaure la discrimination en bas d echelle
        rows = conn.execute(
            text(
                f"""
                SELECT {_LIST_COLUMNS_QUALIFIED},
                       COALESCE(pen.total_penalty, 0) AS total_penalty
                FROM mart.fact_vhs_score s
                LEFT JOIN (
                    SELECT inspection_key, run_id, ROUND(SUM(penalty_applied), 1) AS total_penalty
                    FROM mart.fact_vhs_penalty_detail
                    WHERE penalty_applied > 0
                    GROUP BY inspection_key, run_id
                ) pen ON pen.inspection_key = s.inspection_key AND pen.run_id = s.run_id
                WHERE {' AND '.join(where)}
                ORDER BY s.vhs_final_score ASC, pen.total_penalty DESC NULLS LAST, s.vhs_score_sk
                LIMIT :limit
                """
            ),
            params,
        ).fetchall()

    return {"run_id": run_id, "items": rows_to_dicts(rows)}


def get_vhs_inspection_detail(engine, vhs_score_sk: int) -> dict[str, Any] | None:
    """One inspection score plus every applied penalty, grouped by zone
    frontend-side. Only positive penalties are returned: they are what
    actually lowers the score."""
    with engine.connect() as conn:
        score_row = conn.execute(
            text(
                """
                SELECT 
                    s.vhs_score_sk,
                    s.inspection_key,
                    s.vehicule_sk,
                    s.immatriculation_norm,
                    s.date_inspection_sk,
                    s.kilometrage,
                    s.vhs_final_score,
                    s.safety_score,
                    s.functional_score,
                    s.cosmetic_score,
                    s.safety_grade,
                    s.decision,
                    s.is_drivable,
                    s.hard_cap_applied,
                    s.hard_cap_type,
                    s.nb_anomalies_total,
                    s.nb_anomalies_critiques,
                    s.nb_checkpoints_scored,
                    s.nb_ok,
                    s.nb_worn,
                    s.nb_worn_strong,
                    s.nb_broken,
                    s.nb_systems_penalized,
                    s.penalty_raw_before_cap,
                    s.penalty_after_system_cap,
                    s.run_id,
                    i.nom_agent_inspection,
                    i.nom_personne_inspection,
                    i.telephone_personne_inspection,
                    i.vin,
                    i.motorisation,
                    i.numero_commande_travaux,
                    i.heure_entree,
                    i.horodateur
                FROM mart.fact_vhs_score s
                LEFT JOIN staging.stg_inspection i 
                  ON s.immatriculation_norm = i.immatriculation 
                 AND s.date_inspection_sk = CAST(TO_CHAR(i.date_inspection, 'YYYYMMDD') AS bigint)
                WHERE s.vhs_score_sk = :vhs_score_sk
                LIMIT 1
                """
            ),
            {"vhs_score_sk": vhs_score_sk},
        ).first()
        if not score_row:
            return None

        penalties = conn.execute(
            text(
                """
                SELECT
                    p.checkpoint_code,
                    COALESCE(p.checkpoint_libelle, d.checkpoint_libelle, p.checkpoint_code) AS checkpoint_libelle,
                    COALESCE(p.zone_controle, d.zone_controle) AS zone_controle,
                    p.observed_value,
                    p.observed_status,
                    p.penalty_applied,
                    p.penalty_reason,
                    p.tier,
                    COALESCE(p.is_vital, d.is_vital) AS is_vital,
                    COALESCE(p.is_immobilizing, d.is_immobilizing) AS is_immobilizing,
                    p.is_hard_cap_trigger,
                    p.est_anomalie_critique,
                    p.systeme_fonctionnel,
                    p.penalty_raw_checkpoint,
                    p.penalty_capped_by_system
                FROM mart.fact_vhs_penalty_detail p
                LEFT JOIN mart.dim_checkpoint d ON d.checkpoint_code = p.checkpoint_code
                WHERE p.inspection_key = :inspection_key
                  AND p.run_id = :run_id
                  AND p.penalty_applied > 0
                ORDER BY p.penalty_applied DESC, 3, p.checkpoint_code
                LIMIT 200
                """
            ),
            {"inspection_key": score_row.inspection_key, "run_id": score_row.run_id},
        ).fetchall()

    result = dict(score_row._mapping)
    result["penalties"] = rows_to_dicts(penalties)
    return result


def get_vhs_inspection_detail_by_key(
    engine, immatriculation: str, date_inspection_sk: int
) -> dict[str, Any] | None:
    """Resolve a VHS inspection from the LATEST run using immatriculation + date_sk.

    The inspection_sk stored in fact_post_inspection_attention_signal may point to
    a stale run (an older VHS run ID). This function always returns data from the
    most recent VHS run for the given vehicle/date combination.
    """
    with engine.connect() as conn:
        latest_run = _latest_run(conn)
        if not latest_run:
            return None

        score_row = conn.execute(
            text(
                """
                SELECT 
                    s.vhs_score_sk,
                    s.inspection_key,
                    s.vehicule_sk,
                    s.immatriculation_norm,
                    s.date_inspection_sk,
                    s.kilometrage,
                    s.vhs_final_score,
                    s.safety_score,
                    s.functional_score,
                    s.cosmetic_score,
                    s.safety_grade,
                    s.decision,
                    s.is_drivable,
                    s.hard_cap_applied,
                    s.hard_cap_type,
                    s.nb_anomalies_total,
                    s.nb_anomalies_critiques,
                    s.nb_checkpoints_scored,
                    s.nb_ok,
                    s.nb_worn,
                    s.nb_worn_strong,
                    s.nb_broken,
                    s.nb_systems_penalized,
                    s.penalty_raw_before_cap,
                    s.penalty_after_system_cap,
                    s.run_id,
                    i.nom_agent_inspection,
                    i.nom_personne_inspection,
                    i.telephone_personne_inspection,
                    i.vin,
                    i.motorisation,
                    i.numero_commande_travaux,
                    i.heure_entree,
                    i.horodateur
                FROM mart.fact_vhs_score s
                LEFT JOIN staging.stg_inspection i 
                  ON s.immatriculation_norm = i.immatriculation 
                 AND s.date_inspection_sk = CAST(TO_CHAR(i.date_inspection, 'YYYYMMDD') AS bigint)
                WHERE s.immatriculation_norm = :immatriculation
                  AND s.date_inspection_sk = :date_inspection_sk
                  AND s.run_id = :run_id
                ORDER BY s.vhs_score_sk DESC
                LIMIT 1
                """
            ),
            {
                "immatriculation": immatriculation.strip().upper(),
                "date_inspection_sk": date_inspection_sk,
                "run_id": latest_run,
            },
        ).first()
        if not score_row:
            return None

        penalties = conn.execute(
            text(
                """
                SELECT
                    p.checkpoint_code,
                    COALESCE(p.checkpoint_libelle, d.checkpoint_libelle, p.checkpoint_code) AS checkpoint_libelle,
                    COALESCE(p.zone_controle, d.zone_controle) AS zone_controle,
                    p.observed_value,
                    p.observed_status,
                    p.penalty_applied,
                    p.penalty_reason,
                    p.tier,
                    COALESCE(p.is_vital, d.is_vital) AS is_vital,
                    COALESCE(p.is_immobilizing, d.is_immobilizing) AS is_immobilizing,
                    p.is_hard_cap_trigger,
                    p.est_anomalie_critique,
                    p.systeme_fonctionnel,
                    p.penalty_raw_checkpoint,
                    p.penalty_capped_by_system
                FROM mart.fact_vhs_penalty_detail p
                LEFT JOIN mart.dim_checkpoint d ON d.checkpoint_code = p.checkpoint_code
                WHERE p.inspection_key = :inspection_key
                  AND p.run_id = :run_id
                  AND p.penalty_applied > 0
                ORDER BY p.penalty_applied DESC, 3, p.checkpoint_code
                LIMIT 200
                """
            ),
            {"inspection_key": score_row.inspection_key, "run_id": score_row.run_id},
        ).fetchall()

    result = dict(score_row._mapping)
    result["penalties"] = rows_to_dicts(penalties)
    return result

