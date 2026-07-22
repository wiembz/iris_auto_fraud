# -*- coding: utf-8 -*-
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

"""
Verification des KPIs Power BI via le schema powerbi_v
"""
sys.path.insert(0, '.')
from sqlalchemy import text
from backend.db import get_engine

engine = get_engine()
SEP = "=" * 72

def section(num, title, pbi_val=""):
    print(f"\n{SEP}")
    label = f"  ETAPE {num} — {title}"
    if pbi_val:
        label += f"   [Power BI: {pbi_val}]"
    print(label)
    print(SEP)

def run(conn, sql, label=""):
    try:
        rows = conn.execute(text(sql)).fetchall()
        if not rows:
            print(f"  (aucune ligne retournee)")
            return []
        cols = list(rows[0]._mapping.keys())
        # Header
        widths = [max(len(str(c)), max((len(str(r._mapping[c])) for r in rows), default=0)) for c in cols]
        header = "  " + "  ".join(str(c).ljust(w) for c, w in zip(cols, widths))
        print(header)
        print("  " + "-" * (sum(widths) + 2 * len(widths)))
        for r in rows:
            print("  " + "  ".join(str(r._mapping[c]).ljust(w) for c, w in zip(cols, widths)))
        return rows
    except Exception as e:
        print(f"  ERREUR: {e}")
        return []

