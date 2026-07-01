"""
etl/dwh/load_dim_tiers.py
=========================
Charge staging.stg_sinistres -> dwh.dim_tiers.

Grain      : une ligne par tiers identifié (clé fonctionnelle)
Clé métier : (nom_tiers, immatriculation_vehicule_tiers,
              numero_contrat_tiers, numero_sinistre_tiers)
Clé tech   : tiers_sk, entier séquentiel généré par le DWH

Source     : staging.stg_sinistres uniquement.
             Sinistres.xlsx contient les informations du tiers déclaré
             dans le sinistre automobile (NOMTIERS, IMVEHTIER, etc.).

Colonnes source → DWH :
  nomtiers   → nom_tiers
  imvehtier  → immatriculation_vehicule_tiers
  numcnttie  → numero_contrat_tiers
  numsnttie  → numero_sinistre_tiers

Note : codpostie (CODPOSTIE) exclu — entièrement NULL dans la source.

Colonnes finales :
  tiers_sk, nom_tiers, immatriculation_vehicule_tiers,
  numero_contrat_tiers, numero_sinistre_tiers,
  source_system, created_at

Usage :
  python etl/dwh/load_dim_tiers.py
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwh_utils

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

TABLE_NAME    = "dim_tiers"
SOURCE_TABLE  = "staging.stg_sinistres"
SOURCE_SYSTEM = "SINISTRES"
TODAY         = datetime.now(timezone.utc).replace(tzinfo=None)

FINAL_COLS = [
    "tiers_sk",
    "nom_tiers",
    "immatriculation_vehicule_tiers",
    "numero_contrat_tiers",
    "numero_sinistre_tiers",
    "source_system",
    "created_at",
]

# Clé fonctionnelle de déduplication
DEDUP_KEY = [
    "nom_tiers",
    "immatriculation_vehicule_tiers",
    "numero_contrat_tiers",
    "numero_sinistre_tiers",
]

# Colonnes source (noms normalisés staging) → noms cibles DWH
COLUMN_MAP: dict[str, str] = {
    "nomtiers":  "nom_tiers",
    "imvehtier": "immatriculation_vehicule_tiers",
    "numcnttie": "numero_contrat_tiers",
    "numsnttie": "numero_sinistre_tiers",
}

# Variantes acceptées si la normalisation staging produit un nom légèrement différent
COLUMN_CANDIDATES: dict[str, list[str]] = {
    "nom_tiers":                     ["nomtiers",  "nom_tiers",  "nom_tier"],
    "immatriculation_vehicule_tiers": ["imvehtier", "imvehtiers", "immat_tiers", "immatriculation_tiers"],
    "numero_contrat_tiers":          ["numcnttie", "num_cnt_tie", "numcnt_tier", "numero_contrat_tiers"],
    "numero_sinistre_tiers":         ["numsnttie", "num_snt_tie", "numsnt_tier", "numero_sinistre_tiers"],
}

# Valeurs textuelles non exploitables (comparées après upper() + strip())
_INVALID_COMMUN = frozenset({
    "", "NULL", "NAN", "NONE", "INCONNU",
    "NON RENSEIGNE", "NON RENSEIGNÉ",
    "N/A", "NA", "#N/A", "ND", "NR",
    "/", "-", "--", "---", ".", "..",
})

_INVALID_NOM = _INVALID_COMMUN | frozenset({
    "SANS TIERS", "PAS DE TIERS", "NEANT", "NÉANT",
    "SANS", "AUCUN", "AUCUNE",
    # Descriptions d'événements ou codes ambigus, pas des noms de tiers
    "DERAPAGE", "DIVERS CHOCS", "BRIS DE GLASS", "BG", "B.G",
})

_INVALID_IMMAT = _INVALID_COMMUN | frozenset({
    "0", "00", "000", "0000", "00000", "000000",
    "SANS TIERS", "PAS DE TIERS", "NEANT", "NÉANT",
    "INCONNU", "NON RENSEIGNE",
    # Piétons, deux-roues non immatriculés, valeurs spéciales
    "#", "#MOBYLETTE", "#PIETON", "MOBYLETTE", "PIETON",
    "NON ASSURE", "NON ASSURÉ",
})

_INVALID_ID = _INVALID_COMMUN | frozenset({
    # Abréviations "non fourni" fréquentes dans la source BNA
    "NF", "NF.", "N", "N.D", "RAS",
    # Zéros padding
    "0", "00", "0000", "00000", "000000",
})


# Civilités à supprimer du nom tiers
_CIVILITES = re.compile(
    r"^\s*(MR\.?|M\.?|MME\.?|MONSIEUR|MADAME|DR\.?|STE\.?|SA\b|SARL\b)\s+",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Helpers colonnes
# ---------------------------------------------------------------------------

def _first_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _resolve_columns(df: pd.DataFrame) -> dict[str, str | None]:
    return {
        target: _first_col(df, candidates)
        for target, candidates in COLUMN_CANDIDATES.items()
    }


# ---------------------------------------------------------------------------
# Fonctions de nettoyage
# ---------------------------------------------------------------------------

def _clean_nom_tiers(val: object) -> str | None:
    """Nettoie le nom du tiers : supprime civilités, normalise, uppercase."""
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    s = str(val).strip()
    s = _CIVILITES.sub("", s)
    s = re.sub(r"\s+", " ", s).strip().upper()
    return None if s in _INVALID_NOM else s


def _clean_immat_tiers(val: object) -> str | None:
    """Nettoie l'immatriculation du véhicule tiers : uppercase, strip, invalid → None."""
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    s = re.sub(r"\s+", "", str(val).strip()).upper()
    return None if s in _INVALID_IMMAT else s


