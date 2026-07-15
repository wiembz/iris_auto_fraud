
"""
etl/staging_area/prepare_inspection_sa.py
==========================================
Lit FicheVoitureStafim.xlsx brut et charge staging.stg_inspection.

Remplace l'ancien clean_fiche.py + load_inspection_sa.py.
Réutilise sa_utils pour la connexion PostgreSQL et l'audit.

Flux DWH aval :
  staging.stg_inspection -> dim_vehicule  (immatriculation, vin, motorisation)
                         -> fact_inspection_vehicule (kilométrage, anomalies, score…)

Nettoyages appliqués :
  1. Standardisation noms de colonnes (Excel → noms techniques)
  2. Standardisation immatriculation (TU / RS / NT + correction inversions)
  3. Nettoyage VIN
  4. Nettoyage motorisation
  5. Nettoyage kilométrage (extraction numérique + seuil 100 km)
  6. Nettoyage noms agent / personne (civilités, espaces)
  7. Nettoyage numéro commande (TEST → NULL)
  8. Déduplication (seuil SEUIL_DOUBLON_HEURES sur même immat + même date)
  9. Encodage 43 checkpoints → colonnes enc_* [0.0 / 0.5 / 1.0] (internes staging)
  10. Calcul nb_anomalies par section + total
  11. niveau_etat_vehicule (BON / MOYEN / MAUVAIS / CRITIQUE)
  12. indicateur_mauvais_etat (boolean)
  13. Nettoyage commentaires (apostrophes Unicode, espaces)

Usage :
  python etl/staging_area/prepare_inspection_sa.py
"""
from __future__ import annotations

import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sa_utils


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
SOURCE_FILE   = "FicheVoitureStafim.xlsx"
TABLE_NAME    = "stg_inspection"
SCHEMA        = "staging"
SOURCE_SYSTEM = "STAFIM"

BASE_DIR     = Path(__file__).resolve().parent.parent.parent
STAFIM_PATH  = BASE_DIR / "data" / "raw" / SOURCE_FILE

# Seuil doublon : deux inspections du même véhicule < 3h le même jour → doublon
SEUIL_DOUBLON_HEURES: float = 3.0

# Seuils niveau état véhicule (sur 43 checkpoints au total)
#   BON      : 0  anomalie
#   MOYEN    : 1–5  anomalies  (< 12 %)
#   MAUVAIS  : 6–13 anomalies  (14–30 %)
#   CRITIQUE : >= 14 anomalies (> 30 %)
# Ajuster après retour terrain selon la distribution observée.
SEUIL_MOYEN:    int = 1
SEUIL_MAUVAIS:  int = 6
SEUIL_CRITIQUE: int = 14


# ---------------------------------------------------------------------------
# Mapping colonnes Excel → noms techniques
# ---------------------------------------------------------------------------
COLUMN_RENAME_MAP: dict[str, str] = {
    "Horodateur":             "horodateur",
    "HEURE D'ENTREE":         "heure_entree",
    "DATE":                   "date_inspection",
    "N° COMMANDE DE TRAVAUX": "numero_commande_travaux",
    "NOM DE L'AGENT":         "nom_agent_inspection",
    "NOM ET PRENOM":          "nom_personne_inspection",
    "NOM ET PRENOM ":         "nom_personne_inspection",  # variante espace trailing
    "TELEPHONE":              "telephone_personne_inspection",
    "N° D'IMMATRICULATION":   "immatriculation",
    "V.I.N":                  "vin",
    "KILOMETRAGE":            "kilometrage_raw",
    "MOTORISATION":           "motorisation",
    " [MOTORISATION]":        "motorisation",             # variante ancien script
    "Score":                  "score_etat_vehicule",
    "Commentaire":            "commentaire_tour_vehicule",
    "Commentaire.1":          "commentaire_interieur",
    "Commentaire.2":          "commentaire_sous_capot",
    "Commentaire.3":          "commentaire_sous_vehicule",
    "Commentaire.4":          "commentaire_entretien",
}

def _norm_source_column_name(name: object) -> str:
    """Normalize Excel headers for robust source-to-staging mapping."""
    text = unicodedata.normalize("NFKD", str(name).strip())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", text.lower())


_RENAME_LOOKUP: dict[str, str] = {
    _norm_source_column_name(source): target
    for source, target in COLUMN_RENAME_MAP.items()
}


def _build_rename_map(columns: pd.Index) -> dict[str, str]:
    """Build a robust rename map while keeping the first source per target."""
    rename_eff: dict[str, str] = {}
    seen_targets: set[str] = set()
    for col in columns:
        target = _RENAME_LOOKUP.get(_norm_source_column_name(col))
        if target and target not in seen_targets:
            rename_eff[col] = target
            seen_targets.add(target)
    return rename_eff


