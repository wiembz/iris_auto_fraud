# -*- coding: utf-8 -*-
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
"""
Script de vérification des KPIs affichés dans le dashboard Power BI IRIS.
Compare les valeurs réelles de la base de données avec celles visibles dans la capture d'écran Power BI.

KPIs Power BI à vérifier (d'après la capture d'écran) :
  1. Dossiers scorés        : 221,574K
  2. Score médian           : 11  (Goal: 18, -41,67%)
  3. % Dossiers prioritaires: 0,72%  (Goal: 1,37%, -47,46%)
  4. Montant moyen (prioritaires vs global): 2,52K  (Goal: 2,52K, -9,47%)
  5. % Confiance élevée     : 99,64%  (Goal: 99,96%, -0,32%)
  6. Montant sous vigilance : 700,18KDT  (Goal: 4,30MDT, -83,7%)

  Montant Sinistres par niveau d'attention :
    - Analyse standard     : 394,75MDT (100%)
    - Pointe à vérifier    : 252,23MDT
    - Examen renforcé      : 56,16MDT
    - Examen prioritaire   : 8,73MDT
    - Total                : 711 876 100,65 (vu dans le tableau détail)

  Leads Volume (Pct Prioritaires / Dossiers Scorés) visible sur le graphe
"""

import sys
sys.path.insert(0, '.')

from sqlalchemy import text
from backend.db import get_engine

engine = get_engine()

SEP = "=" * 70

def section(title):
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)

def fmt_num(n, decimals=2):
    if n is None:
        return "NULL"
    return f"{n:,.{decimals}f}"

