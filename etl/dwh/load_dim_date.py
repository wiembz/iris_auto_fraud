
"""
etl/dwh/load_dim_date.py
========================
Génère et charge la dimension calendrier dwh.dim_date.

Plage couverte : 2010-01-01 -> 2035-12-31
Clé technique  : date_sk = AAAAMMJJ

Structure :
  date_sk         INTEGER PRIMARY KEY
  date_complete   DATE
  annee           INTEGER
  trimestre       INTEGER
  mois            INTEGER
  libelle_mois    TEXT
  jour            INTEGER
  jour_semaine    INTEGER  (1=lundi ... 7=dimanche)
  libelle_jour    TEXT
  semaine_annee   INTEGER
  est_weekend     BOOLEAN

Usage :
  python etl/dwh/load_dim_date.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwh_utils


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
DATE_DEBUT = "2010-01-01"
DATE_FIN = "2035-12-31"
TABLE_NAME = "dim_date"

LIBELLES_MOIS = {
    1: "Janvier",
    2: "Février",
    3: "Mars",
    4: "Avril",
    5: "Mai",
    6: "Juin",
    7: "Juillet",
    8: "Août",
    9: "Septembre",
    10: "Octobre",
    11: "Novembre",
    12: "Décembre",
}

LIBELLES_JOURS = {
    1: "Lundi",
    2: "Mardi",
    3: "Mercredi",
    4: "Jeudi",
    5: "Vendredi",
    6: "Samedi",
    7: "Dimanche",
}


# ---------------------------------------------------------------------------
# Génération de la dimension
# ---------------------------------------------------------------------------
def build_dim_date(date_debut: str = DATE_DEBUT, date_fin: str = DATE_FIN) -> pd.DataFrame:
    """
    Génère un DataFrame représentant la dimension calendrier.
    La colonne jour_semaine suit la convention ISO :
    1 = lundi, 7 = dimanche.
    """
    dates = pd.date_range(start=date_debut, end=date_fin, freq="D")

    df = pd.DataFrame({"date_complete": dates})

    df["date_sk"] = df["date_complete"].dt.strftime("%Y%m%d").astype(int)
    df["annee"] = df["date_complete"].dt.year
    df["trimestre"] = df["date_complete"].dt.quarter
    df["mois"] = df["date_complete"].dt.month
    df["libelle_mois"] = df["mois"].map(LIBELLES_MOIS)
    df["jour"] = df["date_complete"].dt.day
    df["jour_semaine"] = df["date_complete"].dt.isocalendar().day.astype(int)
    df["libelle_jour"] = df["jour_semaine"].map(LIBELLES_JOURS)
    df["semaine_annee"] = df["date_complete"].dt.isocalendar().week.astype(int)
    df["est_weekend"] = df["jour_semaine"].isin([6, 7])

    df = df[
        [
            "date_sk",
            "date_complete",
            "annee",
            "trimestre",
            "mois",
            "libelle_mois",
            "jour",
            "jour_semaine",
            "libelle_jour",
            "semaine_annee",
            "est_weekend",
        ]
    ]

    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Chargement
# ---------------------------------------------------------------------------
def load_dim_date(run_id: str, engine, logger) -> int:
    """
    Génère dim_date et la charge dans dwh.dim_date.
    Retourne le nombre de lignes chargées.
    """
    logger.info(f"Génération dim_date : {DATE_DEBUT} -> {DATE_FIN}")

    df = build_dim_date()

    logger.info(f"  Nombre de jours générés : {len(df)}")

    n_rows, elapsed = dwh_utils.write_to_dwh(df, engine, TABLE_NAME, logger)

    logger.info(f"  Chargement terminé en {elapsed:.1f}s")

    return n_rows


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    logger = dwh_utils.setup_logging(run_id, log_name="load_dim_date")
    engine = dwh_utils.build_engine(logger)

    dwh_utils.create_dwh_schema(engine, logger)

    n = load_dim_date(run_id, engine, logger)

    df_check = build_dim_date()
    min_date = df_check["date_complete"].min().date()
    max_date = df_check["date_complete"].max().date()

    logger.info("=" * 60)
    logger.info("dwh.dim_date chargée avec succès")
    logger.info(f"  lignes chargées : {n}")
    logger.info(f"  date minimale   : {min_date}")
    logger.info(f"  date maximale   : {max_date}")
    logger.info("=" * 60)