# ---------------------------------------------------------------------------
# Colonnes checkpoint par section (noms UTF-8 exacts du fichier Excel)
# ---------------------------------------------------------------------------
TOUR_VEHICULE_COLS: list[str] = [
    "TOUR DU VEHICULE [Plaques de police]",
    "TOUR DU VEHICULE [Vitres et pare brise]",
    "TOUR DU VEHICULE [Balais essuie-glace]",
    "TOUR DU VEHICULE [Eclairage avant]",
    "TOUR DU VEHICULE [Eclairage arrière]",
    "TOUR DU VEHICULE [Rétroviseur Droit]",
    "TOUR DU VEHICULE [Rétroviseur Gauche]",
    "TOUR DU VEHICULE [Pneus avant]",
    "TOUR DU VEHICULE [Pneus arrière]",
]

DANS_VEHICULE_COLS: list[str] = [
    "DANS LE VEHICULE [Contrôle état balais essuie-vitres AV]",
    "DANS LE VEHICULE [Contrôle état balais essuie-vitres AR]",
    "DANS LE VEHICULE [Contrôle lève-vitre AV]",
    "DANS LE VEHICULE [Contrôle lève-vitre AR]",
    "DANS LE VEHICULE [Contrôle feux éclairages AV]",
    "DANS LE VEHICULE [Contrôle feux éclairages AR]",
    "DANS LE VEHICULE [Contrôle feux de signalisation AV]",
    "DANS LE VEHICULE [Contrôle feux de signalisation AR]",
    "DANS LE VEHICULE [Contrôle avertisseur sonore]",
]

SOUS_CAPOT_COLS: list[str] = [
    "SOUS LE CAPOT [Contrôle batterie]",
    "SOUS LE CAPOT [Contrôle niveau huile moteur]",
    "SOUS LE CAPOT [Contrôle niveau liquide refroidissement]",
    "SOUS LE CAPOT [Contrôle niveau liquide de frein]",
    "SOUS LE CAPOT [Contrôle durits de radiateur]",
    "SOUS LE CAPOT [Contrôle état des courroies d'accessoires]",
]

SOUS_VEHICULE_COLS: list[str] = [
    "SOUS LE VEHICULE [Contrôle plaquettes freins AV]",
    "SOUS LE VEHICULE [Contrôle disques AV]",
    "SOUS LE VEHICULE [Contrôle étriers]",
    "SOUS LE VEHICULE [Contrôle plaquettes freins AR]",
    "SOUS LE VEHICULE [Contrôle disques AR]",
    "SOUS LE VEHICULE [Contrôle étanchéité amortisseurs AV]",
    "SOUS LE VEHICULE [Contrôle étanchéité amortisseurs AR]",
    "SOUS LE VEHICULE [Contrôle gaine transmissions/rotules/crémaillère]",
    "SOUS LE VEHICULE [Contrôle état pneumatiques AV et AR]",
    "SOUS LE VEHICULE [Contrôle roue de secours]",
    "SOUS LE VEHICULE [Contrôle étanchéité tous fluides]",
    "SOUS LE VEHICULE [Contrôle état sous caisse]",
    "SOUS LE VEHICULE [Contrôle ligne d'échappement]",
]

AUTRES_PRESTATIONS_COLS: list[str] = [
    "AUTRES PRESTATIONS [Opération d'entretien]",
    "AUTRES PRESTATIONS [Contrôle filtre à air]",
    "AUTRES PRESTATIONS [Contrôle filtre d'habitacle]",
    "AUTRES PRESTATIONS [Contrôle bougies d'allumage]",
    "AUTRES PRESTATIONS [Courroie de distribution]",
    "AUTRES PRESTATIONS [Fonctionnement climatisation]",
]

ALL_CHECKPOINT_COLS: list[str] = (
    TOUR_VEHICULE_COLS
    + DANS_VEHICULE_COLS
    + SOUS_CAPOT_COLS
    + SOUS_VEHICULE_COLS
    + AUTRES_PRESTATIONS_COLS
)
# Total : 9 + 9 + 6 + 13 + 6 = 43 checkpoints

# Encodage unifié : 1.0 = OK | 0.5 = à surveiller | 0.0 = défectueux
ENCODING_MAP: dict[str, float] = {
    "Bon":                                          1.0,
    "Contrôle OK":                                  1.0,
    "Proposition faite":                            0.5,
    "Intervention conseillée":                      0.5,
    "Réparation effectuée suite à l'accord client": 0.5,
    "Défectueux":                                   0.0,
    "Contrôle non OK":                              0.0,
}

