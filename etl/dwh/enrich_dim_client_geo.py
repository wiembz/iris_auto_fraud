"""
etl/dwh/enrich_dim_client_geo.py
=================================
DeuxiÃ¨me passe de correction gÃ©ographique sur dwh.dim_client.

Corrige UNIQUEMENT les lignes oÃ¹ gouvernor / pays / localite = 'UNKNOWN'
en appliquant un rÃ©fÃ©rentiel gÃ©ographique tunisien avec score de confiance.

Niveaux de confiance
--------------------
  HIGH     : (cpost_norm, cite_norm) match exact dans le rÃ©fÃ©rentiel
             OU cpost_norm fiable + localitÃ© du rÃ©fÃ©rentiel trouvÃ©e dans adr1_norm
  MEDIUM   : cite_norm seule (gouvernor unique dans le rÃ©fÃ©rentiel)
             OU cpost_norm seul  (gouvernor unique dans le rÃ©fÃ©rentiel)
  LOW      : mot-clÃ© dans adr1 â€” jamais appliquÃ© automatiquement
  NO_MATCH : aucune correspondance fiable

Application automatique
-----------------------
  HIGH   : toujours appliquÃ©
  MEDIUM : appliquÃ© si APPLY_MEDIUM = True (dÃ©faut : False)
  LOW    : jamais appliquÃ© automatiquement
  Cas ambigus : conservÃ©s UNKNOWN

Cette correction est basÃ©e sur un rÃ©fÃ©rentiel interne avec score de confiance.
Elle ne force PAS les cas ambigus vers TUNISIE.

Usage
-----
  python etl/dwh/enrich_dim_client_geo.py
  python etl/dwh/enrich_dim_client_geo.py --apply-medium
"""
from __future__ import annotations

import argparse
import math
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwh_utils

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Configuration
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

APPLY_MEDIUM = False      # Surcharger via --apply-medium en CLI

TABLE_NAME = "dim_client"
SCHEMA     = "dwh"