with engine.connect() as conn:

    # ------------------------------------------------------------------ #
    # 0. Identifier la version de score et le score_run_id le plus récent #
    # ------------------------------------------------------------------ #
    section("0. Score run le plus récent")
    run_info = conn.execute(text("""
        SELECT score_version, score_run_id, MAX(created_at) AS run_date
        FROM mart.fact_claim_attention_score
        GROUP BY score_version, score_run_id
        ORDER BY run_date DESC
        LIMIT 5
    """)).fetchall()
    for r in run_info:
        print(f"  version={r[0]}  run_id={r[1]}  date={r[2]}")

    # Utiliser le run le plus récent
    latest = run_info[0] if run_info else None
    if not latest:
        print("  ⚠️  Aucune donnée trouvée dans fact_claim_attention_score !")
        sys.exit(1)

    SCORE_VERSION = latest[0]
    SCORE_RUN_ID  = latest[1]
    print(f"\n  >> Utilisation de : version={SCORE_VERSION}, run_id={SCORE_RUN_ID}")

    params = {"sv": SCORE_VERSION, "sr": SCORE_RUN_ID}

    # ------------------------------------------------------------------ #
    # 1. KPI : Dossiers scorés (total claims)                             #
    # ------------------------------------------------------------------ #
    section("1. KPI — Dossiers scorés  [PowerBI: 221,574K]")
    total_claims = conn.execute(text("""
        SELECT COUNT(*) AS total
        FROM mart.fact_claim_attention_score
        WHERE score_version = :sv AND score_run_id = :sr
    """), params).scalar_one()
    print(f"  Total dossiers scorés   : {fmt_num(total_claims, 0)}")
    print(f"  En milliers (K)         : {total_claims/1000:.3f}K")
    print(f"  PowerBI affiche         : 221,574K")
    diff1 = total_claims - 221574
    print(f"  Écart                   : {diff1:+,d} ({diff1/221574*100:+.2f}%)")

    # ------------------------------------------------------------------ #
    # 2. KPI : Score médian                                               #
    # ------------------------------------------------------------------ #
    section("2. KPI — Score médian  [PowerBI: 11]")
    median_score = conn.execute(text("""
        SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY attention_score) AS median_score
        FROM mart.fact_claim_attention_score
        WHERE score_version = :sv AND score_run_id = :sr
    """), params).scalar_one()
    print(f"  Score médian réel       : {fmt_num(median_score, 2)}")
    print(f"  PowerBI affiche         : 11")
    if median_score is not None:
        diff2 = float(median_score) - 11
        print(f"  Écart                   : {diff2:+.2f}")

    # ------------------------------------------------------------------ #
    # 3. KPI : % Dossiers prioritaires                                    #
    # ------------------------------------------------------------------ #
    section("3. KPI — % Dossiers prioritaires  [PowerBI: 0,72%]")
    prio_count = conn.execute(text("""
        SELECT COUNT(*) AS cnt
        FROM mart.fact_claim_attention_score
        WHERE score_version = :sv AND score_run_id = :sr
          AND attention_level IN ('Examen renforcé', 'Examen prioritaire',
                                  'examen_renforce', 'examen_prioritaire',
                                  'HIGH', 'CRITICAL', 'PRIORITY')
    """), params).scalar_one()
    pct_prio = (prio_count / total_claims * 100) if total_claims > 0 else 0
    print(f"  Dossiers prioritaires   : {prio_count:,}")
    print(f"  % prioritaires          : {pct_prio:.4f}%")
    print(f"  PowerBI affiche         : 0,72%")
    diff3 = pct_prio - 0.72
    print(f"  Écart                   : {diff3:+.4f}pp")

    # ------------------------------------------------------------------ #
    # 3b. Distribution des attention_level (pour comprendre la segmentation)
    # ------------------------------------------------------------------ #
    section("3b. Distribution attention_level (tous les niveaux)")
    levels = conn.execute(text("""
        SELECT attention_level, COUNT(*) AS cnt,
               ROUND(COUNT(*)*100.0 / SUM(COUNT(*)) OVER (), 4) AS pct
        FROM mart.fact_claim_attention_score
        WHERE score_version = :sv AND score_run_id = :sr
        GROUP BY attention_level
        ORDER BY cnt DESC
    """), params).fetchall()
    for lvl in levels:
        print(f"  {str(lvl[0]):<30} : {lvl[1]:>8,}  ({lvl[2]}%)")

    # ------------------------------------------------------------------ #
    # 4. KPI : Montant moyen (prioritaires vs global)                     #
    # ------------------------------------------------------------------ #
    section("4. KPI — Montant moyen prioritaires  [PowerBI: 2,52K]")
    # Vérifier si la colonne claim_amount existe dans fact_claim_scoring_features
    try:
        avg_amount_prio = conn.execute(text("""
            SELECT AVG(f.claim_amount) AS avg_amount
            FROM mart.fact_claim_attention_score s
            JOIN mart.fact_claim_scoring_features f
              ON f.claim_sk = s.claim_sk AND f.feature_run_id = s.feature_run_id
            WHERE s.score_version = :sv AND s.score_run_id = :sr
              AND s.attention_level IN ('Examen renforcé', 'Examen prioritaire',
                                        'examen_renforce', 'examen_prioritaire',
                                        'HIGH', 'CRITICAL', 'PRIORITY')
        """), params).scalar_one()

        avg_amount_global = conn.execute(text("""
            SELECT AVG(f.claim_amount) AS avg_amount
            FROM mart.fact_claim_attention_score s
            JOIN mart.fact_claim_scoring_features f
              ON f.claim_sk = s.claim_sk AND f.feature_run_id = s.feature_run_id
            WHERE s.score_version = :sv AND s.score_run_id = :sr
        """), params).scalar_one()

        print(f"  Montant moyen (prioritaires)  : {fmt_num(avg_amount_prio, 2)} DT")
        print(f"  En KDT                        : {(avg_amount_prio or 0)/1000:.3f}K")
        print(f"  Montant moyen (global)        : {fmt_num(avg_amount_global, 2)} DT")
        print(f"  En KDT (global)               : {(avg_amount_global or 0)/1000:.3f}K")
        print(f"  PowerBI affiche               : 2,52K")
    except Exception as e:
        print(f"  ⚠️  Erreur: {e}")

    # ------------------------------------------------------------------ #
    # 5. KPI : % Confiance élevée                                         #
    # ------------------------------------------------------------------ #
    section("5. KPI — % Confiance élevée  [PowerBI: 99,64%]")
    conf_levels = conn.execute(text("""
        SELECT confidence_level, COUNT(*) AS cnt,
               ROUND(COUNT(*)*100.0 / SUM(COUNT(*)) OVER (), 4) AS pct
        FROM mart.fact_claim_attention_score
        WHERE score_version = :sv AND score_run_id = :sr
        GROUP BY confidence_level
        ORDER BY cnt DESC
    """), params).fetchall()
    for cl in conf_levels:
        print(f"  {str(cl[0]):<20} : {cl[1]:>8,}  ({cl[2]}%)")

    high_conf = conn.execute(text("""
        SELECT COUNT(*) FROM mart.fact_claim_attention_score
        WHERE score_version = :sv AND score_run_id = :sr
          AND confidence_level IN ('HIGH', 'Élevée', 'élevée', 'HAUTE', 'high', 'ELEVE', 'elevee', 'Haute')
    """), params).scalar_one()
    pct_high_conf = (high_conf / total_claims * 100) if total_claims > 0 else 0
    print(f"\n  Confiance élevée (HIGH) : {high_conf:,}  ({pct_high_conf:.4f}%)")
    print(f"  PowerBI affiche         : 99,64%")

    # ------------------------------------------------------------------ #
    # 6. KPI : Montant total sous vigilance                               #
    # ------------------------------------------------------------------ #
    section("6. KPI — Montant sous vigilance  [PowerBI: 700,18KDT]")
    try:
        montant_vigilance = conn.execute(text("""
            SELECT SUM(f.claim_amount) AS total_amount
            FROM mart.fact_claim_attention_score s
            JOIN mart.fact_claim_scoring_features f
              ON f.claim_sk = s.claim_sk AND f.feature_run_id = s.feature_run_id
            WHERE s.score_version = :sv AND s.score_run_id = :sr
              AND s.attention_level NOT IN ('Analyse standard', 'analyse_standard',
                                             'LOW', 'STANDARD')
        """), params).scalar_one()
        print(f"  Montant sous vigilance  : {fmt_num(montant_vigilance, 2)} DT")
        print(f"  En KDT                  : {(montant_vigilance or 0)/1000:.2f}KDT")
        print(f"  PowerBI affiche         : 700,18KDT")
        if montant_vigilance:
            diff6 = (montant_vigilance/1000) - 700.18
            print(f"  Écart (KDT)             : {diff6:+.2f}KDT")
    except Exception as e:
        print(f"  ⚠️  Erreur: {e}")

    # ------------------------------------------------------------------ #
    # 7. Montant Sinistres par niveau d'attention                         #
    # ------------------------------------------------------------------ #
    section("7. Montant Sinistres par attention_level  [PowerBI total: 711,876K DT]")
    try:
        montants_par_niveau = conn.execute(text("""
            SELECT s.attention_level,
                   COUNT(*) AS nb_dossiers,
                   SUM(f.claim_amount) AS total_montant,
                   AVG(f.claim_amount) AS avg_montant
            FROM mart.fact_claim_attention_score s
            JOIN mart.fact_claim_scoring_features f
              ON f.claim_sk = s.claim_sk AND f.feature_run_id = s.feature_run_id
            WHERE s.score_version = :sv AND s.score_run_id = :sr
            GROUP BY s.attention_level
            ORDER BY total_montant DESC
        """), params).fetchall()

        grand_total = sum(r[2] for r in montants_par_niveau if r[2])
        print(f"\n  {'Niveau':<30} {'Nb':>8}  {'Total (DT)':>20}  {'Total (MDT)':>12}  {'Avg (DT)':>12}")
        print(f"  {'-'*90}")
        for r in montants_par_niveau:
            total_mdt = (r[2] or 0) / 1_000_000
            print(f"  {str(r[0]):<30} {r[1]:>8,}  {(r[2] or 0):>20,.2f}  {total_mdt:>12.4f}MDT  {(r[3] or 0):>12,.2f}")
        print(f"  {'-'*90}")
        print(f"  {'TOTAL':<30} {'':>8}  {grand_total:>20,.2f}  {grand_total/1_000_000:>12.4f}MDT")
        print(f"\n  PowerBI affiche total : 711 876 100,65 DT ≈ 711,876KDT")
        diff7 = grand_total - 711876100.65
        print(f"  Écart                 : {diff7:+,.2f} DT  ({diff7/711876100.65*100:+.4f}%)")
    except Exception as e:
        print(f"  ⚠️  Erreur: {e}")

    # ------------------------------------------------------------------ #
    # 8. Vérification des données du tableau Power BI (exemple de lignes) #
    # ------------------------------------------------------------------ #
    section("8. Vérification lignes tableau détail  [PowerBI: premier dossier A20115 2012 2014]")
    try:
        sample_rows = conn.execute(text("""
            SELECT
                s.claim_business_id,
                s.attention_score,
                s.attention_level,
                f.claim_amount,
                f.claim_date,
                s.main_reason_1
            FROM mart.fact_claim_attention_score s
            JOIN mart.fact_claim_scoring_features f
              ON f.claim_sk = s.claim_sk AND f.feature_run_id = s.feature_run_id
            WHERE s.score_version = :sv AND s.score_run_id = :sr
            ORDER BY f.claim_date ASC, s.claim_business_id
            LIMIT 10
        """), params).fetchall()
        print(f"\n  {'Dossier':<25} {'Score':>6}  {'Niveau':<25}  {'Montant (DT)':>14}  {'Date':<12}  Raison")
        print(f"  {'-'*110}")
        for r in sample_rows:
            print(f"  {str(r[0]):<25} {str(r[1]):>6}  {str(r[2]):<25}  {(r[3] or 0):>14,.2f}  {str(r[4]):<12}  {str(r[5])[:40]}")
    except Exception as e:
        print(f"  ⚠️  Erreur: {e}")

    # ------------------------------------------------------------------ #
    # 9. Dossier spécifique vu dans Power BI : A20115 2012 2014          #
    # ------------------------------------------------------------------ #
    section("9. Dossier 'A201152012014' vu dans tableau PowerBI")
    try:
        specific = conn.execute(text("""
            SELECT
                s.claim_business_id,
                s.attention_score,
                s.attention_level,
                s.confidence_level,
                f.claim_amount,
                f.claim_date,
                s.main_reason_1
            FROM mart.fact_claim_attention_score s
            JOIN mart.fact_claim_scoring_features f
              ON f.claim_sk = s.claim_sk AND f.feature_run_id = s.feature_run_id
            WHERE s.score_version = :sv AND s.score_run_id = :sr
              AND s.claim_business_id ILIKE '%A2011520120%'
            LIMIT 5
        """), params).fetchall()
        if specific:
            for r in specific:
                print(f"  ID={r[0]}, Score={r[1]}, Level={r[2]}, Conf={r[3]}, Montant={r[4]:,.2f}, Date={r[5]}")
                print(f"  Raison: {r[6]}")
        else:
            print("  ⚠️  Dossier non trouvé. Recherche alternative...")
            # Chercher un dossier similaire
            alt = conn.execute(text("""
                SELECT claim_business_id FROM mart.fact_claim_attention_score
                WHERE score_version = :sv AND score_run_id = :sr
                LIMIT 5
            """), params).fetchall()
            print("  Exemples de claim_business_id :")
            for a in alt:
                print(f"    {a[0]}")
    except Exception as e:
        print(f"  ⚠️  Erreur: {e}")

    # ------------------------------------------------------------------ #
    # 10. Synthèse finale                                                  #
    # ------------------------------------------------------------------ #
    section("10. SYNTHÈSE — Concordance avec Power BI")
    print("""
  KPI                          PowerBI Value       Valeur DB         Statut
  -------------------------------------------------------------------------
  Dossiers scorés              221,574K            À calculer        →
  Score médian                 11                  À calculer        →
  % Dossiers prioritaires      0,72%               À calculer        →
  Montant moyen (prioritaires) 2,52K               À calculer        →
  % Confiance élevée           99,64%              À calculer        →
  Montant sous vigilance       700,18KDT           À calculer        →
  Total montant sinistres      711 876 100,65 DT   À calculer        →
  """)

print(f"\n{SEP}")
print("  Script terminé avec succès !")
print(SEP)