# Colonnes images — exclues du staging analytique
COLS_IMAGES: list[str] = [f"image{i}" for i in range(1, 11)]

# ---------------------------------------------------------------------------
# Colonnes finales de staging.stg_inspection (hors checkpoints bruts)
# Les colonnes checkpoint brutes sont détectées dynamiquement dans
# transform_inspection à partir des en-têtes Excel réels, puis ajoutées
# à cette liste avant la sélection finale.
# ---------------------------------------------------------------------------
STAGING_COLS: list[str] = [
    "inspection_source_id",
    "horodateur",
    "date_inspection",
    "heure_entree",
    "numero_commande_travaux",
    "nom_agent_inspection",
    "nom_personne_inspection",
    "telephone_personne_inspection",
    "immatriculation",
    "vin",
    "kilometrage",
    "motorisation",
    "score_etat_vehicule",
    "niveau_etat_vehicule",
    "nb_anomalies_tour_vehicule",
    "nb_anomalies_interieur",
    "nb_anomalies_sous_capot",
    "nb_anomalies_sous_vehicule",
    "nb_anomalies_entretien",
    "nb_anomalies_total",
    "indicateur_mauvais_etat",
    "commentaire_tour_vehicule",
    "commentaire_interieur",
    "commentaire_sous_capot",
    "commentaire_sous_vehicule",
    "commentaire_entretien",
    "is_valid_for_join",
    "source_system",
    "created_at",
]


# ---------------------------------------------------------------------------
# Helpers génériques
# ---------------------------------------------------------------------------

