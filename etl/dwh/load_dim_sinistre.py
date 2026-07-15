"""
etl/dwh/load_dim_sinistre.py
============================
Charge staging.stg_sinistres -> dwh.dim_sinistre.

Grain      : une ligne par sinistre unique
Clé métier : numero_sinistre (= NUMSNT)
Clé tech   : sinistre_sk, entier séquentiel généré par le DWH

Remarque : staging.stg_sinistres a pour grain NUMSNT + GRNTSINI
(plusieurs lignes par sinistre selon les garanties associées).
Ce script déduplique sur NUMSNT en conservant la ligne la plus
complète (maximum d'attributs descriptifs non-NULL).

Exclusions délibérées :
  - Montants                        → fact_sinistre
  - Dates clés                      → fact_sinistre (FK dim_date)
  - Clés FK autres dimensions       → fact_sinistre
  - TAUX                            → fact_sinistre
  - Géographie sinistre (regsini,
    gouvsini, citesini, cpostsini)  → dim_geo + fact_sinistre.geo_sinistre_sk
  - Colonnes techniques staging     → exclus
  - nature_sinistre, sous_nature,
    type_pave, heure_sinistre,
    reference_externe, source_dec,
    gestionnaire, resp_ida, respsnt → non retenus (voir décision modèle)

Colonnes finales (13) :
  sinistre_sk, numero_sinistre,
  cause_sinistre, libelle_cause_sinistre,
  code_etat, indicateur_forcage,
  cas_ida, coassur, reassur,
  indicateur_transaction,
  source_system, created_at

Note motif_cloture :
  EXCLU de dim_sinistre — instable au niveau NUMSNT (plusieurs sinistres
  ont 2 motifs distincts selon la garantie). À inclure dans fact_sinistre
  comme attribut dégénéré au grain NUMSNT + GRNTSINI.

Usage :
  python etl/dwh/load_dim_sinistre.py
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

TABLE_NAME    = "dim_sinistre"
SOURCE_TABLE  = "staging.stg_sinistres"
SOURCE_SYSTEM = "BNA_ASSURANCES"
TODAY         = datetime.now(timezone.utc).replace(tzinfo=None)

FINAL_COLS = [
    "sinistre_sk",
    "numero_sinistre",
    "cause_sinistre",
    "libelle_cause_sinistre",
    "code_etat",
    "indicateur_forcage",
    "cas_ida",
    "coassur",
    "reassur",
    "indicateur_transaction",
    "source_system",
    "created_at",
]

# Colonnes descriptives pour le score de complétude (déduplication)
DESCRIPTIVE_COLS = [
    "cause_sinistre",
    "libelle_cause_sinistre",
    "code_etat",
    "indicateur_forcage",
    "cas_ida",
    "coassur",
    "reassur",
    "indicateur_transaction",
]

# Candidats par ordre de priorité (vrais noms staging en tête)
# motif_cloture exclu : instable au niveau NUMSNT → ira dans fact_sinistre
COLUMN_CANDIDATES: dict[str, list[str]] = {
    "numero_sinistre":        ["numsnt",           "num_snt",      "numero_sinistre"],
    "cause_sinistre":         ["causesini_norm",    "causesini",    "causesin",     "cause_sinistre"],
    "libelle_cause_sinistre": ["claim_cause_label", "libelle_cause_sinistre"],
    "code_etat":              ["code_etat",         "codetat",      "cod_etat"],
    "indicateur_forcage":     ["indforcag",         "forcage",      "indicateur_forcage"],
    "cas_ida":                ["cas_ida",           "casida"],
    "coassur":                ["coassur"],
    "reassur":                ["reassur"],
    "indicateur_transaction": ["ddetransa",         "indicateur_transaction"],
}

# Valeurs texte invalides → NULL
_INVALID_TEXT = frozenset({
    "", ".", "..", "-", "--", "---", "/",
    "NAN", "NULL", "NONE", "UNKNOWN",
    "NON RENSEIGNE", "NON RENSEIGNÉ",
    "N/R", "N/A", "#N/A", "ND", "NR", "NA",
    "INCONNU",
})

_OUI_VALUES = frozenset({"O", "OUI", "YES", "Y", "TRUE", "1", "S", "SI"})
_NON_VALUES = frozenset({"N", "NON", "NO", "FALSE", "0"})


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

def _clean_text_upper(val: object) -> str | None:
    """Strip + uppercase. Valeurs invalides → None."""
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    if isinstance(val, (int, float)):
        try:
            f = float(val)
            s = str(int(f)) if f == int(f) else str(f)
        except (ValueError, OverflowError):
            s = str(val)
    else:
        s = str(val)
    s = re.sub(r"\s+", " ", s.strip()).upper()
    return None if s in _INVALID_TEXT else s


def _clean_indicator(val: object) -> str:
    """
    Normalise un indicateur binaire.
      OUI_VALUES → 'OUI'
      NON_VALUES → 'NON'
      NULL / invalide → 'NON_RENSEIGNE'
    """
    if val is None:
        return "NON_RENSEIGNE"
    if isinstance(val, float):
        if pd.isna(val):
            return "NON_RENSEIGNE"
        if val == 1.0:
            return "OUI"
        if val == 0.0:
            return "NON"
    if isinstance(val, int):
        return "OUI" if val == 1 else ("NON" if val == 0 else "NON_RENSEIGNE")
    s = str(val).strip().upper()
    if not s or s in _INVALID_TEXT:
        return "NON_RENSEIGNE"
    if s in _OUI_VALUES:
        return "OUI"
    if s in _NON_VALUES:
        return "NON"
    return "NON_RENSEIGNE"


# ---------------------------------------------------------------------------
# Lecture staging
# ---------------------------------------------------------------------------

def _read_staging(engine, logger) -> pd.DataFrame:
    """
    Lit depuis staging.stg_sinistres les colonnes nécessaires à dim_sinistre.
    Découverte dynamique : ne sélectionne que les colonnes réellement présentes.
    """
    all_candidates: set[str] = set()
    for cands in COLUMN_CANDIDATES.values():
        all_candidates.update(cands)

    with engine.connect() as conn:
        available = set(
            row[0] for row in conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'staging'
                  AND table_name   = 'stg_sinistres'
            """)).fetchall()
        )

    select_cols = sorted(all_candidates & available)
    missing     = sorted(all_candidates - available)

    if missing:
        logger.warning(f"  Colonnes candidates absentes dans staging : {missing}")

    if not select_cols:
        raise RuntimeError(
            "Aucune colonne attendue trouvée dans staging.stg_sinistres. "
            "Vérifiez que load_sinistres_sa.py a bien été exécuté."
        )

    logger.info(f"  {len(select_cols)} colonne(s) sélectionnée(s) : {select_cols}")

    sql = text(f"SELECT {', '.join(select_cols)} FROM {SOURCE_TABLE}")
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn)

    logger.info(f"  {len(df)} lignes lues depuis {SOURCE_TABLE}")
    return df


