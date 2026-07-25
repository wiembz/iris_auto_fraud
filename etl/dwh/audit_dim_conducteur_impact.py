"""
etl/dwh/audit_dim_conducteur_impact.py
=======================================
Rapport d'impact REPRODUCTIBLE (lecture seule, aucune écriture en base) pour le
correctif de dim_conducteur (cf. load_dim_conducteur.py, filtre "identité faible").

Compare deux scénarios calculés à partir de staging.stg_sinistres :
  - AVANT  : comportement historique (seule une ligne totalement vide était exclue)
  - APRES  : comportement corrigé (exclusion des numero_permis de repli, cf.
             WEAK_PERMIS_ABNORMAL_USE_THRESHOLD et _PERMIS_PLACEHOLDER_LITERALS)

Sorties (data/quality_reports/dim_conducteur/) :
  - dim_conducteur_permis_seul_distribution_<ts>.csv : distribution complète des
    numero_permis parmi les lignes "identité faible" (nom/dob/date_permis NULL),
    avec indicateur is_suspect.
  - dim_conducteur_valeurs_suspectes_<ts>.csv : liste des valeurs traitées comme
    non-identifiantes (littéraux fictifs + valeurs sur-utilisées), avec occurrences.
  - dim_conducteur_impact_summary_<ts>.md : métriques avant/après + impact sur
    fact_sinistre + dossiers actuellement aberrants + cas de référence.

Usage :
  python etl/dwh/audit_dim_conducteur_impact.py [--claim-numero G26511000017765 --code-garantie REM]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwh_utils
from load_dim_conducteur import (
    _PERMIS_PLACEHOLDER_LITERALS,
    WEAK_PERMIS_ABNORMAL_USE_THRESHOLD,
    _clean_str,
    _read_staging,
    transform_dim_conducteur,
)

REPORT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "quality_reports" / "dim_conducteur"


def _baseline_metrics(df_raw: pd.DataFrame, logger) -> dict:
    """Reproduit le comportement AVANT correctif : seules les lignes totalement
    vides (5 champs NULL) sont exclues ; aucune détection de valeur de repli."""
    df = df_raw.copy()
    df["nom_conducteur"] = df.get("nomconduc").map(_clean_str) if "nomconduc" in df.columns else None
    df["numero_permis"] = df.get("numpermis").map(_clean_str) if "numpermis" in df.columns else None
    df["categorie_permis"] = df.get("categperm").map(_clean_str) if "categperm" in df.columns else None
    df["date_naissance_conducteur"] = pd.to_datetime(df.get("datnaicon"), errors="coerce")
    df["date_permis"] = pd.to_datetime(df.get("datepermi"), errors="coerce")

    data_cols = ["nom_conducteur", "date_naissance_conducteur",
                 "numero_permis", "categorie_permis", "date_permis"]
    mask_vide = df[data_cols].isnull().all(axis=1)
    df_candidates = df[~mask_vide]
    dedup_key = ["nom_conducteur", "date_naissance_conducteur",
                 "numero_permis", "categorie_permis", "date_permis"]
    n_real = df_candidates.drop_duplicates(subset=dedup_key).shape[0]
    return {
        "n_vides": int(mask_vide.sum()),
        "n_candidates": int((~mask_vide).sum()),
        "n_real_conducteur": int(n_real),
        "n_total_with_unknown": int(n_real) + 1,
    }


def _weak_identity_distribution(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Distribution des numero_permis parmi les lignes identité faible
    (nom/dob/date_permis tous NULL, numero_permis renseigné)."""
    df = df_raw.copy()
    nom = df.get("nomconduc").map(_clean_str) if "nomconduc" in df.columns else pd.Series([None] * len(df))
    permis = df.get("numpermis").map(_clean_str) if "numpermis" in df.columns else pd.Series([None] * len(df))
    dob = pd.to_datetime(df.get("datnaicon"), errors="coerce")
    date_permis = pd.to_datetime(df.get("datepermi"), errors="coerce")

    mask_weak = nom.isnull() & dob.isna() & date_permis.isna() & permis.notnull()
    counts = permis[mask_weak].value_counts()
    dist = counts.reset_index()
    dist.columns = ["numero_permis", "n_occurrences"]
    dist["is_suspect"] = (
        (dist["n_occurrences"] > WEAK_PERMIS_ABNORMAL_USE_THRESHOLD)
        | dist["numero_permis"].isin(_PERMIS_PLACEHOLDER_LITERALS)
    )
    return dist.sort_values("n_occurrences", ascending=False).reset_index(drop=True)