def _clean_str(value, blank_vals: frozenset | None = None) -> str | None:
    """Nettoie un champ texte. Retourne None si vide/invalide."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    text = text.replace("’", "'").replace("‘", "'")
    text = " ".join(text.split())
    if not text:
        return None
    if blank_vals and text.upper() in blank_vals:
        return None
    return text


def _fix_apostrophes(series: pd.Series) -> pd.Series:
    """Remplace U+2019 → apostrophe standard dans une série de textes."""
    return (
        series.fillna("")
        .astype(str)
        .str.replace("’", "'", regex=False)
        .str.replace("‘", "'", regex=False)
        .replace("", pd.NA)
    )


# ---------------------------------------------------------------------------
# Nettoyage immatriculation
# ---------------------------------------------------------------------------

_INVALID_IMMAT: frozenset[str] = frozenset({"TEST", "NAN", "NONE", "NULL", "NA", "", "0"})


def _standardiser_une_immat(val) -> str | None:
    """
    Standardise une immatriculation tunisienne vers la forme canonique.

    Formats gérés :
      TU  ex : 1234TU567 (ou inversion 567TU1234 → corrigée)
      RS  ex : RS1234    (ou inversion 1234RS → corrigée)
      NT  ex : 1234NT    (ou inversion NT1234 → corrigée)
      7 chiffres seuls → heuristique TU (1234567 → 1234TU567)

    Valeurs invalides → None (TEST, NAN, NONE, NULL, vide, 0)
    """
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None

    val = str(val).upper().strip()

    # Suppression caractères non alphanumériques
    val = re.sub(r"[^\w]", "", val)

    if not val or val in _INVALID_IMMAT:
        return None

    # Remplacement variantes arabes
    val = re.sub(r"ن\s*ت", "NT", val)
    val = re.sub(r"تونس", "TU", val)

    # ── Format TU ──────────────────────────────────────────────────────────
    m = re.match(r"^(\d+)TU(\d+)$", val)
    if m:
        gauche, droite = m.group(1), m.group(2)
        # Correction inversion : ex 567TU1234 → 1234TU567
        if len(gauche) <= 3 and len(droite) >= 4:
            return f"{droite}TU{gauche}"
        return f"{gauche}TU{droite}"

    # ── Format RS ──────────────────────────────────────────────────────────
    m = re.match(r"^RS(\d+)$", val)
    if m:
        return f"RS{m.group(1)}"
    m = re.match(r"^(\d+)RS$", val)
    if m:
        return f"RS{m.group(1)}"

    # ── Format NT ──────────────────────────────────────────────────────────
    m = re.match(r"^(\d+)NT$", val)
    if m:
        return f"{m.group(1)}NT"
    m = re.match(r"^NT(\d+)$", val)
    if m:
        return f"{m.group(1)}NT"

    # ── 7 chiffres seuls → heuristique TU ─────────────────────────────────
    if re.match(r"^\d{7}$", val):
        return f"{val[:4]}TU{val[4:]}"

    # ── Autres formats numériques ──────────────────────────────────────────
    if re.match(r"^\d+$", val):
        return val

    # ── Format non reconnu : garder tel quel (ne pas éliminer) ────────────
    return val


def _clean_immatriculation(series: pd.Series) -> pd.Series:
    return series.map(_standardiser_une_immat)


# ---------------------------------------------------------------------------
# Nettoyage VIN
# ---------------------------------------------------------------------------

def _clean_vin(series: pd.Series) -> pd.Series:
    def _one(val) -> str | None:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        text = str(val).upper().strip().replace(" ", "")
        return text if text and text not in {"NAN", "NONE", "NULL", "0", "N/A"} else None
    return series.map(_one)


# ---------------------------------------------------------------------------
# Nettoyage motorisation
# ---------------------------------------------------------------------------

def _clean_motorisation(series: pd.Series) -> pd.Series:
    def _one(val) -> str | None:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        text = " ".join(str(val).upper().split())
        return text if text and text not in {"NAN", "NONE", "NULL"} else None
    return series.map(_one)


# ---------------------------------------------------------------------------
# Nettoyage kilométrage
# ---------------------------------------------------------------------------

def _clean_kilometrage(series: pd.Series) -> pd.Series:
    """Extrait les chiffres, convertit en entier. < 100 km → NULL (aberrant)."""
    km_str = series.astype(str).str.replace(r"[^0-9]", "", regex=True).replace("", pd.NA)
    km_num = pd.to_numeric(km_str, errors="coerce").astype("Int64")
    return km_num.where(km_num >= 100)   # seuil aberration


# ---------------------------------------------------------------------------
# Nettoyage noms
# ---------------------------------------------------------------------------

_CIVILITES_RE = re.compile(
    r"\b(M\.|MR\.|MME\.|MR\b|MME\b|M\b)\b",
    re.IGNORECASE,
)


def _clean_nom_agent(series: pd.Series) -> pd.Series:
    def _one(val) -> str | None:
        text = _clean_str(val)
        return " ".join(text.upper().split()) if text else None
    return series.map(_one)


def _clean_nom_personne(series: pd.Series) -> pd.Series:
    """Nettoie le nom + prénom et supprime les civilités (MR, MME, M.)."""
    def _one(val) -> str | None:
        text = _clean_str(val)
        if text is None:
            return None
        text = _CIVILITES_RE.sub("", text).strip()
        text = " ".join(text.upper().split())
        return text if text else None
    return series.map(_one)


# ---------------------------------------------------------------------------
# Nettoyage numéro commande
# ---------------------------------------------------------------------------

def _clean_numero_commande(series: pd.Series) -> pd.Series:
    def _one(val) -> str | None:
        text = _clean_str(val)
        if text is None:
            return None
        return None if text.upper() == "TEST" else text.upper()
    return series.map(_one)


# ---------------------------------------------------------------------------
# Nettoyage commentaires
# ---------------------------------------------------------------------------

def _clean_commentaire(series: pd.Series) -> pd.Series:
    return series.map(lambda v: _clean_str(v))


# ---------------------------------------------------------------------------
# Encodage checkpoints → colonnes enc_*
# ---------------------------------------------------------------------------

def _enc_col_name(col: str) -> str:
    """Génère un nom enc_* court depuis le nom de colonne checkpoint."""
    if col.startswith("TOUR"):
        prefix = "tv"
    elif col.startswith("DANS"):
        prefix = "dv"
    elif col.startswith("SOUS LE CAPOT"):
        prefix = "sc"
    elif col.startswith("SOUS LE VEHICULE"):
        prefix = "sv"
    elif col.startswith("AUTRES"):
        prefix = "ap"
    else:
        prefix = "xx"

    inner = re.search(r"\[(.+)\]", col)
    if inner:
        short = inner.group(1).lower()
        for src, dst in [("é","e"),("è","e"),("ê","e"),("à","a"),("â","a"),
                         ("ù","u"),("û","u"),("ô","o"),("î","i"),("ï","i")]:
            short = short.replace(src, dst)
        short = re.sub(r"[^a-z0-9]+", "_", short).strip("_")[:30]
    else:
        short = re.sub(r"[^a-z0-9]+", "_", col.lower())[:30]

    return f"enc_{prefix}_{short}"


def _encode_checkpoints(df: pd.DataFrame, logger) -> pd.DataFrame:
    """
    Encode les 43 checkpoints en colonnes enc_* [0.0, 0.5, 1.0].
    Les valeurs inconnues sont signalées et encodées à NaN.
    """
    enc_count = 0
    unknown_reported: set[str] = set()

    for col in ALL_CHECKPOINT_COLS:
        if col not in df.columns:
            continue
        # Vérification valeurs inconnues
        actual = set(df[col].dropna().unique())
        unknown = actual - set(ENCODING_MAP.keys())
        for v in unknown:
            if v not in unknown_reported:
                logger.warning(f"  [ENC] Valeur inconnue dans '{col}': '{v}'")
                unknown_reported.add(v)

        df[_enc_col_name(col)] = df[col].map(ENCODING_MAP)
        enc_count += 1

    logger.info(f"  {enc_count} checkpoints encodés → colonnes enc_*")
    return df


# ---------------------------------------------------------------------------
# Calcul anomalies + niveau état véhicule
# ---------------------------------------------------------------------------

def _count_section_anomalies(df: pd.DataFrame, cols_source: list[str]) -> pd.Series:
    """Compte les checkpoints < 1.0 (anomalies) pour une section donnée."""
    enc_names = [_enc_col_name(c) for c in cols_source if _enc_col_name(c) in df.columns]
    if not enc_names:
        return pd.Series(0, index=df.index, dtype="Int64")
    return (df[enc_names] < 1.0).sum(axis=1).astype("Int64")


def _compute_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcule :
      nb_anomalies_* par section
      nb_anomalies_total
      niveau_etat_vehicule  (BON / MOYEN / MAUVAIS / CRITIQUE)
      indicateur_mauvais_etat (bool)

    Seuils niveau_etat_vehicule (sur 43 checkpoints) :
      BON      : 0  anomalie
      MOYEN    : 1–5  anomalies  (SEUIL_MOYEN = 1)
      MAUVAIS  : 6–13 anomalies  (SEUIL_MAUVAIS = 6)
      CRITIQUE : >= 14 anomalies  (SEUIL_CRITIQUE = 14, ≈ 33%)
    """
    df["nb_anomalies_tour_vehicule"] = _count_section_anomalies(df, TOUR_VEHICULE_COLS)
    df["nb_anomalies_interieur"]     = _count_section_anomalies(df, DANS_VEHICULE_COLS)
    df["nb_anomalies_sous_capot"]    = _count_section_anomalies(df, SOUS_CAPOT_COLS)
    df["nb_anomalies_sous_vehicule"] = _count_section_anomalies(df, SOUS_VEHICULE_COLS)
    df["nb_anomalies_entretien"]     = _count_section_anomalies(df, AUTRES_PRESTATIONS_COLS)

    df["nb_anomalies_total"] = (
        df["nb_anomalies_tour_vehicule"].fillna(0)
        + df["nb_anomalies_interieur"].fillna(0)
        + df["nb_anomalies_sous_capot"].fillna(0)
        + df["nb_anomalies_sous_vehicule"].fillna(0)
        + df["nb_anomalies_entretien"].fillna(0)
    ).astype("Int64")

    def _niveau(n) -> str:
        if pd.isna(n):
            return "INCONNU"
        n = int(n)
        if n >= SEUIL_CRITIQUE:
            return "CRITIQUE"
        if n >= SEUIL_MAUVAIS:
            return "MAUVAIS"
        if n >= SEUIL_MOYEN:
            return "MOYEN"
        return "BON"

    df["niveau_etat_vehicule"]    = df["nb_anomalies_total"].map(_niveau)
    df["indicateur_mauvais_etat"] = df["nb_anomalies_total"] >= SEUIL_MAUVAIS

    return df


