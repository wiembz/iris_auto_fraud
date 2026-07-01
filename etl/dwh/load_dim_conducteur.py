"""
etl/dwh/load_dim_conducteur.py
==============================
Charge staging.stg_sinistres -> dwh.dim_conducteur.

Grain      : une ligne par conducteur identifié (clé fonctionnelle)
Clé métier : (nom_conducteur, date_naissance_conducteur,
              numero_permis, categorie_permis, date_permis)
Clé tech   : conducteur_sk, entier séquentiel généré par le DWH

Source     : staging.stg_sinistres uniquement.
             Sinistres.xlsx contient les informations du conducteur déclaré.
             Stafim/NOM ET PRENOM = personne présente à l'inspection (non conducteur).

Colonnes source (après normalisation staging) :
  nomconduc   → nom_conducteur
  datnaicon   → date_naissance_conducteur
  numpermis   → numero_permis
  categperm   → categorie_permis
  datepermi   → date_permis
  dtdecsnt    → référence date sinistre pour calcul âge / ancienneté

Colonnes finales :
  conducteur_sk, nom_conducteur, date_naissance_conducteur,
  numero_permis, categorie_permis, date_permis,
  age_conducteur, anciennete_permis, source_system, created_at

Usage :
  python etl/dwh/load_dim_conducteur.py
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

TABLE_NAME    = "dim_conducteur"
SOURCE_TABLE  = "staging.stg_sinistres"
SOURCE_SYSTEM = "SINISTRES"
TODAY         = datetime.now(timezone.utc).replace(tzinfo=None)

FINAL_COLS = [
    "conducteur_sk",
    "nom_conducteur",
    "date_naissance_conducteur",
    "numero_permis",
    "categorie_permis",
    "date_permis",
    "age_conducteur",
    "anciennete_permis",
    "source_system",
    "created_at",
]

# Clé fonctionnelle de déduplication
DEDUP_KEY = [
    "nom_conducteur",
    "date_naissance_conducteur",
    "numero_permis",
    "categorie_permis",
    "date_permis",
]

# Correspondance colonnes staging → colonnes DWH
COLUMN_MAP = {
    "nomconduc":  "nom_conducteur",
    "datnaicon":  "date_naissance_conducteur",
    "numpermis":  "numero_permis",
    "categperm":  "categorie_permis",
    "datepermi":  "date_permis",
    "dtdecsnt":   "_date_sinistre",   # colonne de travail, non exportée
}

# Variantes acceptées si le nom normalisé diffère légèrement
COLUMN_CANDIDATES: dict[str, list[str]] = {
    "nom_conducteur":           ["nomconduc", "nom_conducteur", "nom_conduc", "nomcond"],
    "date_naissance_conducteur":["datnaicon", "date_naissance_conducteur", "dnaiscond", "datnaiscond"],
    "numero_permis":            ["numpermis", "numero_permis", "num_permis", "numperm"],
    "categorie_permis":         ["categperm", "categorie_permis", "cat_permis", "catperm"],
    "date_permis":              ["datepermi", "date_permis", "dat_permis", "datpermis", "datepermi"],
    "_date_sinistre":           ["dtdecsnt", "date_sinistre", "dtdecsntre", "date_dec_sinistre"],
}

# Valeurs textuelles invalides (comparées après upper())
_INVALID = frozenset({
    "", "NULL", "NAN", "NONE", "INCONNU",
    "NON RENSEIGNE", "NON RENSEIGNÉ", "N/A", "NA", "#N/A", "ND", "NR",
})

# Civilités à supprimer du nom conducteur
_CIVILITES = re.compile(
    r"^\s*(MR\.?|M\.?|MME\.?|MONSIEUR|MADAME|DR\.?|DOCTEUR)\s+",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Helpers colonnes
# ---------------------------------------------------------------------------

def _first_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Retourne le premier nom de colonne existant parmi les candidats."""
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _resolve_columns(df: pd.DataFrame) -> dict[str, str | None]:
    """
    Retourne un dict {nom_final: nom_réel_dans_df} pour chaque colonne cible.
    Valeur None si aucun candidat n'existe dans df.
    """
    return {
        target: _first_col(df, candidates)
        for target, candidates in COLUMN_CANDIDATES.items()
    }


