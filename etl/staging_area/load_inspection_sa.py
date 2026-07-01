"""
etl/staging_area/load_inspection_sa.py
========================================
Lit FicheVoitureStafim.xlsx, applique les nettoyages définis,
charge staging.stg_inspection.

Nettoyages :
  1. Standardisation des noms de colonnes (insensible casse/accents)
  2. Immatriculation : TU/RS/NT + inversions + is_valid_for_join
  3. VIN
  4. Motorisation
  5. Kilométrage
  6. Noms agent et personne
  7. Numéro de commande de travaux
  8. Déduplication (immat + date + horodateur + numéro commande)

Usage autonome :
  python etl/staging_area/load_inspection_sa.py
"""
from __future__ import annotations

import logging
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sa_utils

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

SOURCE_FILE          = "FicheVoitureStafim.xlsx"
SCHEMA               = "staging"
TABLE_NAME           = "stg_inspection"
SEUIL_DOUBLON_HEURES = 3.0

STAFIM_PATH = sa_utils.BASE_DIR / "data" / "raw" / SOURCE_FILE

# Valeurs textuelles considérées comme absentes (comparées après upper())
_INVALID = frozenset({
    "", "0", "TEST", "NAN", "NONE", "NULL",
    "N/A", "NA", "#N/A", "NON", "NEANT", "NÉANT", "ND", "NR", "INCONNU",
})