# ---------------------------------------------------------------------------
# Déduplication
# ---------------------------------------------------------------------------

def _deduplicate(df: pd.DataFrame, logger) -> tuple[pd.DataFrame, int]:
    """
    Déduplique les inspections du même véhicule par fenêtre temporelle.

    Règle :
      - Même immat + même date_inspection + delta horodateur <= SEUIL_DOUBLON_HEURES
        → doublon temporel : garder la ligne avec le plus d'anomalies (plus informative)
      - Même immat mais dates différentes ou delta > seuil → inspections historiques
        distinctes, toutes conservées.
      - Lignes sans immatriculation : conservées sans déduplication.

    Retourne (df_dédupliqué, n_lignes_supprimées).
    """
    n_avant = len(df)

    # Séparer lignes avec / sans immatriculation
    df_valid   = df[df["immatriculation"].notna()].copy()
    df_invalid = df[df["immatriculation"].isna()].copy()

    # Score provisoire pour déduplication (sur enc_* déjà calculées)
    enc_cols = [c for c in df_valid.columns if c.startswith("enc_")]
    df_valid["_score_anom"] = (df_valid[enc_cols] < 1.0).sum(axis=1) if enc_cols else 0

    dup_immats = (
        df_valid[df_valid.duplicated(subset=["immatriculation"], keep=False)]
        ["immatriculation"].unique()
    )

    rows_to_drop: list[int] = []

    for immat in dup_immats:
        lignes = df_valid[df_valid["immatriculation"] == immat].copy()
        lignes = lignes.sort_values(["date_inspection", "horodateur"])

        # Traitement par date : plusieurs inspections à des dates distinctes
        # = inspections historiques, toutes conservées.
        # Au sein d'une même date, groupement glouton par fenêtre temporelle.
        for _date, date_group in lignes.groupby("date_inspection", dropna=False):
            if len(date_group) <= 1:
                continue

            sorted_g = date_group.sort_values("horodateur")
            idx_list = list(sorted_g.index)
            h_list   = list(sorted_g["horodateur"])
            s_list   = list(sorted_g["_score_anom"])

            # Groupement glouton : chaque nouvelle fenêtre commence quand
            # le delta depuis le début de la fenêtre courante dépasse le seuil.
            windows: dict[int, list[int]] = {0: [0]}
            current_w    = 0
            window_start = h_list[0]

            for pos in range(1, len(idx_list)):
                try:
                    delta = abs((h_list[pos] - window_start).total_seconds()) / 3600
                except Exception:
                    delta = float("inf")

                if delta <= SEUIL_DOUBLON_HEURES:
                    windows[current_w].append(pos)
                else:
                    current_w += 1
                    window_start = h_list[pos]
                    windows[current_w] = [pos]

            # Pour chaque fenêtre avec > 1 ligne : garder la plus anomalique
            for positions in windows.values():
                if len(positions) <= 1:
                    continue
                best_pos = max(positions, key=lambda p: s_list[p])
                dropped  = [idx_list[p] for p in positions if p != best_pos]
                rows_to_drop.extend(dropped)
                logger.info(
                    f"  [DEDUP] {immat} date={_date} : "
                    f"{len(positions)} proches → garder idx{idx_list[best_pos]}, "
                    f"drop {len(dropped)} ligne(s)"
                )

    df_valid = df_valid.drop(index=rows_to_drop).drop(columns=["_score_anom"])
    n_suppr  = len(rows_to_drop)

    result = pd.concat([df_valid, df_invalid], ignore_index=True)
    logger.info(f"  Déduplication : {n_suppr} lignes supprimées / {n_avant} initiales")

    return result, n_suppr