# ---------------------------------------------------------------------------
# Nettoyage des champs
# ---------------------------------------------------------------------------

def _clean_nom(val: object) -> str | None:
    """Nettoie le nom conducteur : supprime civilités, normalise espaces, uppercase."""
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    s = str(val).strip()
    s = _CIVILITES.sub("", s)
    s = re.sub(r"\s+", " ", s).strip().upper()
    return None if s in _INVALID else s


def _clean_str(val: object) -> str | None:
    """Nettoie un champ texte court : uppercase, strip, invalid → None."""
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    s = re.sub(r"\s+", " ", str(val).strip()).upper()
    return None if s in _INVALID else s


def _clean_date(val: object) -> pd.Timestamp | None:
    """Convertit en date ; valeur invalide → None."""
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    try:
        ts = pd.to_datetime(val, dayfirst=True, errors="coerce")
        return None if pd.isna(ts) else ts
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Calculs âge / ancienneté
# ---------------------------------------------------------------------------

def _age_annees(dob: object, ref: datetime) -> int | None:
    """Âge en années complètes entre dob et ref."""
    if dob is None or (isinstance(dob, float) and pd.isna(dob)):
        return None
    try:
        dob_ts = pd.Timestamp(dob)
        if pd.isna(dob_ts):
            return None
        years = ref.year - dob_ts.year
        if (ref.month, ref.day) < (dob_ts.month, dob_ts.day):
            years -= 1
        return years if years >= 0 else None
    except Exception:
        return None


def _anciennete_annees(date_permis: object, ref: datetime) -> int | None:
    """Ancienneté du permis en années complètes entre date_permis et ref."""
    if date_permis is None or (isinstance(date_permis, float) and pd.isna(date_permis)):
        return None
    try:
        dp_ts = pd.Timestamp(date_permis)
        if pd.isna(dp_ts):
            return None
        years = ref.year - dp_ts.year
        if (ref.month, ref.day) < (dp_ts.month, dp_ts.day):
            years -= 1
        return years if years >= 0 else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Lecture staging
# ---------------------------------------------------------------------------