with engine.connect() as conn:

    # ------------------------------------------------------------------
    # ETAPE 0 — Configuration
    # ------------------------------------------------------------------
    section(0, "Configuration active (version & run Power BI)")

    print("\n-- 0.1 Version configuree --")
    run(conn, "SELECT score_version FROM powerbi_v.v_score_version_config")

    print("\n-- 0.2 Run actif --")
    run(conn, "SELECT score_version, score_run_id FROM powerbi_v.v_current_run")

    print("\n-- 0.3 Gouvernance complete --")
    run(conn, """
        SELECT component, version, run_id, created_at, row_count
        FROM powerbi_v.v_governance ORDER BY component
    """)

    # ------------------------------------------------------------------
    # ETAPE 1 — Dossiers scorés
    # ------------------------------------------------------------------
    section(1, "Dossiers scores (grain dossier - regle ADR MAX)", "221 574")

    print("\n-- 1.1 Total dossiers uniques --")
    run(conn, """
        SELECT
            COUNT(*)                  AS dossier_count,
            ROUND(COUNT(*)/1000.0, 3) AS dossier_count_K,
            MIN(claim_date)           AS date_min,
            MAX(claim_date)           AS date_max
        FROM powerbi_v.v_dossier_attention
    """)

    print("\n-- 1.2 Cross-check grain garantie --")
    run(conn, """
        SELECT
            COUNT(*)                        AS guarantee_rows,
            COUNT(DISTINCT claim_root_id)   AS dossier_count_check
        FROM powerbi_v.v_claim_attention_guarantee
    """)

    # ------------------------------------------------------------------
    # ETAPE 2 — Score median
    # ------------------------------------------------------------------
    section(2, "Score median", "11")

    run(conn, """
        SELECT
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY dossier_attention_score) AS score_median,
            ROUND(AVG(dossier_attention_score)::numeric, 2)                       AS score_mean,
            MIN(dossier_attention_score)                                           AS score_min,
            MAX(dossier_attention_score)                                           AS score_max,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY dossier_attention_score) AS score_p25,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY dossier_attention_score) AS score_p75
        FROM powerbi_v.v_dossier_attention
    """)

    # ------------------------------------------------------------------
    # ETAPE 3 — % Dossiers prioritaires
    # ------------------------------------------------------------------
    section(3, "% Dossiers prioritaires", "0,72%")

    print("\n-- 3.1 Distribution attention_level --")
    run(conn, """
        SELECT
            dossier_attention_level,
            COUNT(*)                                                    AS nb_dossiers,
            ROUND(COUNT(*)*100.0/SUM(COUNT(*)) OVER (), 4)             AS pct
        FROM powerbi_v.v_dossier_attention
        GROUP BY dossier_attention_level
        ORDER BY nb_dossiers DESC
    """)

    print("\n-- 3.2 % Prioritaires cumule --")
    run(conn, """
        SELECT
            COUNT(*) FILTER (WHERE dossier_attention_level IN
                ('Examen renforce suggere','Examen prioritaire suggere')) AS nb_prioritaires,
            COUNT(*)                                                       AS nb_total,
            ROUND(
                COUNT(*) FILTER (WHERE dossier_attention_level IN
                    ('Examen renforce suggere','Examen prioritaire suggere'))
                * 100.0 / COUNT(*), 4
            )                                                              AS pct_prioritaires
        FROM powerbi_v.v_dossier_attention
    """)

    # ------------------------------------------------------------------
    # ETAPE 4 — Montant moyen prioritaires
    # ------------------------------------------------------------------
    section(4, "Montant moyen prioritaires vs global", "2,52K DT")

    run(conn, """
        SELECT
            'Global'        AS segment,
            COUNT(*)        AS nb,
            ROUND(AVG(dossier_claim_amount)::numeric, 2)   AS avg_DT,
            ROUND(AVG(dossier_claim_amount)/1000, 3)       AS avg_KDT
        FROM powerbi_v.v_dossier_attention
        UNION ALL
        SELECT 'Prioritaires (renforce+prioritaire)',
            COUNT(*),
            ROUND(AVG(dossier_claim_amount)::numeric, 2),
            ROUND(AVG(dossier_claim_amount)/1000, 3)
        FROM powerbi_v.v_dossier_attention
        WHERE dossier_attention_level IN
              ('Examen renforce suggere','Examen prioritaire suggere')
        UNION ALL
        SELECT 'Non prioritaires',
            COUNT(*),
            ROUND(AVG(dossier_claim_amount)::numeric, 2),
            ROUND(AVG(dossier_claim_amount)/1000, 3)
        FROM powerbi_v.v_dossier_attention
        WHERE dossier_attention_level NOT IN
              ('Examen renforce suggere','Examen prioritaire suggere')
    """)

    # ------------------------------------------------------------------
    # ETAPE 5 — % Confiance elevee
    # ------------------------------------------------------------------
    section(5, "% Confiance elevee", "99,64%")

    print("\n-- 5.1 Distribution confidence_level (grain dossier) --")
    run(conn, """
        SELECT
            confidence_level,
            COUNT(*)                                                AS nb_dossiers,
            ROUND(COUNT(*)*100.0/SUM(COUNT(*)) OVER (), 4)         AS pct
        FROM powerbi_v.v_dossier_attention
        GROUP BY confidence_level
        ORDER BY nb_dossiers DESC
    """)

    print("\n-- 5.2 Via v_quality_kpis (KPI officiel) --")
    run(conn, """
        SELECT
            guarantee_rows,
            dossier_count,
            ROUND(pct_confidence_high*100, 4)   AS pct_confidence_high,
            ROUND(pct_unknown_client*100, 4)     AS pct_unknown_client,
            ROUND(pct_missing_vehicle*100, 4)    AS pct_missing_vehicle,
            ROUND(pct_invalid_dates*100, 4)      AS pct_invalid_dates,
            ROUND(pct_migration_2019*100, 4)     AS pct_migration_2019
        FROM powerbi_v.v_quality_kpis
    """)

    # ------------------------------------------------------------------
    # ETAPE 6 — Montant sous vigilance
    # ------------------------------------------------------------------
    section(6, "Montant sous vigilance", "700,18 KDT")

    run(conn, """
        SELECT
            'DEF-A: Tout hors standard'                AS definition,
            ROUND(SUM(dossier_claim_amount)/1000, 2)   AS montant_KDT
        FROM powerbi_v.v_dossier_attention
        WHERE dossier_attention_level <> 'Analyse standard'
        UNION ALL
        SELECT 'DEF-B: Renforce + Prioritaire',
            ROUND(SUM(dossier_claim_amount)/1000, 2)
        FROM powerbi_v.v_dossier_attention
        WHERE dossier_attention_level IN
              ('Examen renforce suggere','Examen prioritaire suggere')
        UNION ALL
        SELECT 'DEF-C: Prioritaire seul',
            ROUND(SUM(dossier_claim_amount)/1000, 2)
        FROM powerbi_v.v_dossier_attention
        WHERE dossier_attention_level = 'Examen prioritaire suggere'
        UNION ALL
        SELECT 'DEF-D: Total global',
            ROUND(SUM(dossier_claim_amount)/1000, 2)
        FROM powerbi_v.v_dossier_attention
    """)

    # ------------------------------------------------------------------
    # ETAPE 7 — Montant Sinistres par attention_level
    # ------------------------------------------------------------------
    section(7, "Montant Sinistres par attention_level", "Total: 711 876 100,65 DT")

    run(conn, """
        SELECT
            dossier_attention_level,
            COUNT(*)                                                    AS nb_dossiers,
            ROUND(SUM(dossier_claim_amount)::numeric, 2)               AS montant_DT,
            ROUND(SUM(dossier_claim_amount)/1e6, 4)                    AS montant_MDT,
            ROUND(SUM(dossier_claim_amount)*100.0
                  /SUM(SUM(dossier_claim_amount)) OVER (), 2)          AS pct_du_total
        FROM powerbi_v.v_dossier_attention
        GROUP BY dossier_attention_level
        ORDER BY montant_DT DESC
    """)

    print("\n-- Total global --")
    run(conn, """
        SELECT
            ROUND(SUM(dossier_claim_amount)::numeric, 2)  AS total_DT,
            ROUND(SUM(dossier_claim_amount)/1e6, 4)       AS total_MDT
        FROM powerbi_v.v_dossier_attention
    """)

    # ------------------------------------------------------------------
    # ETAPE 8 — Leads Volume Over Time
    # ------------------------------------------------------------------
    section(8, "Leads Volume Over Time (mensuel)")

    run(conn, """
        SELECT
            EXTRACT(YEAR  FROM claim_date)::int              AS annee,
            TO_CHAR(claim_date,'Mon')                        AS mois,
            COUNT(*)                                         AS nb_dossiers,
            COUNT(*) FILTER (WHERE dossier_attention_level IN
                ('Examen renforce suggere','Examen prioritaire suggere'))
                                                             AS nb_prioritaires,
            ROUND(
                COUNT(*) FILTER (WHERE dossier_attention_level IN
                    ('Examen renforce suggere','Examen prioritaire suggere'))
                *100.0/NULLIF(COUNT(*),0), 4
            )                                                AS pct_prioritaires
        FROM powerbi_v.v_dossier_attention
        WHERE claim_date IS NOT NULL
        GROUP BY 1, 2, EXTRACT(MONTH FROM claim_date)
        ORDER BY 1, EXTRACT(MONTH FROM claim_date)
    """)

    # ------------------------------------------------------------------
    # ETAPE 9 — Tableau detail
    # ------------------------------------------------------------------
    section(9, "Tableau detail (premieres lignes Power BI)")

    run(conn, """
        SELECT
            EXTRACT(YEAR  FROM claim_date)::int              AS year,
            TO_CHAR(claim_date,'Month')                      AS month,
            EXTRACT(DAY   FROM claim_date)::int              AS day,
            claim_root_id,
            dossier_attention_score,
            ROUND(dossier_claim_amount::numeric, 2)          AS sum_dossier_claim_amount,
            main_reason_1
        FROM powerbi_v.v_dossier_attention
        WHERE claim_date IS NOT NULL
        ORDER BY claim_date ASC, claim_root_id
        LIMIT 10
    """)

    print("\n-- Dossier A201152012014 specifique --")
    run(conn, """
        SELECT claim_root_id, dossier_attention_score, dossier_attention_level,
               confidence_level,
               ROUND(dossier_claim_amount::numeric, 2) AS montant_DT,
               claim_date, main_reason_1
        FROM powerbi_v.v_dossier_attention
        WHERE claim_root_id = 'A201152012014'
    """)

    # ------------------------------------------------------------------
    # ETAPE 10 — Carte geographique
    # ------------------------------------------------------------------
    section(10, "Carte geographique (par gouvernorat)")

    run(conn, """
        SELECT
            COALESCE(gouvernorat,'Non renseigne')           AS gouvernorat,
            COUNT(*)                                        AS nb_dossiers,
            ROUND(SUM(dossier_claim_amount)::numeric, 2)   AS montant_DT,
            ROUND(AVG(dossier_attention_score)::numeric,2) AS score_moyen
        FROM powerbi_v.v_dossier_attention
        GROUP BY gouvernorat
        ORDER BY nb_dossiers DESC
        LIMIT 20
    """)

    # ------------------------------------------------------------------
    # ETAPE 11 — SYNTHESE FINALE
    # ------------------------------------------------------------------
    section(11, "SYNTHESE — Tous les KPIs Power BI en une requete")

    print("\n-- KPIs numeriques --")
    run(conn, """
        SELECT
            COUNT(*)                                                     AS kpi_dossiers_scores,
            PERCENTILE_CONT(0.5) WITHIN GROUP
                (ORDER BY dossier_attention_score)                       AS kpi_score_median,
            ROUND(
                COUNT(*) FILTER (WHERE dossier_attention_level IN
                    ('Examen renforce suggere','Examen prioritaire suggere'))
                *100.0/COUNT(*), 4)                                      AS kpi_pct_prioritaires,
            ROUND(AVG(dossier_claim_amount) FILTER (WHERE dossier_attention_level IN
                ('Examen renforce suggere','Examen prioritaire suggere'))
                ::numeric/1000, 3)                                       AS kpi_avg_prio_KDT,
            ROUND(SUM(dossier_claim_amount)::numeric, 2)                 AS kpi_total_DT
        FROM powerbi_v.v_dossier_attention
    """)

    print("\n-- Confiance + qualite --")
    run(conn, """
        SELECT
            dossier_count,
            ROUND(pct_confidence_high*100, 4) AS kpi_pct_confiance_HIGH
        FROM powerbi_v.v_quality_kpis
    """)

print(f"\n{SEP}")
print("  Verification terminee avec succes !")
print(SEP)