# ---------------------------------------------------------------------------
# Transformation principale
# ---------------------------------------------------------------------------

def transform_dim_sinistre(
    df_raw: pd.DataFrame,
    logger,
) -> tuple[pd.DataFrame, dict]:
    """
    Transforme les données brutes en dwh.dim_sinistre (13 colonnes).
    Retourne (df_final, metrics).
    """
    n_raw = len(df_raw)
    df    = df_raw.copy()

    # ── Résolution du mapping colonnes ───────────────────────────────────────
    col_map = _resolve_columns(df)
    logger.info("  Mapping colonnes staging → DWH :")
    for target, src in col_map.items():
        label = f"← {src}" if src else "← [absent → NULL]"
        logger.info(f"    {target:<30} {label}")

    for target, src in col_map.items():
        if src is not None and src != target:
            df[target] = df[src]
        elif src is None and target not in df.columns:
            df[target] = None

    # ── 1. Clé métier ─────────────────────────────────────────────────────────
    df["numero_sinistre"] = df["numero_sinistre"].map(_clean_text_upper)

    n_sans_cle = int(df["numero_sinistre"].isna().sum())
    if n_sans_cle:
        logger.warning(f"  Lignes sans NUMSNT (exclues) : {n_sans_cle}")
    df = df[df["numero_sinistre"].notna()].copy()

    if df.empty:
        raise RuntimeError("Toutes les lignes ont un NUMSNT NULL. Vérifiez la source.")

    n_avec_cle = len(df)

    # ── 2. Codes texte (uppercase) ────────────────────────────────────────────
    for col in ("cause_sinistre", "libelle_cause_sinistre", "code_etat"):
        if col in df.columns:
            df[col] = df[col].map(_clean_text_upper)

    # ── 3. Indicateurs binaires → OUI / NON / NON_RENSEIGNE ─────────────────
    for col in ("indicateur_forcage", "coassur", "reassur", "indicateur_transaction"):
        if col in df.columns:
            df[col] = df[col].map(_clean_indicator)
        else:
            df[col] = "NON_RENSEIGNE"

    # ── 4. cas_ida : code texte simple ───────────────────────────────────────
    if "cas_ida" in df.columns:
        df["cas_ida"] = df["cas_ida"].map(_clean_text_upper)

    # ── 5. Score de complétude pour déduplication ─────────────────────────────
    desc_cols_present = [c for c in DESCRIPTIVE_COLS if c in df.columns]
    df["_score_completude"] = df[desc_cols_present].notna().sum(axis=1)

    # ── 6. Déduplication : une ligne par numero_sinistre ─────────────────────
    # La ligne la plus complète par NUMSNT est conservée
    n_avant_dedup = len(df)
    df_sorted = df.sort_values(
        ["numero_sinistre", "_score_completude"],
        ascending=[True, False],
    )
    df_best = df_sorted.drop_duplicates(
        subset=["numero_sinistre"], keep="first"
    ).copy()
    n_dupes = n_avant_dedup - len(df_best)

    if n_dupes:
        logger.info(
            f"  Lignes multi-garanties dédupliquées : {n_dupes} "
            "(ligne la plus complète conservée)"
        )
    logger.info(f"  Sinistres distincts après dédup : {len(df_best)}")

    # ── 7. Clé technique séquentielle ─────────────────────────────────────────
    df_best = df_best.reset_index(drop=True)
    df_best.insert(0, "sinistre_sk", range(1, len(df_best) + 1))

    # ── 8. Colonnes techniques DWH ────────────────────────────────────────────
    df_best["source_system"] = SOURCE_SYSTEM
    df_best["created_at"]    = TODAY

    # ── 9. Sélection finale ───────────────────────────────────────────────────
    for col in FINAL_COLS:
        if col not in df_best.columns:
            df_best[col] = None

    # ── 10. Ligne technique UNKNOWN (sinistre_sk = 0) ────────────────────────
    # Les facts référencent sinistre_sk = 0 quand le sinistre source est
    # introuvable. Indicateurs à NON_RENSEIGNE pour rester dans le domaine.
    unknown_row = pd.DataFrame([{
        "sinistre_sk":            0,
        "numero_sinistre":        "UNKNOWN",
        "cause_sinistre":         None,
        "libelle_cause_sinistre": None,
        "code_etat":              None,
        "indicateur_forcage":     "NON_RENSEIGNE",
        "cas_ida":                None,
        "coassur":                "NON_RENSEIGNE",
        "reassur":                "NON_RENSEIGNE",
        "indicateur_transaction": "NON_RENSEIGNE",
        "source_system":          "TECHNICAL",
        "created_at":             TODAY,
    }])
    df_final = pd.concat([unknown_row[FINAL_COLS], df_best[FINAL_COLS]], ignore_index=True)
    df_final["sinistre_sk"] = df_final["sinistre_sk"].astype("int64")

    # ── Métriques ─────────────────────────────────────────────────────────────
    n_loaded = len(df_final)

    coverage: dict[str, int] = {
        col: int(df_final[col].notna().sum()) if col in df_final.columns else 0
        for col in DESCRIPTIVE_COLS
    }

    n_presque_vides = (
        int(df_final[desc_cols_present].isnull().all(axis=1).sum())
        if desc_cols_present else 0
    )

    metrics = {
        "n_raw":           n_raw,
        "n_sans_cle":      n_sans_cle,
        "n_avec_cle":      n_avec_cle,
        "n_avant_dedup":   n_avant_dedup,
        "n_dupes":         n_dupes,
        "n_loaded":        n_loaded,
        "n_presque_vides": n_presque_vides,
        "coverage":        coverage,
    }
    return df_final, metrics