_HERE        = Path(__file__).resolve().parent.parent.parent  # racine projet
REF_CSV_PATH = _HERE / "data" / "reference" / "dim_client" / "geo_client_reference.csv"
REPORT_DIR   = _HERE / "data" / "quality_reports" / "dim_client"

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# RÃ©fÃ©rentiel interne minimal
#
# IMPORTANT : Ces entrÃ©es ont Ã©tÃ© dÃ©finies sur la base des exemples DQ rÃ©els.
#             Les lignes marquÃ©es "# Ã  valider" doivent Ãªtre confirmÃ©es par
#             l'Ã©quipe mÃ©tier ou le rÃ©fÃ©rentiel officiel des codes postaux PTT.
#             Pour enrichir : crÃ©er data/reference/dim_client/geo_client_reference.csv
#             avec les colonnes : cpost, cite_norm, localite_norm, gouvernor, pays
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_INTERNAL_REF: list[dict] = [
    # â”€â”€ Tunis â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    {"cpost": "2089", "cite_norm": "EL KRAM",         "localite_norm": "EL KRAM",         "gouvernor": "TUNIS",    "pays": "TUNISIE"},
    {"cpost": "2089", "cite_norm": "LE KRAM",          "localite_norm": "EL KRAM",         "gouvernor": "TUNIS",    "pays": "TUNISIE"},
    {"cpost": "2089", "cite_norm": "KRAM",             "localite_norm": "EL KRAM",         "gouvernor": "TUNIS",    "pays": "TUNISIE"},
    {"cpost": "2089", "cite_norm": "EL KRAM OUEST",    "localite_norm": "EL KRAM",         "gouvernor": "TUNIS",    "pays": "TUNISIE"},
    # â”€â”€ Ariana â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    {"cpost": "2091", "cite_norm": "EL MENZAH 5",      "localite_norm": "EL MENZAH 5",     "gouvernor": "ARIANA",   "pays": "TUNISIE"},  # Ã  valider
    {"cpost": "2091", "cite_norm": "EL MENZAH 6",      "localite_norm": "EL MENZAH 6",     "gouvernor": "ARIANA",   "pays": "TUNISIE"},  # Ã  valider
    {"cpost": "2091", "cite_norm": "EL MENZAH",        "localite_norm": "EL MENZAH",       "gouvernor": "ARIANA",   "pays": "TUNISIE"},  # Ã  valider
    {"cpost": "2091", "cite_norm": "MANZEH 5",         "localite_norm": "EL MENZAH 5",     "gouvernor": "ARIANA",   "pays": "TUNISIE"},  # Ã  valider
    {"cpost": "2091", "cite_norm": "MANZEH 6",         "localite_norm": "EL MENZAH 6",     "gouvernor": "ARIANA",   "pays": "TUNISIE"},  # Ã  valider
    {"cpost": "2028", "cite_norm": "EL HIDHABE",       "localite_norm": "EL HIDHABE",      "gouvernor": "ARIANA",   "pays": "TUNISIE"},  # Ã  valider
    {"cpost": "2028", "cite_norm": "HIDHABE",          "localite_norm": "EL HIDHABE",      "gouvernor": "ARIANA",   "pays": "TUNISIE"},  # Ã  valider
    # â”€â”€ Manouba â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    {"cpost": "2021", "cite_norm": "OUED ELLIL",       "localite_norm": "OUED ELLIL",      "gouvernor": "MANOUBA",  "pays": "TUNISIE"},
    {"cpost": "2021", "cite_norm": "OUED ELLILI",      "localite_norm": "OUED ELLIL",      "gouvernor": "MANOUBA",  "pays": "TUNISIE"},
    {"cpost": "2021", "cite_norm": "OUED ELIL",        "localite_norm": "OUED ELLIL",      "gouvernor": "MANOUBA",  "pays": "TUNISIE"},
    {"cpost": "2021", "cite_norm": "ESSAIDA",          "localite_norm": "ESSAIDA",         "gouvernor": "MANOUBA",  "pays": "TUNISIE"},  # Ã  valider
    {"cpost": "2021", "cite_norm": "CITE ENNOUR",      "localite_norm": "CITE ENNOUR",     "gouvernor": "MANOUBA",  "pays": "TUNISIE"},  # Ã  valider
    # â”€â”€ Ben Arous â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    {"cpost": "2057", "cite_norm": "CITE LES PINS",    "localite_norm": "CITE LES PINS",   "gouvernor": "BEN AROUS","pays": "TUNISIE"},  # Ã  valider
    {"cpost": "2075", "cite_norm": "EL FAOUZ",         "localite_norm": "EL FAOUZ",        "gouvernor": "BEN AROUS","pays": "TUNISIE"},  # Ã  valider
    {"cpost": "2075", "cite_norm": "FAOUZ",            "localite_norm": "EL FAOUZ",        "gouvernor": "BEN AROUS","pays": "TUNISIE"},  # Ã  valider
    # â”€â”€ Enrichir ici ou via data/reference/dim_client/geo_client_reference.csv â”€â”€â”€â”€â”€â”€
]

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Valeurs texte invalides (comparÃ©es aprÃ¨s normalisation)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_INVALID_TEXT = frozenset({
    "", ".", "..", "-", "--", "/",
    "XXX", "UNKNOWN", "NON RENSEIGNE", "NON RENSEIGNÃ‰",
    "NAN", "NULL", "NONE", "NA", "N A", "N/A", "ND", "NR",
    "0", "00",
})

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Normalisation
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def normalize_text(raw) -> str | None:
    """
    Normalise un champ texte adresse/citÃ© pour le matching gÃ©ographique.

    Ã‰tapes :
      1. NFKD + suppression diacritiques
      2. Uppercase
      3. Apostrophes / tirets â†’ espace
      4. Supprime tout sauf lettres, chiffres, espaces
      5. Normalise espaces
      6. Filtre valeurs invalides
      7. Aliases sÃ©mantiques tunisiens (CTEâ†’CITE, MANZEHâ†’EL MENZAH, etc.)
    """
    if raw is None:
        return None
    if isinstance(raw, float) and math.isnan(raw):
        return None
    s = str(raw).strip()
    if not s:
        return None

    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.upper()
    s = re.sub(r"['''`\-]", " ", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()

    if not s or s in _INVALID_TEXT:
        return None

    # â”€â”€ Aliases sÃ©mantiques â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # AbrÃ©viations de voirie/citÃ©
    s = re.sub(r"\bCITEE\b", "CITE", s)
    s = re.sub(r"\bCTE\b",   "CITE", s)

    # EL MANZEH / EL MENZEH â†’ EL MENZAH (correction orthographique + maintien EL)
    s = re.sub(r"\bEL\s+MANZEH\b", "EL MENZAH", s)
    s = re.sub(r"\bEL\s+MENZEH\b", "EL MENZAH", s)

    # MANZEH / MENZEH seul (sans EL prÃ©cÃ©dent) â†’ EL MENZAH
    # NB : aprÃ¨s les remplacements ci-dessus, les MANZEH/MENZEH restants
    #      ne sont plus prÃ©cÃ©dÃ©s de EL.
    s = re.sub(r"\bMANZEH\b", "EL MENZAH", s)
    s = re.sub(r"\bMENZEH\b", "EL MENZAH", s)

    # OUED ELLILI / OUED ELILI â†’ OUED ELLIL
    s = re.sub(r"\bOUED\s+ELLILI\b", "OUED ELLIL", s)
    s = re.sub(r"\bOUED\s+ELILI\b",  "OUED ELLIL", s)

    # ELKRAM (collÃ©) â†’ EL KRAM
    s = re.sub(r"\bELKRAM\b", "EL KRAM", s)

    # Variants ENNASIM
    s = re.sub(r"\bENNASSIM\b", "ENNASIM", s)
    s = re.sub(r"\bENNACIM\b",  "ENNASIM", s)

    s = re.sub(r"\s+", " ", s).strip()
    return s if s and s not in _INVALID_TEXT else None


def normalize_cpost(raw) -> str | None:
    """
    Normalise un code postal tunisien.
    Extrait les chiffres, valide la plage tunisienne (700â€“9999).
    Retourne None pour les codes hors plage ou invalides.
    """
    if raw is None:
        return None
    if isinstance(raw, float):
        if math.isnan(raw):
            return None
        raw = str(int(raw))
    s = str(raw).strip().split(".")[0]
    digits = re.sub(r"[^0-9]", "", s)
    if not digits:
        return None
    try:
        cp = int(digits)
    except ValueError:
        return None
    if cp < 700 or cp > 9999:
        return None
    return str(cp).zfill(4)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Chargement du rÃ©fÃ©rentiel
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def load_reference(logger) -> pd.DataFrame:
    """
    Charge le rÃ©fÃ©rentiel gÃ©ographique.
    PrioritÃ© : CSV externe â†’ rÃ©fÃ©rentiel interne minimal.
    Applique normalize_text / normalize_cpost sur toutes les entrÃ©es.
    """
    if REF_CSV_PATH.exists():
        logger.info(f"  RÃ©fÃ©rentiel externe : {REF_CSV_PATH}")
        try:
            df_ref = pd.read_csv(REF_CSV_PATH, dtype=str)
            required = {"cpost", "cite_norm", "localite_norm", "gouvernor", "pays"}
            missing  = required - set(df_ref.columns)
            if missing:
                logger.warning(
                    f"  Colonnes manquantes dans le CSV ({missing}). "
                    "Repli sur rÃ©fÃ©rentiel interne."
                )
                df_ref = pd.DataFrame(_INTERNAL_REF)
            else:
                logger.info(f"  {len(df_ref)} entrÃ©es chargÃ©es (CSV externe)")
        except Exception as exc:
            logger.warning(f"  Erreur lecture CSV ({exc}). Repli sur rÃ©fÃ©rentiel interne.")
            df_ref = pd.DataFrame(_INTERNAL_REF)
    else:
        logger.info(
            f"  Aucun rÃ©fÃ©rentiel externe trouvÃ© ({REF_CSV_PATH}). "
            "RÃ©fÃ©rentiel interne minimal utilisÃ©."
        )
        df_ref = pd.DataFrame(_INTERNAL_REF)
        logger.info(f"  {len(df_ref)} entrÃ©es dans le rÃ©fÃ©rentiel interne")

    # Normalisation identique aux donnÃ©es client
    df_ref["cpost"]         = df_ref["cpost"].map(normalize_cpost)
    df_ref["cite_norm"]     = df_ref["cite_norm"].map(normalize_text)
    df_ref["localite_norm"] = df_ref["localite_norm"].map(normalize_text)
    df_ref["gouvernor"]     = df_ref["gouvernor"].astype(str).str.strip().str.upper()
    df_ref["pays"]          = df_ref["pays"].astype(str).str.strip().str.upper()

    df_ref = df_ref.dropna(subset=["cpost", "gouvernor", "pays"])
    df_ref = df_ref[df_ref["gouvernor"].str.len() > 0].copy()

    logger.info(f"  RÃ©fÃ©rentiel final aprÃ¨s normalisation : {len(df_ref)} entrÃ©es valides")
    return df_ref


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Construction des lookups
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def build_lookups(df_ref: pd.DataFrame) -> dict:
    """
    Construit les structures de recherche depuis le rÃ©fÃ©rentiel normalisÃ©.

    pair_lookup  : {(cpost, cite_norm)} â†’ (gouvernor, pays, localite_norm)
    cite_govs    : {cite_norm}          â†’ set(gouvernors)  â€” unicitÃ© MEDIUM
    cpost_govs   : {cpost}              â†’ set(gouvernors)  â€” unicitÃ© MEDIUM
    cpost_locs   : {cpost}              â†’ {localite_norm: (gouvernor, pays, localite_norm)}
                                                            â€” HIGH via adr1
    """
    pair_lookup: dict[tuple[str, str], tuple] = {}
    cite_govs:   dict[str, set[str]]          = {}
    cpost_govs:  dict[str, set[str]]          = {}
    cpost_locs:  dict[str, dict[str, tuple]]  = {}

    for _, row in df_ref.iterrows():
        cpost     = row["cpost"]
        cite_n    = row["cite_norm"]
        loc_n     = row["localite_norm"]
        gouvernor = row["gouvernor"]
        pays      = row["pays"]

        if not isinstance(cpost, str) or not cpost:
            continue

        canonical_loc = loc_n if (isinstance(loc_n, str) and loc_n) else cite_n

        # Pair lookup
        if isinstance(cite_n, str) and cite_n:
            key = (cpost, cite_n)
            if key not in pair_lookup:
                pair_lookup[key] = (gouvernor, pays, canonical_loc or cite_n)

        # Gouvernors par cite (MEDIUM uniqueness check)
        if isinstance(cite_n, str) and cite_n:
            cite_govs.setdefault(cite_n, set()).add(gouvernor)

        # Gouvernors par cpost (MEDIUM uniqueness check)
        cpost_govs.setdefault(cpost, set()).add(gouvernor)

        # LocalitÃ©s par cpost pour adr1 substring search (HIGH 2)
        # Seuil minimal de 5 chars pour Ã©viter les faux positifs
        loc_key = canonical_loc
        if isinstance(loc_key, str) and len(loc_key) >= 5:
            cpost_locs.setdefault(cpost, {})[loc_key] = (gouvernor, pays, loc_key)

    return {
        "pair_lookup":  pair_lookup,
        "cite_govs":    cite_govs,
        "cpost_govs":   cpost_govs,
        "cpost_locs":   cpost_locs,
    }


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Matching gÃ©ographique
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def match_geography(
    adr1_norm:  str | None,
    cpost_norm: str | None,
    cite_norm:  str | None,
    lookups:    dict,
) -> tuple[str, str | None, str | None, str | None, str, str]:
    """
    Recherche la gÃ©ographie d'une ligne client UNKNOWN.

    Ordre de prioritÃ© :
      HIGH 1  : (cpost, cite) exact dans pair_lookup
      HIGH 2  : cpost + localite du rÃ©fÃ©rentiel trouvÃ©e dans adr1_norm
      MEDIUM 3: cite seule â€” gouvernor unique dans cite_govs
      MEDIUM 4: cpost seul â€” gouvernor unique dans cpost_govs
      NO_MATCH: aucune correspondance fiable

    Retourne : (confidence, gouvernor, pays, localite, rule, matched_key)
    """
    pair_lookup = lookups["pair_lookup"]
    cite_govs   = lookups["cite_govs"]
    cpost_govs  = lookups["cpost_govs"]
    cpost_locs  = lookups["cpost_locs"]

    # â”€â”€ HIGH 1 : match exact (cpost, cite) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if cpost_norm and cite_norm:
        key = (cpost_norm, cite_norm)
        if key in pair_lookup:
            gov, pays, loc = pair_lookup[key]
            return (
                "HIGH", gov, pays, loc,
                "HIGH_PAIR",
                f"cpost={cpost_norm}|cite={cite_norm}",
            )

    # â”€â”€ HIGH 2 : cpost + localitÃ© du rÃ©fÃ©rentiel dans adr1 â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if cpost_norm and adr1_norm and cpost_norm in cpost_locs:
        for loc_key, (gov, pays, loc) in cpost_locs[cpost_norm].items():
            if loc_key in adr1_norm:
                return (
                    "HIGH", gov, pays, loc,
                    "HIGH_CPOST_ADR1",
                    f"cpost={cpost_norm}|adr1_contains={loc_key}",
                )

    # â”€â”€ MEDIUM 3 : cite seule (gouvernor unique dans le rÃ©fÃ©rentiel) â”€â”€â”€â”€â”€â”€
    if cite_norm and cite_norm in cite_govs:
        govs = cite_govs[cite_norm]
        if len(govs) == 1:
            gov  = next(iter(govs))
            return (
                "MEDIUM", gov, "TUNISIE", cite_norm,
                "MEDIUM_CITE_UNIQUE",
                f"cite={cite_norm}",
            )

    # â”€â”€ MEDIUM 4 : cpost seul (gouvernor unique dans le rÃ©fÃ©rentiel) â”€â”€â”€â”€â”€â”€
    if cpost_norm and cpost_norm in cpost_govs:
        govs = cpost_govs[cpost_norm]
        if len(govs) == 1:
            gov = next(iter(govs))
            loc = cite_norm if cite_norm else "UNKNOWN"
            return (
                "MEDIUM", gov, "TUNISIE", loc,
                "MEDIUM_CPOST_UNIQUE",
                f"cpost={cpost_norm}",
            )

    return "NO_MATCH", None, None, None, "NO_MATCH", ""


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Application des mises Ã  jour SQL
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _apply_updates(df_to_apply: pd.DataFrame, engine, logger) -> None:
    """
    Met Ã  jour dwh.dim_client uniquement pour les corrections sÃ©lectionnÃ©es.
    Ne modifie QUE gouvernor, pays, localite.
    Garde une condition de sÃ©curitÃ© : la ligne doit encore Ãªtre UNKNOWN.
    """
    sql_upd = text("""
        UPDATE dwh.dim_client
        SET    gouvernor = :new_gouvernor,
               pays      = :new_pays,
               localite  = :new_localite
        WHERE  client_sk = :client_sk
          AND  (gouvernor = 'UNKNOWN' OR pays = 'UNKNOWN' OR localite = 'UNKNOWN')
    """)

    rows        = df_to_apply[
        ["client_sk", "new_gouvernor", "new_pays", "new_localite"]
    ].to_dict("records")
    chunk_size  = 500
    total       = 0

    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]
        with engine.begin() as conn:
            for row in chunk:
                conn.execute(sql_upd, {
                    "new_gouvernor": row["new_gouvernor"],
                    "new_pays":      row["new_pays"],
                    "new_localite":  row["new_localite"],
                    "client_sk":     int(row["client_sk"]),
                })
        total += len(chunk)
        logger.info(f"    Mis Ã  jour : {total}/{len(rows)}")

    logger.info(f"  Total corrections appliquÃ©es dans dwh.{TABLE_NAME} : {len(rows)}")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# RequÃªtes de validation
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _print_validation_queries(logger) -> None:
    """Affiche dans les logs les requÃªtes SQL de validation post-exÃ©cution."""
    sep = "=" * 70
    logger.info(sep)
    logger.info("  REQUÃŠTES SQL DE VALIDATION POST-ENRICHISSEMENT")
    logger.info(sep)

    logger.info("""
-- 1. Volume UNKNOWN avant/aprÃ¨s
SELECT
    COUNT(*) FILTER (WHERE gouvernor = 'UNKNOWN') AS n_gov_unknown,
    COUNT(*) FILTER (WHERE pays      = 'UNKNOWN') AS n_pays_unknown,
    COUNT(*) FILTER (WHERE localite  = 'UNKNOWN') AS n_loc_unknown,
    COUNT(*)                                       AS n_total
FROM dwh.dim_client;
""")

    logger.info("""
-- 2. Distribution par pays
SELECT pays, COUNT(*) AS nb
FROM dwh.dim_client
GROUP BY pays
ORDER BY nb DESC;
""")

    logger.info("""
-- 3. Distribution par gouvernorat (clients tunisiens)
SELECT gouvernor, COUNT(*) AS nb
FROM dwh.dim_client
WHERE pays = 'TUNISIE'
GROUP BY gouvernor
ORDER BY nb DESC;
""")

    logger.info("""
-- 4. Top 50 couples cpost + cite encore UNKNOWN
SELECT cpost, cite, COUNT(*) AS nb
FROM dwh.dim_client
WHERE gouvernor = 'UNKNOWN'
GROUP BY cpost, cite
ORDER BY nb DESC
LIMIT 50;
""")

    logger.info("""
-- 5. Exemples de corrections HIGH appliquÃ©es (depuis le rapport CSV)
-- Filtrer le fichier data/quality_reports/dim_client/dim_client_geo_enrichment_report_<run_id>.csv
-- sur geo_confidence = 'HIGH'
""")

    logger.info("""
-- 6. ContrÃ´le : seules les lignes anciennement UNKNOWN ont Ã©tÃ© modifiÃ©es
-- Comparer : UNKNOWN avant (log run) vs UNKNOWN aprÃ¨s (requÃªte 1)
-- La diffÃ©rence doit Ã©galer n_high (+ n_medium si APPLY_MEDIUM=True)
""")

    logger.info("""
-- 7. ContrÃ´le structure dim_client (non modifiÃ©e par ce script)
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'dwh'
  AND table_name   = 'dim_client'
ORDER BY ordinal_position;
""")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Fonction principale
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def enrich_dim_client_geo(
    run_id:       str,
    engine,
    logger,
    apply_medium: bool = APPLY_MEDIUM,
) -> dict:
    """
    Orchestre la deuxiÃ¨me passe de correction gÃ©ographique sur dwh.dim_client.

    1. Charge le rÃ©fÃ©rentiel (CSV externe ou interne)
    2. Lit les lignes UNKNOWN depuis dwh.dim_client
    3. Normalise adr1, cpost, cite
    4. Applique le matching avec score de confiance
    5. Met Ã  jour la base pour HIGH (et MEDIUM si demandÃ©)
    6. GÃ©nÃ¨re le rapport CSV qualitÃ©
    7. Affiche les requÃªtes de validation
    """
    sep = "=" * 70
    logger.info(sep)
    logger.info(f"[GEO-ENRICH] dwh.{TABLE_NAME}  â€”  run_id={run_id}")
    logger.info("  Correction gÃ©ographique qualitÃ© â€” rÃ©fÃ©rentiel avec score de confiance")
    logger.info("  Les cas ambigus restent UNKNOWN. Aucun forÃ§age vers TUNISIE.")
    logger.info(f"  APPLY_MEDIUM = {apply_medium}")
    logger.info(sep)

    # 1. RÃ©fÃ©rentiel et lookups
    df_ref  = load_reference(logger)
    lookups = build_lookups(df_ref)
    logger.info(
        f"  Lookups : "
        f"{len(lookups['pair_lookup'])} paires (cpost,cite), "
        f"{len(lookups['cpost_locs'])} codes postaux avec localitÃ©s, "
        f"{len(lookups['cite_govs'])} citÃ©s distinctes"
    )

    # 2. Lecture des lignes UNKNOWN
    sql_read = text("""
        SELECT client_sk, idclt, adr1, cpost, cite,
               gouvernor, pays, localite
        FROM   dwh.dim_client
        WHERE  gouvernor = 'UNKNOWN'
           OR  pays      = 'UNKNOWN'
           OR  localite  = 'UNKNOWN'
        ORDER  BY client_sk
    """)
    with engine.connect() as conn:
        df_unk = pd.read_sql(sql_read, conn)

    n_total_unknown = len(df_unk)
    logger.info(f"  Lignes UNKNOWN lues depuis dwh.{TABLE_NAME} : {n_total_unknown}")

    if df_unk.empty:
        logger.info("  Aucune ligne UNKNOWN â€” enrichissement non nÃ©cessaire.")
        _print_validation_queries(logger)
        return {
            "n_total_unknown": 0,
            "n_high": 0, "n_medium": 0, "n_low": 0,
            "n_no_match": 0, "n_applied": 0,
        }

    # 3. Normalisation
    df_unk["_adr1_norm"]  = df_unk["adr1"].map(normalize_text)
    df_unk["_cpost_norm"] = df_unk["cpost"].map(normalize_cpost)
    df_unk["_cite_norm"]  = df_unk["cite"].map(normalize_text)

    # 4. Matching
    records = []
    for _, row in df_unk.iterrows():
        conf, gov, pays, loc, rule, matched_key = match_geography(
            row["_adr1_norm"],
            row["_cpost_norm"],
            row["_cite_norm"],
            lookups,
        )
        records.append({
            "client_sk":      row["client_sk"],
            "idclt":          row["idclt"],
            "adr1":           row["adr1"],
            "cpost":          row["cpost"],
            "cite":           row["cite"],
            "old_gouvernor":  row["gouvernor"],
            "old_pays":       row["pays"],
            "old_localite":   row["localite"],
            "new_gouvernor":  gov  if gov  is not None else row["gouvernor"],
            "new_pays":       pays if pays is not None else row["pays"],
            "new_localite":   loc  if loc  is not None else row["localite"],
            "geo_confidence": conf,
            "geo_rule":       rule,
            "matched_key":    matched_key,
        })

    df_results = pd.DataFrame(records)

    # 5. Comptages
    mask_high     = df_results["geo_confidence"] == "HIGH"
    mask_medium   = df_results["geo_confidence"] == "MEDIUM"
    mask_low      = df_results["geo_confidence"] == "LOW"
    mask_no_match = df_results["geo_confidence"] == "NO_MATCH"

    n_high    = int(mask_high.sum())
    n_medium  = int(mask_medium.sum())
    n_low     = int(mask_low.sum())
    n_no_match= int(mask_no_match.sum())

    logger.info(f"  RÃ©sultats matching :")
    logger.info(f"    HIGH     : {n_high}")
    logger.info(f"    MEDIUM   : {n_medium}  (appliquÃ© : {apply_medium})")
    logger.info(f"    LOW      : {n_low}  (jamais appliquÃ© automatiquement)")
    logger.info(f"    NO_MATCH : {n_no_match}")

    # 6. Application des corrections
    df_to_apply = df_results[mask_high].copy()
    if apply_medium:
        df_to_apply = pd.concat(
            [df_to_apply, df_results[mask_medium]], ignore_index=True
        )

    n_applied       = len(df_to_apply)
    n_unknown_after = n_total_unknown - n_applied

    if n_applied > 0:
        logger.info(f"  Application de {n_applied} corrections en base...")
        _apply_updates(df_to_apply, engine, logger)
    else:
        logger.info("  Aucune correction Ã  appliquer (rÃ©fÃ©rentiel trop petit).")
        logger.info("  â†’ Enrichissez data/reference/dim_client/geo_client_reference.csv")

    # 7. Rapport CSV qualitÃ©
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_cols = [
        "client_sk", "idclt", "adr1", "cpost", "cite",
        "old_gouvernor", "old_pays", "old_localite",
        "new_gouvernor", "new_pays", "new_localite",
        "geo_confidence", "geo_rule", "matched_key",
    ]
    report_path = REPORT_DIR / f"dim_client_geo_enrichment_report_{run_id}.csv"
    df_results[report_cols].to_csv(report_path, index=False, encoding="utf-8-sig")
    logger.info(f"  Rapport qualitÃ© : {report_path}")

    # 8. RÃ©sumÃ© final
    logger.info(sep)
    logger.info("  RÃ‰SUMÃ‰ â€” ENRICHISSEMENT GÃ‰OGRAPHIQUE DIM_CLIENT")
    logger.info(sep)
    logger.info(f"  UNKNOWN avant enrichissement    : {n_total_unknown}")
    logger.info(f"  Corrections HIGH appliquÃ©es     : {n_high}")
    if apply_medium:
        logger.info(f"  Corrections MEDIUM appliquÃ©es   : {n_medium}")
    else:
        logger.info(
            f"  Corrections MEDIUM disponibles  : {n_medium}"
            "  (non appliquÃ©es â€” relancer avec --apply-medium)"
        )
    logger.info(f"  Cas LOW non appliquÃ©s           : {n_low}")
    logger.info(f"  Cas sans correspondance         : {n_no_match}")
    logger.info(f"  UNKNOWN aprÃ¨s enrichissement    : {n_unknown_after}")
    logger.info(f"  Rapport CSV                     : {report_path}")
    logger.info(sep)

    # 9. RequÃªtes de validation
    _print_validation_queries(logger)

    return {
        "n_total_unknown":  n_total_unknown,
        "n_high":           n_high,
        "n_medium":         n_medium,
        "n_low":            n_low,
        "n_no_match":       n_no_match,
        "n_applied":        n_applied,
        "n_unknown_after":  n_unknown_after,
        "report_path":      str(report_path),
    }


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Point d'entrÃ©e
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "DeuxiÃ¨me passe de correction gÃ©ographique sur dwh.dim_client. "
            "Corrige uniquement les lignes UNKNOWN avec un score de confiance."
        )
    )
    parser.add_argument(
        "--apply-medium",
        action="store_true",
        default=False,
        help="Appliquer aussi les corrections de confiance MEDIUM (dÃ©faut : False)",
    )
    args = parser.parse_args()

    _run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    _logger = dwh_utils.setup_logging(_run_id, log_name="enrich_dim_client_geo")
    _engine = dwh_utils.build_engine(_logger)

    enrich_dim_client_geo(
        run_id       = _run_id,
        engine       = _engine,
        logger       = _logger,
        apply_medium = args.apply_medium,
    )