def _read_staging(engine, logger) -> pd.DataFrame:
    """
    Lit les colonnes conducteur depuis staging.stg_sinistres.
    Tente d'abord un SELECT ciblé ; si une colonne manque, charge tout
    et laisse _resolve_columns gérer les variantes.
    """
    target_cols = ["nomconduc", "datnaicon", "numpermis", "categperm", "datepermi", "dtdecsnt"]

    # Colonnes réellement présentes dans la table
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
    extra_present = [c for c in target_cols if c not in available]

    if extra_present:
        logger.warning(f"  Colonnes non trouvées dans stg_sinistres : {extra_present}")

    if not select_cols:
        raise RuntimeError(
            "Aucune colonne conducteur trouvée dans staging.stg_sinistres. "
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

def transform_dim_conducteur(
    df_raw: pd.DataFrame,
    logger,
) -> tuple[pd.DataFrame, dict]:
    """
    Transforme les données brutes conducteur en dwh.dim_conducteur.
    Retourne (df_final, metrics).
    """
    n_raw = len(df_raw)
    df    = df_raw.copy()

    # ── Résolution des noms de colonnes ──────────────────────────────────────
    col_map = _resolve_columns(df)
    logger.info(f"  Résolution colonnes : {col_map}")

    # ── Mapping → noms cibles ─────────────────────────────────────────────────
    for target, src in col_map.items():
        if src is not None and src != target:
            df[target] = df[src]
        elif src is None and target not in df.columns:
            df[target] = None

    # ── 1. Nettoyage nom conducteur ───────────────────────────────────────────
    df["nom_conducteur"] = df["nom_conducteur"].map(_clean_nom)

    # ── 2. Nettoyage permis ───────────────────────────────────────────────────
    df["numero_permis"]   = df["numero_permis"].map(_clean_str)
    df["categorie_permis"] = df["categorie_permis"].map(_clean_str)
    df["date_permis"]     = df["date_permis"].map(_clean_date)

    # ── 3. Date naissance ─────────────────────────────────────────────────────
    df["date_naissance_conducteur"] = df["date_naissance_conducteur"].map(_clean_date)

    # ── 4. Date sinistre de référence (colonne de travail) ────────────────────
    if "_date_sinistre" in df.columns:
        df["_date_sinistre"] = pd.to_datetime(df["_date_sinistre"], errors="coerce")
    else:
        df["_date_sinistre"] = pd.NaT

    # ── 5. Filtrage : exclure les lignes totalement vides ─────────────────────
    data_cols = ["nom_conducteur", "date_naissance_conducteur",
                 "numero_permis", "categorie_permis", "date_permis"]
    mask_vide = df[data_cols].isnull().all(axis=1)
    n_vides   = int(mask_vide.sum())
    df = df[~mask_vide].copy()
    n_candidates = len(df)
    if n_vides:
        logger.info(f"  Lignes totalement vides exclues : {n_vides}")
    logger.info(f"  Lignes candidates conducteur : {n_candidates}")

    # ── 6. Déduplication sur la clé fonctionnelle ─────────────────────────────
    # Trier par date sinistre DESC pour que la ligne "winner" porte la date
    # la plus récente (utilisée pour le calcul âge / ancienneté).
    df_sorted = df.sort_values("_date_sinistre", ascending=False, na_position="last")
    df_best   = df_sorted.drop_duplicates(subset=DEDUP_KEY, keep="first").copy()
    n_dupes   = n_candidates - len(df_best)
    if n_dupes:
        logger.info(f"  Doublons fonctionnels supprimés : {n_dupes}")
    logger.info(f"  Conducteurs distincts après dédup : {len(df_best)}")

    # ── 7. Calcul âge et ancienneté ───────────────────────────────────────────
    # Référence : date du sinistre si disponible, sinon date de chargement.
    def _ref(row) -> datetime:
        ds = row["_date_sinistre"]
        if pd.notna(ds):
            return ds.to_pydatetime()
        return TODAY

    df_best["age_conducteur"] = df_best.apply(
        lambda r: _age_annees(r["date_naissance_conducteur"], _ref(r)),
        axis=1,
    ).astype("Int64")   # nullable integer

    df_best["anciennete_permis"] = df_best.apply(
        lambda r: _anciennete_annees(r["date_permis"], _ref(r)),
        axis=1,
    ).astype("Int64")

    # ── 7b. Nettoyage qualité métier âge et ancienneté ────────────────────────
    # Âge conducteur : impossible < 16 ans (âge légal permis) ou > 100 ans
    mask_age_invalid = (
        df_best["age_conducteur"].notna()
        & ((df_best["age_conducteur"] < 16) | (df_best["age_conducteur"] > 100))
    )
    n_age_invalid = int(mask_age_invalid.sum())
    df_best.loc[mask_age_invalid, "age_conducteur"] = pd.NA

    # Ancienneté permis : impossible < 0 ou > 80 ans
    mask_anc_invalid = (
        df_best["anciennete_permis"].notna()
        & ((df_best["anciennete_permis"] < 0) | (df_best["anciennete_permis"] > 80))
    )
    n_anc_invalid = int(mask_anc_invalid.sum())
    df_best.loc[mask_anc_invalid, "anciennete_permis"] = pd.NA

    # Cohérence : ancienneté permis > (âge - 16) → impossible (permis avant 16 ans)
    mask_coherence = (
        df_best["age_conducteur"].notna()
        & df_best["anciennete_permis"].notna()
        & (df_best["anciennete_permis"] > (df_best["age_conducteur"] - 16))
    )
    n_coherence = int(mask_coherence.sum())
    df_best.loc[mask_coherence, "anciennete_permis"] = pd.NA

    if n_age_invalid:
        logger.info(f"  Âges aberrants mis à NULL        : {n_age_invalid}")
    if n_anc_invalid:
        logger.info(f"  Anciennetés aberrantes mises à NULL : {n_anc_invalid}")
    if n_coherence:
        logger.info(f"  Incohérences âge/permis mises à NULL : {n_coherence}")

    # ── 8. Clé technique séquentielle ─────────────────────────────────────────
    df_best = df_best.reset_index(drop=True)
    df_best.insert(0, "conducteur_sk", range(1, len(df_best) + 1))

    # ── 9. Colonnes techniques DWH ────────────────────────────────────────────
    df_best["source_system"] = SOURCE_SYSTEM
    df_best["created_at"]    = TODAY

    # ── 10. Sélection finale des conducteurs réels ───────────────────────────
    for col in FINAL_COLS:
        if col not in df_best.columns:
            df_best[col] = None

    df_real = df_best[FINAL_COLS].copy()
    n_real  = len(df_real)

    # ── 11. Ligne technique UNKNOWN (conducteur_sk = 0) ──────────────────────
    # fact_sinistre référence conducteur_sk = 0 pour les sinistres sans
    # conducteur exploitable.  Cette ligne doit toujours exister.
    unknown_row = pd.DataFrame([{
        "conducteur_sk":              0,
        "nom_conducteur":             "UNKNOWN",
        "date_naissance_conducteur":  None,
        "numero_permis":              None,
        "categorie_permis":           None,
        "date_permis":                None,
        "age_conducteur":             None,
        "anciennete_permis":          None,
        "source_system":              "TECHNICAL",
        "created_at":                 TODAY,
    }])

    # UNKNOWN en tête, conducteurs réels ensuite (SK 1..N)
    df_final = pd.concat([unknown_row, df_real], ignore_index=True)
    df_final["conducteur_sk"] = df_final["conducteur_sk"].astype("int64")

    # ── Métriques ─────────────────────────────────────────────────────────────
    n_total       = len(df_final)
    n_avec_nom        = int(df_real["nom_conducteur"].notna().sum())
    n_avec_permis     = int(df_real["numero_permis"].notna().sum())
    n_avec_ddn        = int(df_real["date_naissance_conducteur"].notna().sum())
    n_avec_date_permis= int(df_real["date_permis"].notna().sum())
    ages_ok           = df_real["age_conducteur"].dropna()
    anc_ok            = df_real["anciennete_permis"].dropna()
    n_avec_age        = len(ages_ok)
    n_avec_anc        = len(anc_ok)
    n_dup_sk          = int(df_final["conducteur_sk"].duplicated().sum())
    n_dup_grain       = int(df_final[DEDUP_KEY].duplicated().sum())

    metrics = {
        "n_raw":                  n_raw,
        "n_candidates":           n_candidates,
        "n_vides":                n_vides,
        "n_dupes":                n_dupes,
        "n_real_conducteur":      n_real,
        "n_total_with_unknown":   n_total,
        "unknown_row_present":    True,
        "n_avec_nom":             n_avec_nom,
        "n_avec_permis":          n_avec_permis,
        "n_avec_ddn":             n_avec_ddn,
        "n_avec_date_permis":     n_avec_date_permis,
        "n_avec_age":             n_avec_age,
        "n_avec_anc":             n_avec_anc,
        "n_age_invalid":          n_age_invalid,
        "n_anc_invalid":          n_anc_invalid,
        "n_coherence":            n_coherence,
        "age_moyen":              round(float(ages_ok.mean()), 1) if len(ages_ok) else None,
        "anciennete_moy":         round(float(anc_ok.mean()), 1)  if len(anc_ok)  else None,
        "duplicate_sk_count":     n_dup_sk,
        "duplicate_grain_count":  n_dup_grain,
    }
    return df_final, metrics


# ---------------------------------------------------------------------------
# Chargement principal
# ---------------------------------------------------------------------------

def load_dim_conducteur(run_id: str, engine, logger) -> int:
    """
    Orchestre la lecture, la transformation et le chargement de dwh.dim_conducteur.
    Retourne le nombre de lignes chargées.
    """
    logger.info(f"[RUN {run_id}] {SOURCE_TABLE} -> dwh.{TABLE_NAME}")

    # Vérifier que la table source existe
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

    df_final, m = transform_dim_conducteur(df_raw, logger)

    n_rows, elapsed = dwh_utils.write_to_dwh(df_final, engine, TABLE_NAME, logger)

    logger.info("=" * 60)
    logger.info(f"  lignes lues depuis staging          : {m['n_raw']}")
    logger.info(f"  lignes candidates conducteur        : {m['n_candidates']}")
    logger.info(f"  lignes totalement vides exclues     : {m['n_vides']}")
    logger.info(f"  doublons fonctionnels supprimés     : {m['n_dupes']}")
    logger.info(f"  conducteurs réels distincts chargés : {m['n_real_conducteur']}")
    logger.info(f"  total lignes avec UNKNOWN           : {m['n_total_with_unknown']}")
    logger.info(f"  unknown_row_present                 : {m['unknown_row_present']}")
    logger.info(f"  avec nom conducteur                 : {m['n_avec_nom']}")
    logger.info(f"  avec numéro de permis               : {m['n_avec_permis']}")
    logger.info(f"  avec date de naissance              : {m['n_avec_ddn']}")
    logger.info(f"  avec date de permis                 : {m['n_avec_date_permis']}")
    logger.info(f"  avec age_conducteur renseigné       : {m['n_avec_age']}")
    logger.info(f"  avec anciennete_permis renseignée   : {m['n_avec_anc']}")
    logger.info(f"  âges aberrants mis à NULL           : {m['n_age_invalid']}")
    logger.info(f"  anciennetés aberrantes mises à NULL : {m['n_anc_invalid']}")
    logger.info(f"  incohérences âge/permis mises à NULL: {m['n_coherence']}")
    logger.info(f"  âge moyen (après nettoyage)         : {m['age_moyen']}")
    logger.info(f"  ancienneté permis moyenne           : {m['anciennete_moy']}")
    logger.info(f"  doublons conducteur_sk              : {m['duplicate_sk_count']}")
    logger.info(f"  doublons grain fonctionnel          : {m['duplicate_grain_count']}")
    logger.info(f"  durée chargement                    : {elapsed:.1f}s")
    logger.info("=" * 60)
    logger.info("Validation SQL :")
    logger.info("""
-- 1. Ligne UNKNOWN
SELECT *
FROM dwh.dim_conducteur
WHERE conducteur_sk = 0;

-- 2. Répartition réels / UNKNOWN
SELECT
    COUNT(*)                                    AS total_rows,
    COUNT(*) FILTER (WHERE conducteur_sk = 0)   AS unknown_rows,
    COUNT(*) FILTER (WHERE conducteur_sk <> 0)  AS real_conducteur_rows
FROM dwh.dim_conducteur;

-- 3. Doublons sur conducteur_sk
SELECT conducteur_sk, COUNT(*) AS nb
FROM dwh.dim_conducteur
GROUP BY conducteur_sk
HAVING COUNT(*) > 1;

-- 4. Couverture dans fact_sinistre
SELECT
    COUNT(*)                                           AS total_sinistres,
    COUNT(*) FILTER (WHERE conducteur_sk = 0)          AS conducteur_unknown,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE conducteur_sk = 0)
        / NULLIF(COUNT(*), 0),
        2
    )                                                  AS pct_conducteur_unknown
FROM dwh.fact_sinistre;
""")

    return n_rows


# ---------------------------------------------------------------------------
# Point d'entrée autonome
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _run_id  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    _logger  = dwh_utils.setup_logging(_run_id, log_name="load_dim_conducteur")
    _engine  = dwh_utils.build_engine(_logger)
    dwh_utils.create_dwh_schema(_engine, _logger)
    _n = load_dim_conducteur(_run_id, _engine, _logger)
    _logger.info(f"Terminé : {_n} lignes -> dwh.{TABLE_NAME}")
