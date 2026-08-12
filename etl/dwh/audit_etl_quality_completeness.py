"""
Read-only ETL completeness and quality audit.

The audit checks loaded staging/DWH tables without modifying the database:
row counts, primary key quality, duplicate business keys, foreign-key coverage,
technical UNKNOWN rows (sk = 0), and business completeness indicators.

Audit trail (data/quality_reports/etl_quality):
  runs/<run_ts>/*.csv + manifest.json  — immutable trace per run
                                         (retention: IRIS_AUDIT_RUN_RETENTION,
                                         default 10 runs)
  latest/*.csv + manifest.json         — stable paths, always the last run

Exit code: 0 if no FAIL finding (WARNs allowed), 1 otherwise — usable as a
CI / orchestration quality gate (final step of load_all_dwh.py).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

DWH_DIR = Path(__file__).resolve().parent
BASE_DIR = DWH_DIR.parent.parent
sys.path.insert(0, str(DWH_DIR))

import dwh_utils


REPORT_DIR = BASE_DIR / "data" / "quality_reports" / "etl_quality"


def _read_sql(engine, query: str, params: dict | None = None) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql_query(text(query), conn, params=params or {})


def _table_exists(engine, schema: str, table: str) -> bool:
    df = _read_sql(
        engine,
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = :schema
          AND table_name = :table
        """,
        {"schema": schema, "table": table},
    )
    return not df.empty