# ---------------------------------------------------------------------------
# Transformation principale
# ---------------------------------------------------------------------------

def transform_inspection(
    df_raw: pd.DataFrame,
    logger,
) -> tuple[pd.DataFrame, dict]:
    """
    Applique l'ensemble du pipeline de nettoyage sur le DataFrame brut.
    Retourne (df_staging, metrics).
    """
    n_raw = len(df_raw)
    logger.info(f"  Lignes brutes : {n_raw}")

    df = df_raw.copy()

    # ── 1. Normalisation noms de colonnes ──────────────────────────────────
    logger.info("  [STEP 1] Renommage colonnes")
    df.columns = [c.strip() for c in df.columns]
    rename_eff = _build_rename_map(df.columns)
    df = df.rename(columns=rename_eff)

    # Supprimer colonnes images (non analytiques)
    df = df.drop(columns=[c for c in COLS_IMAGES if c in df.columns], errors="ignore")

    # ── 2. Nettoyage apostrophes dans checkpoints ──────────────────────────
    for col in ALL_CHECKPOINT_COLS:
        if col in df.columns:
            df[col] = _fix_apostrophes(df[col])

    # ── 3. Parsing dates / heures ──────────────────────────────────────────
    logger.info("  [STEP 3] Parsing dates")
    if "horodateur" in df.columns:
        df["horodateur"] = pd.to_datetime(df["horodateur"], errors="coerce", dayfirst=True)
    if "date_inspection" in df.columns:
        df["date_inspection"] = pd.to_datetime(
            df["date_inspection"], errors="coerce", dayfirst=True
        ).dt.date
    if "heure_entree" in df.columns:
        df["heure_entree"] = df["heure_entree"].astype(str).str.strip()

    # ── 4. Immatriculation ─────────────────────────────────────────────────
    logger.info("  [STEP 4] Standardisation immatriculation")
    if "immatriculation" in df.columns:
        df["immatriculation"] = _clean_immatriculation(df["immatriculation"])
    df["is_valid_for_join"] = df.get("immatriculation", pd.Series(dtype=object)).notna()

    # ── 5. VIN ─────────────────────────────────────────────────────────────
    if "vin" in df.columns:
        df["vin"] = _clean_vin(df["vin"])

    # ── 6. Motorisation ────────────────────────────────────────────────────
    if "motorisation" in df.columns:
        df["motorisation"] = _clean_motorisation(df["motorisation"])

    # ── 7. Kilométrage ─────────────────────────────────────────────────────
    logger.info("  [STEP 7] Nettoyage kilométrage")
    src_km = "kilometrage_raw" if "kilometrage_raw" in df.columns else "kilometrage"
    if src_km in df.columns:
        df["kilometrage"] = _clean_kilometrage(df[src_km])
    df = df.drop(columns=["kilometrage_raw"], errors="ignore")

    # ── 8. Noms ────────────────────────────────────────────────────────────
    if "nom_agent_inspection" in df.columns:
        df["nom_agent_inspection"] = _clean_nom_agent(df["nom_agent_inspection"])
    if "nom_personne_inspection" in df.columns:
        df["nom_personne_inspection"] = _clean_nom_personne(df["nom_personne_inspection"])
    if "telephone_personne_inspection" in df.columns:
        df["telephone_personne_inspection"] = df["telephone_personne_inspection"].map(_clean_str)

    # ── 9. Numéro commande ─────────────────────────────────────────────────
    if "numero_commande_travaux" in df.columns:
        df["numero_commande_travaux"] = _clean_numero_commande(df["numero_commande_travaux"])

    # ── 10. Score état (numérique) ─────────────────────────────────────────
    if "score_etat_vehicule" in df.columns:
        df["score_etat_vehicule"] = pd.to_numeric(df["score_etat_vehicule"], errors="coerce")

    # ── 11. Commentaires ───────────────────────────────────────────────────
    for col_com in [
        "commentaire_tour_vehicule", "commentaire_interieur",
        "commentaire_sous_capot", "commentaire_sous_vehicule",
        "commentaire_entretien",
    ]:
        if col_com in df.columns:
            df[col_com] = _clean_commentaire(df[col_com])

    # ── 12. Encodage checkpoints (avant dédup pour scorer) ─────────────────
    logger.info("  [STEP 12] Encodage checkpoints")
    df = _encode_checkpoints(df, logger)

    # ── 13. Déduplication ──────────────────────────────────────────────────
    logger.info("  [STEP 13] Déduplication")
    df, n_dupes_supprimes = _deduplicate(df, logger)

    # ── 14. Calcul anomalies + niveaux ─────────────────────────────────────
    logger.info("  [STEP 14] Calcul anomalies")
    df = _compute_anomalies(df)

    # ── 15. Valeurs brutes des checkpoints avec noms normalisés snake_case ──
    # Détection robuste : on normalise d'abord le nom de colonne Excel puis on
    # vérifie le préfixe normalisé.  Cette approche est insensible à la casse,
    # aux accents, aux types de crochets et aux espaces dans les en-têtes Excel,
    # ce qui évite de rater SOUS_VEHICULE si l'en-tête utilise
    # «Sous le Vehicule [...]» au lieu de «SOUS LE VEHICULE [...]».
    _STAGING_ZONE_PREFIXES = (
        "tour_du_vehicule_",
        "dans_le_vehicule_",
        "sous_le_capot_",
        "sous_le_vehicule_",
        "autres_prestations_",
    )
    _EXCLUDE_CK_PAT = re.compile(r"commentaire|image\d*$", re.I)

    _raw_ck_cols_added: list[str] = []
    _used_staging_names: set[str] = set(STAGING_COLS)

    for excel_col in list(df.columns):
        # Normalize first so the prefix check is case/bracket/accent agnostic
        staging_name = sa_utils.normalize_column_name(excel_col)
        if not any(staging_name.startswith(p) for p in _STAGING_ZONE_PREFIXES):
            continue
        # Exclude comment and image columns that accidentally share a zone prefix
        if _EXCLUDE_CK_PAT.search(staging_name):
            continue
        # Resolve 55-char truncation collision
        if staging_name in _used_staging_names:
            i = 1
            base = staging_name[:53]
            while f"{base}_{i}" in _used_staging_names:
                i += 1
            staging_name = f"{base}_{i}"
        _used_staging_names.add(staging_name)
        _raw_ck_cols_added.append(staging_name)
        df[staging_name] = df[excel_col].map(
            lambda v: (re.sub(r"\s+", " ", str(v)).strip() or None)
            if isinstance(v, str) else None
        )

    logger.info(f"  {len(_raw_ck_cols_added)} colonnes checkpoints brutes préparées pour staging")
    for _zpfx in _STAGING_ZONE_PREFIXES:
        _zn = sum(1 for c in _raw_ck_cols_added if c.startswith(_zpfx))
        logger.info(f"    {_zpfx}: {_zn} cols détectées")

    # ── 16. Colonnes techniques ────────────────────────────────────────────
    df["source_system"] = SOURCE_SYSTEM
    df["created_at"]    = datetime.now(timezone.utc).replace(tzinfo=None)

    # ── 17. ID source séquentiel ───────────────────────────────────────────
    df = df.reset_index(drop=True)
    df.insert(0, "inspection_source_id", range(1, len(df) + 1))

    # ── 18. Sélection colonnes finales staging ────────────────────────────
    # Les enc_* restent dans df_working mais ne sont pas dans STAGING_COLS.
    # Les colonnes checkpoint brutes détectées dynamiquement (étape 15)
    # sont ajoutées après STAGING_COLS.
    _all_staging_cols = STAGING_COLS + _raw_ck_cols_added
    for col in _all_staging_cols:
        if col not in df.columns:
            df[col] = None

    df_final = df[_all_staging_cols].copy()

    # ── 18. Métriques DQ ──────────────────────────────────────────────────
    n_valid   = int(df_final["is_valid_for_join"].sum())
    n_mauvais = int(df_final["indicateur_mauvais_etat"].sum())

    metrics = {
        "n_raw":             n_raw,
        "n_loaded":          len(df_final),
        "n_dupes_supprimes": n_dupes_supprimes,
        "n_valid_for_join":  n_valid,
        "n_immat_manquante": len(df_final) - n_valid,
        "n_mauvais_etat":    n_mauvais,
        "n_critique":        int((df_final["niveau_etat_vehicule"] == "CRITIQUE").sum()),
        "dist_niveau":       df_final["niveau_etat_vehicule"].value_counts().to_dict(),
        "km_median":         int(df_final["kilometrage"].median()) if df_final["kilometrage"].notna().any() else None,
    }

    return df_final, metrics