def _reference_dossier_impact(engine, numero_sinistre: str, code_garantie: str) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT fs.fact_sinistre_sk AS claim_sk, fs.numero_sinistre, fs.code_garantie,
                   fs.conducteur_sk, dc.numero_permis, dc.nom_conducteur
            FROM dwh.fact_sinistre fs
            LEFT JOIN dwh.dim_conducteur dc ON dc.conducteur_sk = fs.conducteur_sk
            WHERE fs.numero_sinistre = :n AND fs.code_garantie = :g
        """), {"n": numero_sinistre, "g": code_garantie}).fetchone()
    if row is None:
        return None
    return dict(row._mapping)


def _aberrant_dossiers_count(engine, threshold: int = 100) -> int | None:
    with engine.connect() as conn:
        exists = conn.execute(text("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'mart' AND table_name = 'fact_claim_business_rule_signal'
        """)).fetchone()
        if not exists:
            return None
        latest_run = conn.execute(text("""
            SELECT signal_run_id FROM mart.fact_claim_business_rule_signal
            GROUP BY signal_run_id ORDER BY MAX(created_at) DESC LIMIT 1
        """)).fetchone()
        if not latest_run:
            return None
        count = conn.execute(text("""
            SELECT COUNT(*) FROM mart.fact_claim_business_rule_signal
            WHERE signal_run_id = :r AND rule_code = 'DRIVER_CLAIMS_12M_HIGH'
              AND rule_observed_value::float > :t
        """), {"r": latest_run[0], "t": threshold}).fetchone()
        return int(count[0])