def _columns(engine, schema: str, table: str) -> list[str]:
    df = _read_sql(
        engine,
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = :schema
          AND table_name = :table
        ORDER BY ordinal_position
        """,
        {"schema": schema, "table": table},
    )
    return df["column_name"].tolist()


def _count_table(engine, schema: str, table: str) -> int | None:
    if not _table_exists(engine, schema, table):
        return None
    df = _read_sql(engine, f'SELECT COUNT(*) AS n FROM "{schema}"."{table}"')
    return int(df.loc[0, "n"])


def _table_counts(engine) -> pd.DataFrame:
    expected = [
        ("staging", "stg_production"),
        ("staging", "stg_sinistres"),
        ("staging", "stg_clients"),
        ("staging", "stg_inspection"),
        ("dwh", "dim_date"),
        ("dwh", "dim_client"),
        ("dwh", "dim_contrat"),
        ("dwh", "dim_garantie"),
        ("dwh", "dim_geo"),
        ("dwh", "dim_vehicule"),
        ("dwh", "dim_conducteur"),
        ("dwh", "dim_tiers"),
        ("dwh", "dim_camtier"),
        ("dwh", "dim_intermediaire"),
        ("dwh", "dim_produit"),
        ("dwh", "dim_sinistre"),
        ("dwh", "fact_sinistre"),
        ("dwh", "fact_contrat"),
        ("dwh", "fact_inspection_vehicule"),
        ("dwh", "fact_inspection_checkpoint"),
    ]
    rows = []
    for schema, table in expected:
        n = _count_table(engine, schema, table)
        rows.append(
            {
                "schema": schema,
                "table": table,
                "exists": n is not None,
                "row_count": n if n is not None else 0,
                "severity": "FAIL" if n == 0 or n is None else "OK",
            }
        )
    return pd.DataFrame(rows)


def _key_quality(engine) -> pd.DataFrame:
    key_specs = [
        ("dwh", "dim_client", "client_sk"),
        ("dwh", "dim_contrat", "contrat_sk"),
        ("dwh", "dim_garantie", "garantie_sk"),
        ("dwh", "dim_geo", "geo_sk"),
        ("dwh", "dim_vehicule", "vehicule_sk"),
        ("dwh", "dim_conducteur", "conducteur_sk"),
        ("dwh", "dim_tiers", "tiers_sk"),
        ("dwh", "dim_camtier", "camtier_sk"),
        ("dwh", "dim_intermediaire", "intermediaire_sk"),
        ("dwh", "dim_produit", "produit_sk"),
        ("dwh", "dim_sinistre", "sinistre_sk"),
        ("dwh", "fact_sinistre", "fact_sinistre_sk"),
        ("dwh", "fact_contrat", "fact_contrat_sk"),
        ("dwh", "fact_inspection_vehicule", "fact_inspection_vehicule_sk"),
        ("dwh", "fact_inspection_checkpoint", "fact_inspection_checkpoint_sk"),
    ]
    rows = []
    for schema, table, key in key_specs:
        if not _table_exists(engine, schema, table) or key not in _columns(engine, schema, table):
            rows.append(
                {
                    "table": f"{schema}.{table}",
                    "key_column": key,
                    "row_count": 0,
                    "distinct_keys": 0,
                    "null_keys": None,
                    "duplicate_key_rows": None,
                    "zero_key_rows": None,
                    "severity": "FAIL",
                    "issue": "table_or_key_missing",
                }
            )
            continue
        df = _read_sql(
            engine,
            f"""
            SELECT COUNT(*) AS row_count,
                   COUNT(DISTINCT {key}) AS distinct_keys,
                   COUNT(*) FILTER (WHERE {key} IS NULL) AS null_keys,
                   COUNT(*) FILTER (WHERE {key} = 0) AS zero_key_rows
            FROM "{schema}"."{table}"
            """,
        )
        row_count = int(df.loc[0, "row_count"])
        distinct_keys = int(df.loc[0, "distinct_keys"])
        null_keys = int(df.loc[0, "null_keys"])
        zero_key_rows = int(df.loc[0, "zero_key_rows"])
        duplicate_key_rows = max(row_count - distinct_keys, 0)
        severity = "OK"
        issue = ""
        if null_keys:
            severity = "FAIL"
            issue = "null_surrogate_key"
        elif duplicate_key_rows:
            severity = "FAIL"
            issue = "duplicate_surrogate_key"
        rows.append(
            {
                "table": f"{schema}.{table}",
                "key_column": key,
                "row_count": row_count,
                "distinct_keys": distinct_keys,
                "null_keys": null_keys,
                "duplicate_key_rows": duplicate_key_rows,
                "zero_key_rows": zero_key_rows,
                "severity": severity,
                "issue": issue,
            }
        )
    return pd.DataFrame(rows)


def _business_key_quality(engine) -> pd.DataFrame:
    specs = [
        ("dwh", "dim_client", "idclt"),
        ("dwh", "dim_contrat", "contrat_key"),
        ("dwh", "dim_garantie", "garantie_key"),
        ("dwh", "dim_geo", "geo_key"),
        ("dwh", "dim_vehicule", "immatriculation"),
        ("dwh", "dim_sinistre", "numero_sinistre"),
        ("dwh", "dim_camtier", "code_camtier"),
        ("dwh", "dim_produit", "code_produit"),
        ("dwh", "dim_intermediaire", "code_intermediaire"),
        ("dwh", "fact_sinistre", "sinistre_garantie_key"),
        ("dwh", "fact_contrat", "contrat_mouvement_key"),
        ("dwh", "fact_inspection_vehicule", "inspection_key"),
        ("dwh", "fact_inspection_checkpoint", "inspection_checkpoint_key"),
    ]
    rows = []
    for schema, table, key in specs:
        if not _table_exists(engine, schema, table) or key not in _columns(engine, schema, table):
            # Une clé métier attendue mais absente est un défaut d'audit, pas
            # un cas à ignorer silencieusement.
            rows.append(
                {
                    "table": f"{schema}.{table}",
                    "business_key": key,
                    "row_count": 0,
                    "distinct_business_keys": 0,
                    "missing_business_keys": None,
                    "duplicate_business_key_rows": None,
                    "severity": "FAIL",
                    "issue": "table_or_business_key_missing",
                }
            )
            continue
        df = _read_sql(
            engine,
            f"""
            SELECT COUNT(*) AS row_count,
                   COUNT(DISTINCT {key}) AS distinct_business_keys,
                   COUNT(*) FILTER (WHERE {key} IS NULL OR TRIM(CAST({key} AS TEXT)) = '') AS missing_business_keys
            FROM "{schema}"."{table}"
            """,
        )
        row_count = int(df.loc[0, "row_count"])
        distinct_keys = int(df.loc[0, "distinct_business_keys"])
        missing = int(df.loc[0, "missing_business_keys"])
        duplicates = max(row_count - distinct_keys, 0)
        severity = "OK"
        issue = ""
        if missing:
            severity = "FAIL"
            issue = "missing_business_key"
        elif duplicates:
            severity = "FAIL"
            issue = "duplicate_business_key"
        rows.append(
            {
                "table": f"{schema}.{table}",
                "business_key": key,
                "row_count": row_count,
                "distinct_business_keys": distinct_keys,
                "missing_business_keys": missing,
                "duplicate_business_key_rows": duplicates,
                "severity": severity,
                "issue": issue,
            }
        )
    return pd.DataFrame(rows)


def _fk_coverage(engine) -> pd.DataFrame:
    # (fact, fk, dim, dim_key, zero_expected)
    # zero_expected=True : le sk=0 est structurellement normal pour ce FK
    # (événement pas encore survenu, ou absence source documentée) — le taux
    # d'UNKNOWN élevé n'y est pas une anomalie. Les contrôles d'intégrité
    # (orphelins, zero sans ligne dimension) restent bloquants dans tous les cas.
    specs = [
        ("dwh.fact_sinistre", "sinistre_sk", "dwh.dim_sinistre", "sinistre_sk", False),
        ("dwh.fact_sinistre", "garantie_sk", "dwh.dim_garantie", "garantie_sk", False),
        ("dwh.fact_sinistre", "client_sk", "dwh.dim_client", "client_sk", False),
        ("dwh.fact_sinistre", "contrat_sk", "dwh.dim_contrat", "contrat_sk", False),
        ("dwh.fact_sinistre", "vehicule_sk", "dwh.dim_vehicule", "vehicule_sk", False),
        ("dwh.fact_sinistre", "conducteur_sk", "dwh.dim_conducteur", "conducteur_sk", False),
        # tiers/camtier : ~27-31% de sinistres sans tiers exploitable — absence
        # source validée lors de la clôture de dim_tiers, pas un défaut ETL.
        ("dwh.fact_sinistre", "tiers_sk", "dwh.dim_tiers", "tiers_sk", True),
        ("dwh.fact_sinistre", "camtier_sk", "dwh.dim_camtier", "camtier_sk", True),
        ("dwh.fact_sinistre", "geo_sinistre_sk", "dwh.dim_geo", "geo_sk", False),
        ("dwh.fact_sinistre", "date_survenance_sk", "dwh.dim_date", "date_sk", False),
        ("dwh.fact_sinistre", "date_declaration_sk", "dwh.dim_date", "date_sk", False),
        ("dwh.fact_sinistre", "date_ouverture_sk", "dwh.dim_date", "date_sk", False),
        # date_cloture = 0 pour les sinistres encore ouverts.
        ("dwh.fact_sinistre", "date_cloture_sk", "dwh.dim_date", "date_sk", True),
        ("dwh.fact_contrat", "client_sk", "dwh.dim_client", "client_sk", False),
        ("dwh.fact_contrat", "contrat_sk", "dwh.dim_contrat", "contrat_sk", False),
        ("dwh.fact_contrat", "produit_sk", "dwh.dim_produit", "produit_sk", False),
        ("dwh.fact_contrat", "intermediaire_sk", "dwh.dim_intermediaire", "intermediaire_sk", False),
        ("dwh.fact_contrat", "date_debut_contrat_sk", "dwh.dim_date", "date_sk", False),
        # dates d'événements optionnels (contrat pas encore fini/résilié…)
        ("dwh.fact_contrat", "date_fin_contrat_sk", "dwh.dim_date", "date_sk", True),
        ("dwh.fact_contrat", "date_debut_effet_sk", "dwh.dim_date", "date_sk", False),
        ("dwh.fact_contrat", "date_fin_effet_sk", "dwh.dim_date", "date_sk", True),
        ("dwh.fact_contrat", "date_derniere_operation_sk", "dwh.dim_date", "date_sk", True),
        ("dwh.fact_contrat", "date_resiliation_sk", "dwh.dim_date", "date_sk", True),
        ("dwh.fact_inspection_vehicule", "vehicule_sk", "dwh.dim_vehicule", "vehicule_sk", False),
        ("dwh.fact_inspection_vehicule", "date_inspection_sk", "dwh.dim_date", "date_sk", False),
        ("dwh.fact_inspection_checkpoint", "vehicule_sk", "dwh.dim_vehicule", "vehicule_sk", False),
        ("dwh.fact_inspection_checkpoint", "date_inspection_sk", "dwh.dim_date", "date_sk", False),
    ]
    rows = []
    for fact, fk, dim, dim_key, zero_expected in specs:
        f_schema, f_table = fact.split(".")
        d_schema, d_table = dim.split(".")
        if not _table_exists(engine, f_schema, f_table) or not _table_exists(engine, d_schema, d_table):
            continue
        f_cols = _columns(engine, f_schema, f_table)
        d_cols = _columns(engine, d_schema, d_table)
        if fk not in f_cols or dim_key not in d_cols:
            rows.append(
                {
                    "fact_table": fact,
                    "fk_column": fk,
                    "dim_table": dim,
                    "fact_rows": 0,
                    "severity": "FAIL",
                    "issue": "fk_or_dim_key_column_missing",
                }
            )
            continue
        df = _read_sql(
            engine,
            f"""
            SELECT COUNT(*) AS fact_rows,
                   COUNT(*) FILTER (WHERE f.{fk} IS NULL) AS null_fk_rows,
                   COUNT(*) FILTER (WHERE f.{fk} = 0) AS technical_zero_rows,
                   COUNT(*) FILTER (WHERE f.{fk} = 0 AND d.{dim_key} IS NULL) AS technical_zero_without_dim_row,
                   COUNT(*) FILTER (WHERE f.{fk} IS NOT NULL AND f.{fk} <> 0 AND d.{dim_key} IS NULL) AS nonzero_orphan_fk_rows
            FROM {fact} f
            LEFT JOIN {dim} d
              ON f.{fk} = d.{dim_key}
            """,
        )
        fact_rows = int(df.loc[0, "fact_rows"])
        null_fk = int(df.loc[0, "null_fk_rows"])
        zero_fk = int(df.loc[0, "technical_zero_rows"])
        zero_without_dim = int(df.loc[0, "technical_zero_without_dim_row"])
        nonzero_orphan = int(df.loc[0, "nonzero_orphan_fk_rows"])
        unknown = null_fk + zero_fk
        unknown_rate = round(unknown / fact_rows, 6) if fact_rows else None
        nonzero_orphan_rate = round(nonzero_orphan / fact_rows, 6) if fact_rows else None
        severity = "OK"
        issue = ""
        if nonzero_orphan:
            severity = "FAIL"
            issue = "nonzero_orphan_fk"
        elif zero_without_dim:
            severity = "FAIL"
            issue = "technical_zero_without_dimension_row"
        elif null_fk:
            severity = "FAIL"
            issue = "null_fk_rows"
        elif fact_rows and unknown_rate is not None and unknown_rate >= 0.20:
            if zero_expected:
                issue = "expected_unknown_rate_documented"
            else:
                severity = "WARN"
                issue = "high_unknown_fk_rate"
        rows.append(
            {
                "fact_table": fact,
                "fk_column": fk,
                "dim_table": dim,
                "fact_rows": fact_rows,
                "null_fk_rows": null_fk,
                "technical_zero_rows": zero_fk,
                "technical_zero_without_dim_row": zero_without_dim,
                "nonzero_orphan_fk_rows": nonzero_orphan,
                "unknown_fk_rate": unknown_rate,
                "nonzero_orphan_fk_rate": nonzero_orphan_rate,
                "zero_expected": zero_expected,
                "severity": severity,
                "issue": issue,
            }
        )
    return pd.DataFrame(rows)


def _technical_unknown_rows(engine) -> pd.DataFrame:
    """Chaque dimension référencée par un fact doit avoir exactement une
    ligne technique UNKNOWN (sk = 0), créée par son loader."""
    specs = [
        ("dwh", "dim_client", "client_sk"),
        ("dwh", "dim_contrat", "contrat_sk"),
        ("dwh", "dim_garantie", "garantie_sk"),
        ("dwh", "dim_geo", "geo_sk"),
        ("dwh", "dim_vehicule", "vehicule_sk"),
        ("dwh", "dim_conducteur", "conducteur_sk"),
        ("dwh", "dim_tiers", "tiers_sk"),
        ("dwh", "dim_camtier", "camtier_sk"),
        ("dwh", "dim_intermediaire", "intermediaire_sk"),
        ("dwh", "dim_produit", "produit_sk"),
        ("dwh", "dim_sinistre", "sinistre_sk"),
        ("dwh", "dim_date", "date_sk"),
    ]
    rows = []
    for schema, table, key in specs:
        if not _table_exists(engine, schema, table):
            rows.append(
                {
                    "table": f"{schema}.{table}",
                    "key_column": key,
                    "unknown_rows": None,
                    "severity": "FAIL",
                    "issue": "table_missing",
                }
            )
            continue
        n = int(
            _read_sql(
                engine,
                f'SELECT COUNT(*) AS n FROM "{schema}"."{table}" WHERE {key} = 0',
            ).loc[0, "n"]
        )
        severity = "OK" if n == 1 else "FAIL"
        issue = "" if n == 1 else ("missing_unknown_row" if n == 0 else "duplicate_unknown_row")
        rows.append(
            {
                "table": f"{schema}.{table}",
                "key_column": key,
                "unknown_rows": n,
                "severity": severity,
                "issue": issue,
            }
        )
    return pd.DataFrame(rows)


def _critical_completeness(engine) -> pd.DataFrame:
    checks = [
        (
            "stg_sinistres_to_fact_sinistre_rows",
            "staging.stg_sinistres",
            "dwh.fact_sinistre",
        ),
        (
            "stg_inspection_to_fact_inspection_vehicule_rows",
            "staging.stg_inspection",
            "dwh.fact_inspection_vehicule",
        ),
    ]
    rows = []
    for name, source, target in checks:
        s_schema, s_table = source.split(".")
        t_schema, t_table = target.split(".")
        source_count = _count_table(engine, s_schema, s_table)
        target_count = _count_table(engine, t_schema, t_table)
        if source_count is None or target_count is None:
            severity = "FAIL"
            diff = None
            ratio = None
        else:
            diff = target_count - source_count
            ratio = round(target_count / source_count, 6) if source_count else None
            severity = "OK" if diff == 0 else "WARN"
        rows.append(
            {
                "check_name": name,
                "source_table": source,
                "source_rows": source_count,
                "target_table": target,
                "target_rows": target_count,
                "row_diff": diff,
                "target_source_ratio": ratio,
                "severity": severity,
            }
        )
    return pd.DataFrame(rows)


def _domain_quality(engine) -> pd.DataFrame:
    checks: list[dict] = []

    if _table_exists(engine, "dwh", "dim_geo"):
        df = _read_sql(
            engine,
            """
            SELECT geo_quality_level, needs_review, COUNT(*) AS rows
            FROM dwh.dim_geo
            GROUP BY 1,2
            ORDER BY rows DESC
            """,
        )
        for _, row in df.iterrows():
            severity = "OK"
            if row["geo_quality_level"] in {"CONFLICT", "AMBIGUOUS"}:
                severity = "FAIL"
            elif row["geo_quality_level"] == "PARTIAL":
                severity = "WARN"
            checks.append(
                {
                    "domain": "geo",
                    "metric": f"dim_geo_quality_{row['geo_quality_level']}_{row['needs_review']}",
                    "value": int(row["rows"]),
                    "severity": severity,
                }
            )

    if _table_exists(engine, "dwh", "dim_vehicule"):
        df = _read_sql(
            engine,
            """
            SELECT source_system,
                   COUNT(*) AS rows,
                   COUNT(*) FILTER (WHERE vin IS NOT NULL AND TRIM(vin) <> '') AS with_vin,
                   COUNT(*) FILTER (WHERE motorisation IS NOT NULL AND TRIM(motorisation) <> '') AS with_motorisation
            FROM dwh.dim_vehicule
            GROUP BY source_system
            ORDER BY source_system
            """,
        )
        for _, row in df.iterrows():
            source = row["source_system"]
            rows_count = int(row["rows"])
            motor = int(row["with_motorisation"])
            severity = "OK"
            if "STAFIM" in str(source) and motor == 0 and rows_count > 0:
                severity = "FAIL"
            checks.append(
                {
                    "domain": "vehicle",
                    "metric": f"dim_vehicule_{source}_with_motorisation",
                    "value": motor,
                    "denominator": rows_count,
                    "severity": severity,
                }
            )

    if _table_exists(engine, "dwh", "fact_sinistre"):
        cols = set(_columns(engine, "dwh", "fact_sinistre"))
        total = int(_read_sql(engine, "SELECT COUNT(*) AS rows FROM dwh.fact_sinistre").loc[0, "rows"])

        amount_cols = [
            "montant_evaluation",
            "montant_reglement",
            "montant_reserve",
            "montant_recours",
            "montant_charge_sinistre",
        ]
        for col in amount_cols:
            if col not in cols:
                continue
            df = _read_sql(
                engine,
                f"""
                SELECT COUNT(*) FILTER (WHERE {col} IS NULL) AS null_rows,
                       COUNT(*) FILTER (WHERE {col} < 0) AS negative_rows
                FROM dwh.fact_sinistre
                """,
            )
            for metric in ["null_rows", "negative_rows"]:
                value = int(df.loc[0, metric])
                checks.append(
                    {
                        "domain": "claim",
                        "metric": f"fact_sinistre_{col}_{metric}",
                        "value": value,
                        "denominator": total,
                        "severity": "WARN" if value else "OK",
                    }
                )

        for col in ["date_survenance_sk", "date_declaration_sk", "date_ouverture_sk"]:
            if col not in cols:
                continue
            value = int(
                _read_sql(
                    engine,
                    f"""
                    SELECT COUNT(*) FILTER (WHERE {col} IS NULL OR {col} = 0) AS missing_rows
                    FROM dwh.fact_sinistre
                    """,
                ).loc[0, "missing_rows"]
            )
            checks.append(
                {
                    "domain": "claim",
                    "metric": f"fact_sinistre_{col}_missing",
                    "value": value,
                    "denominator": total,
                    "severity": "WARN" if value else "OK",
                }
            )

    # Chronologie des dates (les SK YYYYMMDD se comparent numériquement ;
    # 0 = date absente, exclue de la comparaison). Une inversion massive ici
    # a déjà signalé un bug de parsing jour/mois — seuil WARN à 0.1%.
    chronology_specs = [
        ("dwh.fact_sinistre", "claim", "date_declaration_sk", "date_survenance_sk"),
        ("dwh.fact_sinistre", "claim", "date_ouverture_sk", "date_survenance_sk"),
        ("dwh.fact_sinistre", "claim", "date_cloture_sk", "date_ouverture_sk"),
        ("dwh.fact_contrat", "contract", "date_fin_contrat_sk", "date_debut_contrat_sk"),
        ("dwh.fact_contrat", "contract", "date_fin_effet_sk", "date_debut_effet_sk"),
    ]
    for table, domain, later_col, earlier_col in chronology_specs:
        schema, table_name = table.split(".")
        if not _table_exists(engine, schema, table_name):
            continue
        cols = set(_columns(engine, schema, table_name))
        if later_col not in cols or earlier_col not in cols:
            continue
        df = _read_sql(
            engine,
            f"""
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE {later_col} > 0 AND {earlier_col} > 0
                                      AND {later_col} < {earlier_col}) AS violations
            FROM {table}
            """,
        )
        total_rows = int(df.loc[0, "total"])
        violations = int(df.loc[0, "violations"])
        rate = violations / total_rows if total_rows else 0.0
        checks.append(
            {
                "domain": domain,
                "metric": f"{table_name}_{later_col}_before_{earlier_col}",
                "value": violations,
                "denominator": total_rows,
                "severity": "WARN" if rate >= 0.001 else "OK",
            }
        )

    return pd.DataFrame(checks)


# Nombre de runs horodatés conservés dans REPORT_DIR/runs
# (surcharge : IRIS_AUDIT_RUN_RETENTION)
DEFAULT_RUN_RETENTION = 10


def _prune_old_runs(runs_dir: Path, keep: int) -> None:
    """Supprime les runs les plus anciens au-delà de `keep` (best-effort).

    Les noms de run sont des timestamps UTC : l'ordre lexicographique est
    l'ordre chronologique.
    """
    try:
        candidates = sorted(p for p in runs_dir.iterdir() if p.is_dir())
        for old in candidates[:-keep] if keep > 0 else []:
            shutil.rmtree(old, ignore_errors=True)
    except OSError:
        pass


def _build_findings(results: dict[str, pd.DataFrame]) -> pd.DataFrame:
    findings = []
    for name, df in results.items():
        if "severity" in df.columns:
            bad = df[df["severity"].isin(["FAIL", "WARN"])].copy()
            if not bad.empty:
                bad.insert(0, "section", name)
                findings.append(bad)
    return pd.concat(findings, ignore_index=True, sort=False) if findings else pd.DataFrame()


def _write_outputs(results: dict[str, pd.DataFrame], run_ts: str) -> tuple[Path, dict]:
    """Écrit l'audit trail :

      runs/<run_ts>/*.csv + manifest.json   — trace immuable du run
      latest/*.csv + manifest.json          — chemins stables (dernier run)

    Retourne (chemin findings du run, manifest).
    """
    runs_dir = REPORT_DIR / "runs"
    run_dir = runs_dir / run_ts
    latest_dir = REPORT_DIR / "latest"
    run_dir.mkdir(parents=True, exist_ok=True)
    latest_dir.mkdir(parents=True, exist_ok=True)

    findings_df = _build_findings(results)
    all_outputs = dict(results)
    all_outputs["etl_quality_findings"] = findings_df

    for name, df in all_outputs.items():
        df.to_csv(run_dir / f"{name}.csv", index=False, encoding="utf-8-sig")
        df.to_csv(latest_dir / f"{name}.csv", index=False, encoding="utf-8-sig")

    sections = {}
    for name, df in results.items():
        if "severity" in df.columns:
            sections[name] = {
                sev: int(n) for sev, n in df["severity"].value_counts().items()
            }
    n_fail = int((findings_df["severity"] == "FAIL").sum()) if not findings_df.empty else 0
    n_warn = int((findings_df["severity"] == "WARN").sum()) if not findings_df.empty else 0
    manifest = {
        "run_id": run_ts,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sections": sections,
        "findings_fail": n_fail,
        "findings_warn": n_warn,
        "status": "FAIL" if n_fail else ("WARN" if n_warn else "OK"),
    }
    for target in (run_dir, latest_dir):
        (target / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    try:
        retention = int(os.environ.get("IRIS_AUDIT_RUN_RETENTION", DEFAULT_RUN_RETENTION))
    except ValueError:
        retention = DEFAULT_RUN_RETENTION
    _prune_old_runs(runs_dir, retention)

    return run_dir / "etl_quality_findings.csv", manifest


def main() -> int:
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    engine = dwh_utils.build_engine()
    results = {
        "table_counts": _table_counts(engine),
        "key_quality": _key_quality(engine),
        "business_key_quality": _business_key_quality(engine),
        "fk_coverage": _fk_coverage(engine),
        "technical_unknown_rows": _technical_unknown_rows(engine),
        "critical_completeness": _critical_completeness(engine),
        "domain_quality": _domain_quality(engine),
    }
    findings_path, manifest = _write_outputs(results, run_ts)

    print("=" * 72)
    print(f"ETL QUALITY / COMPLETENESS AUDIT (read-only) — run {run_ts}")
    print("=" * 72)
    for name, df in results.items():
        if "severity" not in df.columns:
            continue
        counts = df["severity"].value_counts().to_dict()
        print(f"{name:<28} {counts}")
    print(f"status:   {manifest['status']} "
          f"(FAIL={manifest['findings_fail']}, WARN={manifest['findings_warn']})")
    print(f"reports:  {REPORT_DIR / 'runs' / run_ts}")
    print(f"latest:   {REPORT_DIR / 'latest'}")
    print(f"findings: {findings_path}")
    print("=" * 72)

    # Gate prod : code retour non nul si au moins un FAIL — permet de brancher
    # l'audit en CI/orchestration sans parser la sortie.
    return 1 if manifest["findings_fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