# Civilités à supprimer du nom personne (insensible à la casse)
_CIVILITES = re.compile(
    r"^\s*(MR\.?|MME\.?|M\.?|MONSIEUR|MADAME|DR\.?|DOCTEUR)\s*",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# 1. Normalisation des noms de colonnes
# ---------------------------------------------------------------------------

# Correspondance source → nom technique.
# La comparaison est insensible à la casse, aux accents et à la ponctuation.
COLUMN_RENAME_MAP: dict[str, str] = {
    # Immatriculation
    "N° D'IMMATRICULATION":   "immatriculation",
    "IMMATRICULATION":        "immatriculation",
    # VIN
    "V.I.N":                  "vin",
    "VIN":                    "vin",
    # Kilométrage
    "KILOMETRAGE":            "kilometrage",
    "Kilométrage":            "kilometrage",
    "KM":                     "kilometrage",
    "Km":                     "kilometrage",
    # Motorisation
    "MOTORISATION":           "motorisation",
    # Numéro de commande
    "N° COMMANDE DE TRAVAUX": "numero_commande_travaux",
    # Agents / personnes
    "NOM DE L'AGENT":         "nom_agent_inspection",
    "NOM ET PRENOM":          "nom_personne_inspection",
    "NOM ET PRÉNOM":          "nom_personne_inspection",
    "TELEPHONE":              "telephone_personne_inspection",
    # Dates / temps
    "DATE":                   "date_inspection",
    "HEURE D'ENTREE":         "heure_entree",
    "HEURE D'ENTRÉE":         "heure_entree",
    "Heure d'entrée":         "heure_entree",
    "Horodateur":             "horodateur",
    "HORODATEUR":             "horodateur",
    # Score
    "Score":                  "score_etat_vehicule",
    "SCORE":                  "score_etat_vehicule",
    # Ordre
    "N° D'ORDRE":             "numero_ordre",
    "N°ORDRE":                "numero_ordre",
}


def _norm_key(s: str) -> str:
    """Normalise un nom de colonne : supprime accents, ponctuation, casse."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", s.lower())


_RENAME_LOOKUP: dict[str, str] = {_norm_key(k): v for k, v in COLUMN_RENAME_MAP.items()}


def _apply_rename(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip() for c in df.columns]
    rename_eff: dict[str, str] = {}
    seen_targets: set[str] = set()
    for col in df.columns:
        target = _RENAME_LOOKUP.get(_norm_key(col))
        if target and target not in seen_targets:
            rename_eff[col] = target
            seen_targets.add(target)
    return df.rename(columns=rename_eff), rename_eff


# ---------------------------------------------------------------------------
# 2. Immatriculation
# ---------------------------------------------------------------------------

def _standardise_immat(val: object) -> str | None:
    """
    Standardise une immatriculation tunisienne.

    Formats cibles :
      TU → xxxxTUyyy   ex. 1234TU567
      RS → RSxxxx      ex. RS1234
      NT → xxxxNT      ex. 1234NT

    Corrections inversions :
      xxxxRS → RSxxxx
      NTxxxx → xxxxNT

    Valeurs invalides (TEST, NAN, vide, 0, …) → None.
    """
    if not isinstance(val, str) or not val.strip():
        return None

    s = re.sub(r"\s+", "", val.strip().upper())

    if s in _INVALID:
        return None

    # Format TU : chiffres encadrant TU
    m = re.match(r"^(\d{1,4})TU(\d{1,4})$", s)
    if m:
        return f"{m.group(1)}TU{m.group(2)}"

    # Format RS correct
    if re.match(r"^RS\d+$", s):
        return s
    # Inversion RS : xxxxRS → RSxxxx
    m = re.match(r"^(\d+)RS$", s)
    if m:
        return f"RS{m.group(1)}"

    # Format NT correct
    if re.match(r"^\d+NT$", s):
        return s
    # Inversion NT : NTxxxx → xxxxNT
    m = re.match(r"^NT(\d+)$", s)
    if m:
        return f"{m.group(1)}NT"

    return None  # format non reconnu → invalide


# ---------------------------------------------------------------------------
# 3. VIN
# ---------------------------------------------------------------------------

def _clean_vin(val: object) -> str | None:
    if not isinstance(val, str) or not val.strip():
        return None
    s = re.sub(r"\s+", "", val.strip().upper())
    return None if s in _INVALID else s


# ---------------------------------------------------------------------------
# 4. Motorisation
# ---------------------------------------------------------------------------

def _clean_motorisation(val: object) -> str | None:
    if not isinstance(val, str) or not val.strip():
        return None
    s = re.sub(r"\s+", " ", val.strip().upper())
    return None if s in _INVALID else s


# ---------------------------------------------------------------------------
# 5. Kilométrage
# ---------------------------------------------------------------------------

_KM_ABERRANT_MIN = 100  # km < 100 → invalide


def _clean_km(series: pd.Series) -> pd.Series:
    def _parse(v) -> int | None:
        if pd.isna(v):
            return None
        digits = re.sub(r"[^\d]", "", str(v).strip())
        if not digits:
            return None
        n = int(digits)
        return None if n < _KM_ABERRANT_MIN else n
    return series.map(_parse)


# ---------------------------------------------------------------------------
# 6. Noms
# ---------------------------------------------------------------------------

def _clean_nom_agent(val: object) -> str | None:
    if not isinstance(val, str) or not val.strip():
        return None
    s = re.sub(r"\s+", " ", val.strip().upper())
    return None if s in _INVALID else s


def _clean_nom_personne(val: object) -> str | None:
    if not isinstance(val, str) or not val.strip():
        return None
    s = _CIVILITES.sub("", val.strip())
    s = re.sub(r"\s+", " ", s.upper()).strip()
    return None if s in _INVALID else s


# ---------------------------------------------------------------------------
# 7. Numéro de commande de travaux
# ---------------------------------------------------------------------------

def _clean_numero_commande(val: object) -> str | None:
    if not isinstance(val, str) or not val.strip():
        return None
    s = val.strip().upper()
    return None if s in _INVALID else s


# ---------------------------------------------------------------------------
# 8. Déduplication
# ---------------------------------------------------------------------------

def _deduplicate(df: pd.DataFrame, logger) -> tuple[pd.DataFrame, int]:
    """
    Déduplique les lignes représentant la même inspection.

    Règle de regroupement (union-find) :
      - Même immatriculation + même numéro de commande (non-null) → même inspection
      - Même immatriculation + même date_inspection
        + delta horodateur ≤ SEUIL_DOUBLON_HEURES → même inspection
      Dans chaque groupe → garder la ligne la plus complète (max champs renseignés).

    Lignes sans immatriculation : conservées telles quelles (is_valid_for_join = FALSE).
    Inspections distinctes (dates/heures éloignées, commandes différentes) : toutes conservées.
    """
    n_avant  = len(df)

    if "immatriculation" not in df.columns:
        logger.warning("  [DEDUP] Colonne 'immatriculation' absente — ignorée")
        return df, 0

    df_valid   = df[df["immatriculation"].notna()].copy()
    df_invalid = df[df["immatriculation"].isna()].copy()

    # Score de complétude (plus de champs non-vides = ligne plus complète)
    df_valid["_score"] = df_valid.replace("", pd.NA).notna().sum(axis=1)

    has_date = "date_inspection" in df_valid.columns
    has_hora = "horodateur" in df_valid.columns
    has_cmd  = "numero_commande_travaux" in df_valid.columns

    dup_immats = (
        df_valid[df_valid.duplicated(subset=["immatriculation"], keep=False)]
        ["immatriculation"].unique()
    )

    rows_to_drop: list[int] = []

    for immat in dup_immats:
        lignes = df_valid[df_valid["immatriculation"] == immat]
        n      = len(lignes)
        iloc_idx = list(lignes.index)  # vrais index DataFrame

        # Union-Find
        parent = list(range(n))

        def _find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def _union(x: int, y: int) -> None:
            px, py = _find(x), _find(y)
            if px != py:
                parent[px] = py

        for i in range(n):
            ri = lignes.iloc[i]
            for j in range(i + 1, n):
                rj = lignes.iloc[j]

                # Même numéro de commande non-null → duplicate
                if has_cmd:
                    ci = ri.get("numero_commande_travaux")
                    cj = rj.get("numero_commande_travaux")
                    if (pd.notna(ci) and pd.notna(cj)
                            and str(ci).strip() and str(cj).strip()
                            and str(ci).strip() == str(cj).strip()):
                        _union(i, j)
                        continue

                # Même date + delta horodateur ≤ seuil
                if has_date:
                    di = ri.get("date_inspection")
                    dj = rj.get("date_inspection")
                    if pd.notna(di) and pd.notna(dj) and di == dj:
                        if has_hora:
                            hi = ri.get("horodateur")
                            hj = rj.get("horodateur")
                            try:
                                delta = abs((hj - hi).total_seconds()) / 3600
                                if delta <= SEUIL_DOUBLON_HEURES:
                                    _union(i, j)
                            except Exception:
                                pass
                        else:
                            _union(i, j)

        # Construire les composantes connexes
        components: dict[int, list[int]] = defaultdict(list)
        for i in range(n):
            components[_find(i)].append(i)

        for members in components.values():
            if len(members) <= 1:
                continue
            scores   = [lignes.iloc[m]["_score"] for m in members]
            best     = max(range(len(members)), key=lambda k: scores[k])
            dropped  = [iloc_idx[m] for k, m in enumerate(members) if k != best]
            rows_to_drop.extend(dropped)
            logger.info(
                f"  [DEDUP] {immat} : groupe {len(members)} → "
                f"garder idx{iloc_idx[members[best]]}, drop {len(dropped)}"
            )

    df_valid = df_valid.drop(index=rows_to_drop).drop(columns=["_score"])
    n_suppr  = len(rows_to_drop)
    result   = pd.concat([df_valid, df_invalid], ignore_index=True)
    logger.info(f"  Déduplication : {n_suppr} supprimées / {n_avant} initiales")
    return result, n_suppr


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def load_inspection_sa(run_id: str, engine, logger: logging.Logger) -> int:
    """
    Lit FicheVoitureStafim.xlsx, applique les 8 nettoyages,
    charge staging.stg_inspection. Retourne le nombre de lignes chargées.
    """
    logger.info(f"[RUN {run_id}] {SOURCE_FILE}")

    if not STAFIM_PATH.exists():
        raise FileNotFoundError(f"Fichier source introuvable : {STAFIM_PATH}")

    df = pd.read_excel(STAFIM_PATH, dtype=str)
    n_raw = len(df)
    logger.info(f"  {n_raw} lignes lues / {df.shape[1]} colonnes")

    # ── 1. Standardisation noms de colonnes ───────────────────────────────
    logger.info("  [1] Standardisation colonnes")
    df, rename_eff = _apply_rename(df)
    logger.info(f"       {len(rename_eff)} colonne(s) renommée(s) : {list(rename_eff.values())}")

    # ── Parsing dates / horodateur (nécessaire pour la dédup) ─────────────
    if "horodateur" in df.columns:
        df["horodateur"] = pd.to_datetime(df["horodateur"], errors="coerce", dayfirst=True)
    if "date_inspection" in df.columns:
        df["date_inspection"] = pd.to_datetime(
            df["date_inspection"], errors="coerce", dayfirst=True
        ).dt.date

    # ── 2. Immatriculation ────────────────────────────────────────────────
    logger.info("  [2] Nettoyage immatriculation")
    if "immatriculation" in df.columns:
        df["immatriculation"] = df["immatriculation"].map(_standardise_immat)
    df["is_valid_for_join"] = df.get("immatriculation", pd.Series(dtype=object)).notna()

    # ── 3. VIN ────────────────────────────────────────────────────────────
    if "vin" in df.columns:
        df["vin"] = df["vin"].map(_clean_vin)

    # ── 4. Motorisation ───────────────────────────────────────────────────
    if "motorisation" in df.columns:
        df["motorisation"] = df["motorisation"].map(_clean_motorisation)

    # ── 5. Kilométrage ────────────────────────────────────────────────────
    logger.info("  [5] Nettoyage kilométrage")
    if "kilometrage" in df.columns:
        df["kilometrage"] = _clean_km(df["kilometrage"])

    # ── 6. Noms ───────────────────────────────────────────────────────────
    if "nom_agent_inspection" in df.columns:
        df["nom_agent_inspection"] = df["nom_agent_inspection"].map(_clean_nom_agent)
    if "nom_personne_inspection" in df.columns:
        df["nom_personne_inspection"] = df["nom_personne_inspection"].map(_clean_nom_personne)

    # ── 7. Numéro de commande ─────────────────────────────────────────────
    if "numero_commande_travaux" in df.columns:
        df["numero_commande_travaux"] = df["numero_commande_travaux"].map(_clean_numero_commande)

    # ── 8. Déduplication ─────────────────────────────────────────────────
    logger.info("  [8] Déduplication")
    df, n_suppr = _deduplicate(df, logger)

    # ── Chargement PostgreSQL ─────────────────────────────────────────────
    n_rows, elapsed = sa_utils.write_to_postgres(
        df, engine, SCHEMA, TABLE_NAME, logger
    )

    sa_utils.write_audit_row(
        engine, run_id,
        table_name=f"{SCHEMA}.{TABLE_NAME}",
        source_file=SOURCE_FILE,
        n_rows=n_rows,
        n_cols=df.shape[1],
        elapsed=elapsed,
        status="SUCCESS",
        logger=logger,
    )

    n_valid = int(df["is_valid_for_join"].sum()) if "is_valid_for_join" in df.columns else 0
    logger.info(f"  lignes source lues     : {n_raw}")
    logger.info(f"  doublons supprimés     : {n_suppr}")
    logger.info(f"  lignes chargées        : {n_rows}")
    logger.info(f"  immat valides          : {n_valid}")
    logger.info(f"  immat manquantes       : {n_rows - n_valid}")
    return n_rows


if __name__ == "__main__":
    from datetime import datetime
    _run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    _logger = sa_utils.setup_logging(_run_id, log_name="load_inspection_sa")
    _engine = sa_utils.build_engine(_logger)
    sa_utils.create_schemas(_engine, _logger)
    _n = load_inspection_sa(_run_id, _engine, _logger)
    _logger.info(f"Terminé : {_n} lignes -> {SCHEMA}.{TABLE_NAME}")