def _fantom_bucket_impact(engine, suspect_values: list[str]) -> dict:
    """Lignes fact_sinistre actuellement rattachées à un conducteur_sk dont le
    numero_permis est une valeur SUSPECTE (repli), pas simplement "identité faible" :
    un numero_permis rare et plausible reste une identité valide, il ne doit pas
    être compté comme fantôme."""
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT COUNT(*) AS nb_sinistres_impactes,
                   COUNT(DISTINCT dc.conducteur_sk) AS nb_conducteur_sk_fantomes
            FROM dwh.fact_sinistre fs
            JOIN dwh.dim_conducteur dc ON dc.conducteur_sk = fs.conducteur_sk
            WHERE dc.nom_conducteur IS NULL
              AND dc.date_naissance_conducteur IS NULL
              AND dc.date_permis IS NULL
              AND dc.conducteur_sk <> 0
              AND dc.numero_permis = ANY(:suspects)
        """), {"suspects": list(suspect_values)}).fetchone()
        sk0 = conn.execute(text("SELECT COUNT(*) FROM dwh.fact_sinistre WHERE conducteur_sk = 0")).fetchone()
        total = conn.execute(text("SELECT COUNT(*) FROM dwh.fact_sinistre")).fetchone()
    return {
        "nb_sinistres_impactes": int(row[0]),
        "nb_conducteur_sk_fantomes": int(row[1]),
        "sk0_actuel": int(sk0[0]),
        "total_fact_sinistre": int(total[0]),
    }


def run_audit(claim_numero: str | None, code_garantie: str | None) -> dict:
    logger = dwh_utils.setup_logging(
        datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        log_name="audit_dim_conducteur_impact",
    )
    engine = dwh_utils.build_engine(logger)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    df_raw = _read_staging(engine, logger)

    baseline = _baseline_metrics(df_raw, logger)
    df_final, after_metrics = transform_dim_conducteur(df_raw, logger)

    distribution = _weak_identity_distribution(df_raw)
    distribution_path = REPORT_DIR / f"dim_conducteur_permis_seul_distribution_{ts}.csv"
    distribution.to_csv(distribution_path, index=False)

    suspects = distribution[distribution["is_suspect"]].reset_index(drop=True)
    suspects_path = REPORT_DIR / f"dim_conducteur_valeurs_suspectes_{ts}.csv"
    suspects.to_csv(suspects_path, index=False)

    fantom_impact = _fantom_bucket_impact(engine, suspects["numero_permis"].tolist())
    aberrant_count = _aberrant_dossiers_count(engine)
    reference = None
    if claim_numero and code_garantie:
        reference = _reference_dossier_impact(engine, claim_numero, code_garantie)

    summary_path = REPORT_DIR / f"dim_conducteur_impact_summary_{ts}.md"
    lines = [
        f"# Rapport d'impact dim_conducteur — {ts}",
        "",
        f"Seuil utilisé (WEAK_PERMIS_ABNORMAL_USE_THRESHOLD) : {WEAK_PERMIS_ABNORMAL_USE_THRESHOLD}",
        f"Littéraux placeholder : {sorted(_PERMIS_PLACEHOLDER_LITERALS)}",
        "",
        "## Métriques avant / après",
        "",
        "| Métrique | Avant (comportement historique) | Après (correctif) |",
        "|---|---|---|",
        f"| Lignes staging lues | {after_metrics['n_raw']} | {after_metrics['n_raw']} |",
        f"| Lignes totalement vides exclues | {baseline['n_vides']} | {after_metrics['n_vides']} |",
        f"| Lignes candidates conducteur | {baseline['n_candidates']} | {after_metrics['n_candidates']} |",
        f"| Lignes identité faible exclues | 0 | {after_metrics['n_identite_faible']} |",
        f"| Lignes permis-seul conservées (rares) | — | {after_metrics['n_permis_seul_garde']} |",
        f"| Conducteurs réels distincts | {baseline['n_real_conducteur']} | {after_metrics['n_real_conducteur']} |",
        f"| Total avec UNKNOWN | {baseline['n_total_with_unknown']} | {after_metrics['n_total_with_unknown']} |",
        "",
        "## Distribution des permis seuls",
        "",
        f"- Valeurs distinctes observées : {len(distribution)}",
        f"- Valeurs suspectes (traitées comme repli) : {len(suspects)}",
        f"- Lignes concernées par une valeur suspecte : {int(suspects['n_occurrences'].sum())}",
        f"- Détail complet : `{distribution_path.name}`",
        f"- Valeurs suspectes seules : `{suspects_path.name}`",
        "",
        "## Impact sur dwh.fact_sinistre (état actuel de la base, avant recalcul)",
        "",
        f"- `conducteur_sk` fantômes actuellement en base : {fantom_impact['nb_conducteur_sk_fantomes']}",
        f"- Lignes fact_sinistre qui basculeront vers UNKNOWN (sk=0) : {fantom_impact['nb_sinistres_impactes']}",
        f"- `conducteur_sk=0` actuel : {fantom_impact['sk0_actuel']} / {fantom_impact['total_fact_sinistre']}"
        f" ({100 * fantom_impact['sk0_actuel'] / fantom_impact['total_fact_sinistre']:.2f}%)",
        f"- `conducteur_sk=0` estimé après correctif : "
        f"{fantom_impact['sk0_actuel'] + fantom_impact['nb_sinistres_impactes']} / {fantom_impact['total_fact_sinistre']}"
        f" ({100 * (fantom_impact['sk0_actuel'] + fantom_impact['nb_sinistres_impactes']) / fantom_impact['total_fact_sinistre']:.2f}%)",
        "",
    ]
    if aberrant_count is not None:
        lines += [
            "## Dossiers actuellement aberrants (dernier run de scoring)",
            "",
            f"- Dossiers avec `driver_claim_count_12m > 100` : {aberrant_count}",
            "",
        ]
    if reference is not None:
        lines += [
            f"## Dossier de référence {claim_numero}|{code_garantie}",
            "",
            f"- claim_sk : {reference['claim_sk']}",
            f"- conducteur_sk actuel : {reference['conducteur_sk']}",
            f"- numero_permis : {reference['numero_permis']}",
            f"- nom_conducteur : {reference['nom_conducteur']}",
            "",
        ]
    summary_path.write_text("\n".join(lines), encoding="utf-8")

    logger.info(f"Rapport écrit : {summary_path}")
    engine.dispose()
    return {
        "summary_path": str(summary_path),
        "distribution_path": str(distribution_path),
        "suspects_path": str(suspects_path),
        "baseline": baseline,
        "after": after_metrics,
        "fantom_impact": fantom_impact,
        "aberrant_count": aberrant_count,
        "reference": reference,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claim-numero", default="G26511000017765")
    parser.add_argument("--code-garantie", default="REM")
    args = parser.parse_args()
    result = run_audit(args.claim_numero, args.code_garantie)
    print(result["summary_path"])