def _clean_id(val: object, invalid_set: frozenset) -> str | None:
    """Nettoie un identifiant textuel (numéro contrat ou sinistre tiers)."""
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    # Convertir les entiers/floats sans perdre la valeur
    if isinstance(val, (int, float)):
        s = str(int(val))
    else:
        s = str(val).strip().upper()
    return None if s in invalid_set else s


# ---------------------------------------------------------------------------
# Lecture staging
# ---------------------------------------------------------------------------

def _read_staging(engine, logger) -> pd.DataFrame:
    """
    Lit les colonnes tiers depuis staging.stg_sinistres.
    Sélectionne uniquement les colonnes disponibles.
    """
    target_cols = list(COLUMN_MAP.keys())  # nomtiers, imvehtier, numcnttie, numsnttie

    with engine.connect() as conn:
        available = set(
            row[0] for row in conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'staging'
                  AND table_name   = 'stg_sinistres'
            """)).fetchall()
        )

    select_cols = [c for c in target_cols if c in available]
    missing     = [c for c in target_cols if c not in available]

    if missing:
        logger.warning(f"  Colonnes non trouvées dans stg_sinistres : {missing}")

    if not select_cols:
        raise RuntimeError(
            "Aucune colonne tiers trouvée dans staging.stg_sinistres. "
            "Vérifiez que load_sinistres_sa.py a bien été exécuté."
        )

    sql = text(f"SELECT {', '.join(select_cols)} FROM staging.stg_sinistres")
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn)

    logger.info(f"  {len(df)} lignes lues depuis {SOURCE_TABLE}")
    logger.info(f"  Colonnes lues : {list(df.columns)}")
    return df


# ---------------------------------------------------------------------------
# Transformation principale
# ---------------------------------------------------------------------------

def transform_dim_tiers(
    df_raw: pd.DataFrame,
    logger,
) -> tuple[pd.DataFrame, dict]:
    """
    Transforme les données brutes tiers en dwh.dim_tiers.
    Retourne (df_final, metrics).
    """
    n_raw = len(df_raw)
    df    = df_raw.copy()

    # ── Résolution des noms de colonnes ──────────────────────────────────────
    col_map = _resolve_columns(df)
    logger.info(f"  Résolution colonnes : {col_map}")

    for target, src in col_map.items():
        if src is not None and src != target:
            df[target] = df[src]
        elif src is None and target not in df.columns:
            df[target] = None

    # ── 1. Nettoyage nom tiers ────────────────────────────────────────────────
    df["nom_tiers"] = df["nom_tiers"].map(_clean_nom_tiers)

    # ── 2. Nettoyage immatriculation véhicule tiers ───────────────────────────
    df["immatriculation_vehicule_tiers"] = df["immatriculation_vehicule_tiers"].map(_clean_immat_tiers)

    # ── 3. Nettoyage identifiants tiers ──────────────────────────────────────
    df["numero_contrat_tiers"]  = df["numero_contrat_tiers"].map(
        lambda v: _clean_id(v, _INVALID_ID)
    )
    df["numero_sinistre_tiers"] = df["numero_sinistre_tiers"].map(
        lambda v: _clean_id(v, _INVALID_ID)
    )

    # ── 5. Filtrage : exclure les lignes totalement vides ─────────────────────
    mask_vide = df[DEDUP_KEY].isnull().all(axis=1)
    n_vides   = int(mask_vide.sum())
    df        = df[~mask_vide].copy()
    n_candidates = len(df)
    if n_vides:
        logger.info(f"  Lignes totalement vides exclues : {n_vides}")
    logger.info(f"  Lignes candidates tiers : {n_candidates}")

    # ── 6. Déduplication sur la clé fonctionnelle ─────────────────────────────
    df_best = df.drop_duplicates(subset=DEDUP_KEY, keep="first").copy()
    n_dupes = n_candidates - len(df_best)
    if n_dupes:
        logger.info(f"  Doublons fonctionnels supprimés : {n_dupes}")
    logger.info(f"  Tiers distincts après dédup : {len(df_best)}")

    # ── 7. Clé technique séquentielle ─────────────────────────────────────────
    df_best = df_best.reset_index(drop=True)
    df_best.insert(0, "tiers_sk", range(1, len(df_best) + 1))

    # ── 8. Colonnes techniques DWH ────────────────────────────────────────────
    df_best["source_system"] = SOURCE_SYSTEM
    df_best["created_at"]    = TODAY

    # ── 9. Sélection finale des tiers réels ──────────────────────────────────
    for col in FINAL_COLS:
        if col not in df_best.columns:
            df_best[col] = None

    df_real = df_best[FINAL_COLS].copy()
    n_real  = len(df_real)

    # ── 10. Ligne technique UNKNOWN (tiers_sk = 0) ───────────────────────────
    # fact_sinistre référence tiers_sk = 0 pour les sinistres sans tiers
    # exploitable.  Cette ligne doit toujours exister dans dim_tiers.
    unknown_row = pd.DataFrame([{
        "tiers_sk":                       0,
        "nom_tiers":                      "UNKNOWN",
        "immatriculation_vehicule_tiers":  None,
        "numero_contrat_tiers":            None,
        "numero_sinistre_tiers":           None,
        "source_system":                   "TECHNICAL",
        "created_at":                      TODAY,
    }])

    # UNKNOWN en tête, tiers réels ensuite (SK 1..N)
    df_final = pd.concat([unknown_row, df_real], ignore_index=True)
    df_final["tiers_sk"] = df_final["tiers_sk"].astype("int64")

    # ── Métriques ─────────────────────────────────────────────────────────────
    n_total       = len(df_final)
    n_avec_nom    = int(df_real["nom_tiers"].notna().sum())
    n_avec_immat  = int(df_real["immatriculation_vehicule_tiers"].notna().sum())
    n_avec_cnt    = int(df_real["numero_contrat_tiers"].notna().sum())
    n_avec_snt    = int(df_real["numero_sinistre_tiers"].notna().sum())
    n_dup_sk      = int(df_final["tiers_sk"].duplicated().sum())
    n_dup_grain   = int(df_final[DEDUP_KEY].duplicated().sum())

    metrics = {
        "n_raw":               n_raw,
        "n_candidates":        n_candidates,
        "n_vides":             n_vides,
        "n_dupes":             n_dupes,
        "n_real_tiers":        n_real,
        "n_total_with_unknown": n_total,
        "unknown_row_present": True,
        "n_avec_nom":          n_avec_nom,
        "n_avec_immat":        n_avec_immat,
        "n_avec_cnt":          n_avec_cnt,
        "n_avec_snt":          n_avec_snt,
        "duplicate_sk_count":  n_dup_sk,
        "duplicate_grain_count": n_dup_grain,
    }
    return df_final, metrics


# ---------------------------------------------------------------------------
# Chargement principal
# ---------------------------------------------------------------------------

def load_dim_tiers(run_id: str, engine, logger) -> int:
    """
    Orchestre la lecture, la transformation et le chargement de dwh.dim_tiers.
    Retourne le nombre de lignes chargées.
    """
    logger.info(f"[RUN {run_id}] {SOURCE_TABLE} -> dwh.{TABLE_NAME}")

    with engine.connect() as conn:
        exists = conn.execute(text("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'staging'
              AND table_name   = 'stg_sinistres'
        """)).fetchone()
    if not exists:
        raise RuntimeError(
            f"Table source {SOURCE_TABLE} introuvable. "
            "Exécutez d'abord load_sinistres_sa.py."
        )

    df_raw = _read_staging(engine, logger)

    if df_raw.empty:
        logger.warning("  Aucune ligne dans staging.stg_sinistres — chargement annulé")
        return 0

    df_final, m = transform_dim_tiers(df_raw, logger)

    n_rows, elapsed = dwh_utils.write_to_dwh(df_final, engine, TABLE_NAME, logger)

    logger.info("=" * 60)
    logger.info(f"  lignes lues depuis staging         : {m['n_raw']}")
    logger.info(f"  lignes candidates tiers            : {m['n_candidates']}")
    logger.info(f"  lignes totalement vides exclues    : {m['n_vides']}")
    logger.info(f"  doublons fonctionnels supprimés    : {m['n_dupes']}")
    logger.info(f"  tiers réels distincts chargés      : {m['n_real_tiers']}")
    logger.info(f"  total lignes avec UNKNOWN          : {m['n_total_with_unknown']}")
    logger.info(f"  unknown_row_present                : {m['unknown_row_present']}")
    logger.info(f"  avec nom tiers                     : {m['n_avec_nom']}")
    logger.info(f"  avec immatriculation véhicule tiers: {m['n_avec_immat']}")
    logger.info(f"  avec numéro contrat tiers          : {m['n_avec_cnt']}")
    logger.info(f"  avec numéro sinistre tiers         : {m['n_avec_snt']}")
    logger.info(f"  doublons tiers_sk                  : {m['duplicate_sk_count']}")
    logger.info(f"  doublons grain fonctionnel         : {m['duplicate_grain_count']}")
    logger.info(f"  durée chargement                   : {elapsed:.1f}s")
    logger.info("=" * 60)
    logger.info("Validation SQL :")
    logger.info("""
-- 1. Ligne UNKNOWN
SELECT *
FROM dwh.dim_tiers
WHERE tiers_sk = 0;

-- 2. Répartition réels / UNKNOWN
SELECT
    COUNT(*)                                  AS total_rows,
    COUNT(*) FILTER (WHERE tiers_sk = 0)      AS unknown_rows,
    COUNT(*) FILTER (WHERE tiers_sk <> 0)     AS real_tiers_rows
FROM dwh.dim_tiers;

-- 3. Doublons sur tiers_sk
SELECT tiers_sk, COUNT(*) AS nb
FROM dwh.dim_tiers
GROUP BY tiers_sk
HAVING COUNT(*) > 1;

-- 4. Couverture dans fact_sinistre
SELECT
    COUNT(*)                                                          AS total_sinistres,
    COUNT(*) FILTER (WHERE tiers_sk = 0)                             AS tiers_unknown,
    COUNT(*) FILTER (WHERE tiers_sk = 0 AND camtier_sk = 0)          AS tiers_et_camtier_absents,
    COUNT(*) FILTER (WHERE tiers_sk = 0 AND camtier_sk <> 0)         AS camtier_present_tiers_absent,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE tiers_sk = 0 AND camtier_sk <> 0)
        / NULLIF(COUNT(*) FILTER (WHERE tiers_sk = 0), 0),
        2
    )                                                                 AS pct_camtier_present_tiers_absent
FROM dwh.fact_sinistre;
""")

    return n_rows


# ---------------------------------------------------------------------------
# Point d'entrée autonome
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _run_id  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    _logger  = dwh_utils.setup_logging(_run_id, log_name="load_dim_tiers")
    _engine  = dwh_utils.build_engine(_logger)
    dwh_utils.create_dwh_schema(_engine, _logger)
    _n = load_dim_tiers(_run_id, _engine, _logger)
    _logger.info(f"Terminé : {_n} lignes -> dwh.{TABLE_NAME}")
