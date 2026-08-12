-- docs/claim_attention/claim_sk_14188_control_queries.sql
-- ==========================================================
-- Requêtes de contrôle pour le dossier de référence G26511000017765|REM
-- (claim_sk = 14188), avant/après le correctif dim_conducteur.
--
-- Usage : exécuter la même requête sur iris_auto_fraud (avant) et sur la
-- copie de test après recalcul complet (après), puis comparer les deux
-- résultats. Aucune de ces requêtes n'écrit en base.

-- 1. Identité conducteur du dossier (attendu après fix : conducteur_sk = 0)
--    Note : claim_sk n'existe pas dans dwh.fact_sinistre (c'est un renommage
--    de fact_sinistre_sk fait au niveau mart, cf. compute_claim_scoring_features_v1.py).
SELECT fs.fact_sinistre_sk AS claim_sk, fs.numero_sinistre, fs.code_garantie, fs.conducteur_sk,
       dc.numero_permis, dc.nom_conducteur, dc.source_system
FROM dwh.fact_sinistre fs
LEFT JOIN dwh.dim_conducteur dc ON dc.conducteur_sk = fs.conducteur_sk
WHERE fs.numero_sinistre = 'G26511000017765' AND fs.code_garantie = 'REM';

-- 2. Features de scoring calculées pour ce dossier (attendu : driver_claim_count_12m = 0,
--    driver_days_since_previous_claim = NULL)
SELECT feature_run_id, claim_sk, claim_business_id,
       driver_claim_count_12m, driver_claim_count_total, driver_days_since_previous_claim,
       vehicle_claim_count_12m, client_claim_count_12m
FROM mart.fact_claim_scoring_features
WHERE claim_sk = 14188
ORDER BY created_at DESC
LIMIT 1;

-- 3. Signaux règles métier générés pour ce dossier (attendu : aucune ligne
--    DRIVER_CLAIMS_12M_HIGH ni DRIVER_RECENT_PREVIOUS_CLAIM)
SELECT signal_run_id, rule_family, rule_code, rule_label, rule_observed_value, candidate_points
FROM mart.fact_claim_business_rule_signal
WHERE claim_sk = 14188
  AND signal_run_id = (
      SELECT signal_run_id FROM mart.fact_claim_business_rule_signal
      GROUP BY signal_run_id ORDER BY MAX(created_at) DESC LIMIT 1
  )
ORDER BY rule_family, rule_code;

-- 4. Signal ML anomaly (attendu : driver_claim_count_12m absent ou non dominant
--    parmi les top variables, score_ml recalculé)
SELECT signal_run_id, claim_sk, raw_anomaly_score, score_ml, top_variable_1, top_variable_2, top_variable_3
FROM mart.fact_claim_ml_anomaly_signal
WHERE claim_sk = 14188
ORDER BY created_at DESC
LIMIT 1;

-- 5. Score d'attention final / niveau — version LIVE = IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE
--    (backend/config.py: DEFAULT_SCORE_VERSION). Attendu : score < 80, niveau possiblement revu.
SELECT score_run_id, claim_sk, score_version, attention_score, attention_level, confidence_level, created_at
FROM mart.fact_claim_attention_score
WHERE claim_sk = 14188
  AND score_version = 'IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE'
ORDER BY created_at DESC
LIMIT 1;

-- 6. Comparaison globale avant/après des niveaux d'attention (distribution)
--    À exécuter sur les deux bases puis comparer les répartitions.
SELECT attention_level, COUNT(*) AS nb_dossiers
FROM mart.fact_claim_attention_score
WHERE score_version = 'IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE'
  AND score_run_id = (
      SELECT score_run_id FROM mart.fact_claim_attention_score
      WHERE score_version = 'IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE'
      GROUP BY score_run_id ORDER BY MAX(created_at) DESC LIMIT 1
  )
GROUP BY attention_level
ORDER BY attention_level;

-- 7. Stabilité du nombre de sinistres (doit être identique avant/après :
--    le correctif ne supprime ni n'ajoute aucun sinistre, seulement des
--    conducteur_sk)
SELECT COUNT(*) AS total_fact_sinistre FROM dwh.fact_sinistre;

-- 8. Pas de perte de conducteurs légitimes : nombre de conducteurs réels
--    avant vs après (attendu : baisse marginale, ~83 sur 161522, toutes
--    identifiées comme valeurs de repli dans le rapport d'impact)
SELECT COUNT(*) AS conducteurs_reels FROM dwh.dim_conducteur WHERE conducteur_sk <> 0;

-- 9. Répartition sk=0 vs réels dans fact_sinistre (avant/après)
SELECT
    COUNT(*) FILTER (WHERE conducteur_sk = 0) AS conducteur_unknown,
    COUNT(*) FILTER (WHERE conducteur_sk <> 0) AS conducteur_reel,
    ROUND(100.0 * COUNT(*) FILTER (WHERE conducteur_sk = 0) / NULLIF(COUNT(*), 0), 2) AS pct_unknown
FROM dwh.fact_sinistre;

-- 10. Résultat du gate qualité ETL (doit rester 0 FAIL après recalcul)
--     Consulter data/quality_reports/etl_quality/latest/manifest.json après
--     l'étape audit_etl_quality_completeness du pipeline.