# ---------------------------------------------------------------------------
# Chargement
# ---------------------------------------------------------------------------

def prepare_inspection_sa(run_id: str, engine, logger) -> int:
    """
    Lit FicheVoitureStafim.xlsx, nettoie et charge staging.stg_inspection.
    Retourne le nombre de lignes chargées.
    """
    logger.info(f"[RUN {run_id}] {SOURCE_FILE}")

    if not STAFIM_PATH.exists():
        raise FileNotFoundError(f"Fichier source introuvable : {STAFIM_PATH}")

    df_raw = pd.read_excel(STAFIM_PATH, dtype=str)
    logger.info(f"  {len(df_raw)} lignes lues / {df_raw.shape[1]} colonnes")

    df_final, metrics = transform_inspection(df_raw, logger)

    logger.info(f"  [STEP] Chargement PostgreSQL {SCHEMA}.{TABLE_NAME}")

    n_rows, elapsed = sa_utils.write_to_postgres(
        df_final, engine, SCHEMA, TABLE_NAME, logger
    )

    sa_utils.write_audit_row(
        engine, run_id,
        table_name=f"{SCHEMA}.{TABLE_NAME}",
        source_file=SOURCE_FILE,
        n_rows=n_rows,
        n_cols=df_final.shape[1],
        elapsed=elapsed,
        status="SUCCESS",
        logger=logger,
    )

    # Log métriques DQ
    logger.info("=" * 60)
    logger.info(f"  lignes source lues               : {metrics['n_raw']}")
    logger.info(f"  doublons supprimés               : {metrics['n_dupes_supprimes']}")
    logger.info(f"  lignes chargées DWH              : {metrics['n_loaded']}")
    logger.info(f"  immat valides (is_valid_for_join): {metrics['n_valid_for_join']}")
    logger.info(f"  immat manquantes                 : {metrics['n_immat_manquante']}")
    logger.info(f"  véhicules mauvais état           : {metrics['n_mauvais_etat']}")
    logger.info(f"  véhicules état critique          : {metrics['n_critique']}")
    logger.info(f"  kilométrage médian               : {metrics['km_median']} km")
    logger.info("  -- distribution niveau_etat_vehicule --")
    for niveau, n in sorted(metrics["dist_niveau"].items()):
        logger.info(f"    {niveau:<12} : {n}")
    logger.info("=" * 60)

    return n_rows


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    logger = sa_utils.setup_logging(run_id, log_name="prepare_inspection_sa")
    engine = sa_utils.build_engine(logger)
    sa_utils.create_schemas(engine, logger)

    n = prepare_inspection_sa(run_id, engine, logger)
    logger.info(f"Terminé : {n} lignes → {SCHEMA}.{TABLE_NAME}")
