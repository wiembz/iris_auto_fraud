"""
etl/mart/prune_stale_scoring_runs.py
======================================
Supprime les runs de scoring perimes des tables mart, en ne conservant que le
run le plus recent par version. Les tables mart sont recalculees integralement
a chaque execution (pas d'etat incremental) : un run remplace par un plus
recent n'a aucune valeur analytique. Sans purge, ils s'accumulent a chaque
recalcul et degradent les performances de l'API (scans sequentiels sur des
tables 5 a 10x plus grosses que necessaire).

NE TOUCHE JAMAIS app.claim_review_decision (audit trail des decisions
humaines, immuable par design, sans rapport avec les runs de scoring).

Usage :
  python etl/mart/prune_stale_scoring_runs.py            # applique la purge
  python etl/mart/prune_stale_scoring_runs.py --dry-run  # rapporte seulement
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from etl.utils.runtime import build_engine

# (table, version_column, run_column)
VERSIONED_TABLES = [
    ("fact_claim_scoring_features", "scoring_feature_version", "feature_run_id"),
    ("fact_claim_business_rule_signal", "signal_version", "signal_run_id"),
    ("fact_claim_ml_anomaly_signal", "signal_version", "signal_run_id"),
    ("fact_post_inspection_attention_signal", "signal_version", "signal_run_id"),
    ("fact_claim_attention_score", "score_version", "score_run_id"),
    ("fact_claim_attention_signal_detail", "score_version", "score_run_id"),
]


def prune_stale_scoring_runs(dry_run: bool = False) -> dict[str, int]:
    engine = build_engine()
    deleted: dict[str, int] = {}

    with engine.begin() as conn:
        for table, version_col, run_col in VERSIONED_TABLES:
            keep_runs = conn.execute(
                text(
                    f"""
                    SELECT DISTINCT ON ({version_col}) {version_col}, {run_col}
                    FROM mart.{table}
                    ORDER BY {version_col}, created_at DESC, {run_col} DESC
                    """
                )
            ).fetchall()

            if not keep_runs:
                deleted[table] = 0
                continue

            if dry_run:
                before = conn.execute(text(f"SELECT COUNT(*) FROM mart.{table}")).scalar()
                would_keep = 0
                for version, run_id in keep_runs:
                    would_keep += conn.execute(
                        text(f"SELECT COUNT(*) FROM mart.{table} WHERE {version_col} = :v AND {run_col} = :r"),
                        {"v": version, "r": run_id},
                    ).scalar()
                deleted[table] = before - would_keep
                continue

            keep_clause = " OR ".join(
                f"({version_col} = :v{i} AND {run_col} = :r{i})" for i in range(len(keep_runs))
            )
            params = {}
            for i, (version, run_id) in enumerate(keep_runs):
                params[f"v{i}"] = version
                params[f"r{i}"] = run_id

            result = conn.execute(
                text(f"DELETE FROM mart.{table} WHERE NOT ({keep_clause})"),
                params,
            )
            deleted[table] = result.rowcount

    return deleted


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    deleted = prune_stale_scoring_runs(dry_run=dry_run)
    label = "seraient supprimees" if dry_run else "supprimees"
    print(f"{'[DRY RUN] ' if dry_run else ''}Lignes {label} (runs perimes) :")
    for table, n in deleted.items():
        print(f"  mart.{table:<45} {n:>10}")


if __name__ == "__main__":
    main()
