"""
etl/dwh/backfill_unknown_dimension_rows.py
==========================================
Backfill idempotent des lignes techniques UNKNOWN (sk = 0) dans les
dimensions référencées par les facts.

Les loaders (load_dim_*.py) créent désormais cette ligne à chaque run ;
ce script aligne une base déjà chargée SANS relancer les loaders, donc
sans toucher aux SK existants ni aux facts (qui utilisent déjà sk = 0
comme convention "inconnu").

Idempotent : chaque INSERT est protégé par NOT EXISTS (sk = 0).
Relançable sans effet si les lignes existent déjà.

Usage :
  python etl/dwh/backfill_unknown_dimension_rows.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwh_utils

# (table, sk column, INSERT statement)
# Chaque INSERT reproduit exactement la ligne technique émise par le loader.
BACKFILL_STATEMENTS: list[tuple[str, str, str]] = [
    (
        "dim_client",
        "client_sk",
        """
        INSERT INTO dwh.dim_client
            (client_sk, idclt, typeid, id_piece, nature_client,
             adr1, cpost, cite, gouvernor, pays, localite,
             date_naissance, sexe, nombre_enfant, situation_familiale,
             source_system, created_at)
        SELECT 0, 'UNKNOWN', NULL, NULL, 'UNKNOWN',
               NULL, NULL, NULL, 'UNKNOWN', 'UNKNOWN', 'UNKNOWN',
               NULL, 'UNKNOWN', NULL, NULL,
               'TECHNICAL', :now
        WHERE NOT EXISTS (SELECT 1 FROM dwh.dim_client WHERE client_sk = 0)
        """,
    ),
    (
        "dim_vehicule",
        "vehicule_sk",
        """
        INSERT INTO dwh.dim_vehicule
            (vehicule_sk, immatriculation, vin, motorisation, source_system, created_at)
        SELECT 0, 'UNKNOWN', NULL, NULL, 'TECHNICAL', :now
        WHERE NOT EXISTS (SELECT 1 FROM dwh.dim_vehicule WHERE vehicule_sk = 0)
        """,
    ),
    (
        "dim_camtier",
        "camtier_sk",
        """
        INSERT INTO dwh.dim_camtier
            (camtier_sk, nature_camtier, id_camtier, code_camtier, source_system, created_at)
        SELECT 0, 'UNKNOWN', 'UNKNOWN', 'UNKNOWN', 'TECHNICAL', :now
        WHERE NOT EXISTS (SELECT 1 FROM dwh.dim_camtier WHERE camtier_sk = 0)
        """,
    ),
    (
        "dim_intermediaire",
        "intermediaire_sk",
        """
        INSERT INTO dwh.dim_intermediaire
            (intermediaire_sk, code_intermediaire, nature_intermediaire,
             id_intermediaire, libelle_intermediaire, source_system, created_at)
        SELECT 0, 'UNKNOWN', 'UNKNOWN', 'UNKNOWN', 'UNKNOWN', 'TECHNICAL', :now
        WHERE NOT EXISTS (SELECT 1 FROM dwh.dim_intermediaire WHERE intermediaire_sk = 0)
        """,
    ),
    (
        "dim_produit",
        "produit_sk",
        """
        INSERT INTO dwh.dim_produit
            (produit_sk, code_produit, libelle_produit, code_famille,
             libelle_famille, source_system, created_at)
        SELECT 0, 'UNKNOWN', 'UNKNOWN', 'UNKNOWN', 'UNKNOWN', 'TECHNICAL', :now
        WHERE NOT EXISTS (SELECT 1 FROM dwh.dim_produit WHERE produit_sk = 0)
        """,
    ),
    (
        "dim_sinistre",
        "sinistre_sk",
        """
        INSERT INTO dwh.dim_sinistre
            (sinistre_sk, numero_sinistre, cause_sinistre, libelle_cause_sinistre,
             code_etat, indicateur_forcage, cas_ida, coassur, reassur,
             indicateur_transaction, source_system, created_at)
        SELECT 0, 'UNKNOWN', NULL, NULL,
               NULL, 'NON_RENSEIGNE', NULL, 'NON_RENSEIGNE', 'NON_RENSEIGNE',
               'NON_RENSEIGNE', 'TECHNICAL', :now
        WHERE NOT EXISTS (SELECT 1 FROM dwh.dim_sinistre WHERE sinistre_sk = 0)
        """,
    ),
    (
        "dim_date",
        "date_sk",
        """
        INSERT INTO dwh.dim_date
            (date_sk, date_complete, annee, trimestre, mois, libelle_mois,
             jour, jour_semaine, libelle_jour, semaine_annee, est_weekend)
        SELECT 0, NULL, 0, 0, 0, 'UNKNOWN',
               0, 0, 'UNKNOWN', 0, FALSE
        WHERE NOT EXISTS (SELECT 1 FROM dwh.dim_date WHERE date_sk = 0)
        """,
    ),
]


def backfill_unknown_rows(engine, logger) -> dict[str, int]:
    """Insère les lignes techniques manquantes. Retourne {table: lignes insérées}."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    inserted: dict[str, int] = {}
    with engine.begin() as conn:
        for table, sk_col, stmt in BACKFILL_STATEMENTS:
            params = {"now": now} if ":now" in stmt else {}
            result = conn.execute(text(stmt), params)
            n = result.rowcount if result.rowcount is not None else 0
            inserted[table] = n
            status = "insérée" if n else "déjà présente"
            logger.info(f"  dwh.{table:<20} ligne {sk_col}=0 : {status}")
    return inserted


def main() -> int:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logger = dwh_utils.setup_logging(run_id, log_name="backfill_unknown_dimension_rows")
    engine = dwh_utils.build_engine(logger)

    logger.info(f"[RUN {run_id}] backfill lignes techniques UNKNOWN (sk = 0)")
    inserted = backfill_unknown_rows(engine, logger)
    total = sum(inserted.values())
    logger.info("=" * 60)
    logger.info(f"  lignes techniques insérées : {total}")
    logger.info(f"  dimensions déjà conformes  : {sum(1 for n in inserted.values() if n == 0)}")
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