# ---------------------------------------------------------------------------
# Requêtes de validation
# ---------------------------------------------------------------------------

def _print_validation_queries(logger) -> None:
    sep = "=" * 70
    logger.info(sep)
    logger.info("  REQUÊTES SQL DE VALIDATION — dwh.dim_sinistre")
    logger.info(sep)

    logger.info("""
-- 1. Colonnes finales (doit lister 13 colonnes)
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'dwh' AND table_name = 'dim_sinistre'
ORDER BY ordinal_position;
""")

    logger.info("""
-- 2. Contrôle grain — doit retourner 0 ligne
SELECT numero_sinistre, COUNT(*) AS n
FROM dwh.dim_sinistre
GROUP BY numero_sinistre
HAVING COUNT(*) > 1;
""")

    logger.info("""
-- 3. Sinistres sans numéro (doit = 0)
SELECT COUNT(*) AS n_sans_numero
FROM dwh.dim_sinistre
WHERE numero_sinistre IS NULL;
""")

    logger.info("""
-- 4. Couverture globale
SELECT
    COUNT(*)                        AS total_sinistres,
    COUNT(cause_sinistre)           AS avec_cause,
    COUNT(libelle_cause_sinistre)   AS avec_libelle_cause,
    COUNT(code_etat)                AS avec_code_etat,
    COUNT(cas_ida)                  AS avec_cas_ida,
    COUNT(motif_cloture)            AS avec_motif_cloture
FROM dwh.dim_sinistre;
""")

    logger.info("""
-- 5. Distribution code_etat
SELECT code_etat, COUNT(*) AS nb
FROM dwh.dim_sinistre
GROUP BY code_etat
ORDER BY nb DESC;
""")

    logger.info("""
-- 6. Distribution coassur / reassur
SELECT coassur, reassur, COUNT(*) AS nb
FROM dwh.dim_sinistre
GROUP BY coassur, reassur
ORDER BY nb DESC;
""")

    logger.info("""
-- 7. Distribution indicateur_transaction
SELECT indicateur_transaction, COUNT(*) AS nb
FROM dwh.dim_sinistre
GROUP BY indicateur_transaction
ORDER BY nb DESC;
""")

    logger.info("""
-- 8. Distribution cas_ida
SELECT cas_ida, COUNT(*) AS nb
FROM dwh.dim_sinistre
GROUP BY cas_ida
ORDER BY nb DESC;
""")

    logger.info("""
-- 10. Exemples (50 premières lignes)
SELECT *
FROM dwh.dim_sinistre
ORDER BY sinistre_sk
LIMIT 50;
""")

    logger.info("""
-- Note : motif_cloture a été exclu de dim_sinistre (instable au niveau NUMSNT).
-- Il sera inclus dans fact_sinistre comme attribut dégénéré au grain NUMSNT+GRNTSINI.
""")


# ---------------------------------------------------------------------------
# Chargement principal
# ---------------------------------------------------------------------------

def load_dim_sinistre(run_id: str, engine, logger) -> int:
    """
    Orchestre la lecture, la transformation et le chargement de dwh.dim_sinistre.
    Retourne le nombre de lignes chargées.
    """
    logger.info(f"[RUN {run_id}] {SOURCE_TABLE} -> dwh.{TABLE_NAME}")

    with engine.connect() as conn:
        exists = conn.execute(text("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'staging' AND table_name = 'stg_sinistres'
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

    df_final, m = transform_dim_sinistre(df_raw, logger)

    n_rows, elapsed = dwh_utils.write_to_dwh(df_final, engine, TABLE_NAME, logger)

    sep = "=" * 60
    logger.info(sep)
    logger.info(f"  lignes lues depuis staging              : {m['n_raw']}")
    logger.info(f"  sans NUMSNT (exclus)                    : {m['n_sans_cle']}")
    logger.info(f"  candidats après filtre clé              : {m['n_avec_cle']}")
    logger.info(f"  lignes avant déduplication              : {m['n_avant_dedup']}")
    logger.info(f"  doublons multi-garanties supprimés      : {m['n_dupes']}")
    logger.info(f"  sinistres distincts chargés             : {m['n_loaded']}")
    logger.info(f"  sinistres avec tous descriptifs NULL    : {m['n_presque_vides']}")
    logger.info(sep)
    logger.info("  COUVERTURE DES ATTRIBUTS :")
    for col, n in m["coverage"].items():
        pct = 100.0 * n / m["n_loaded"] if m["n_loaded"] > 0 else 0.0
        logger.info(f"    {col:<30} : {n:>7}  ({pct:5.1f}%)")
    logger.info(sep)
    logger.info(f"  durée chargement                        : {elapsed:.1f}s")
    logger.info(sep)

    _print_validation_queries(logger)

    return n_rows


# ---------------------------------------------------------------------------
# Point d'entrée autonome
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _run_id  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    _logger  = dwh_utils.setup_logging(_run_id, log_name="load_dim_sinistre")
    _engine  = dwh_utils.build_engine(_logger)
    dwh_utils.create_dwh_schema(_engine, _logger)
    _n = load_dim_sinistre(_run_id, _engine, _logger)
    _logger.info(f"Terminé : {_n} lignes -> dwh.{TABLE_NAME}")
