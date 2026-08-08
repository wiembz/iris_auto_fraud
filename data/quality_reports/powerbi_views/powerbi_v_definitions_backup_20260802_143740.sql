-- powerbi_v.v_claim_attention_guarantee
CREATE OR REPLACE VIEW powerbi_v.v_claim_attention_guarantee AS
 SELECT sc.claim_sk,
    sc.claim_business_id,
    split_part(sc.claim_business_id, '|'::text, 1) AS claim_root_id,
    f.numero_sinistre,
    f.code_garantie,
    f.client_sk,
    f.contrat_sk,
    f.vehicle_sk,
    f.garantie_sk,
    f.claim_date,
    f.declaration_date,
    f.contract_start_date,
    f.claim_amount,
    f.client_claim_count_12m,
    f.client_claim_count_24m,
    f.days_since_previous_claim,
    f.days_claim_to_declaration,
    f.days_contract_start_to_claim,
    sc.attention_score,
    sc.attention_level,
    COALESCE(sc.confidence_level, 'Non renseigne'::text) AS confidence_level,
    COALESCE(sc.main_reason_1, 'Non renseigne'::text) AS main_reason_1,
    COALESCE(sc.main_reason_2, 'Non renseigne'::text) AS main_reason_2,
    COALESCE(sc.main_reason_3, 'Non renseigne'::text) AS main_reason_3,
    sc.score_version,
    sc.score_run_id,
    sc.feature_run_id,
    sc.created_at,
    f.claim_geo_sk
   FROM mart.fact_claim_attention_score sc
     JOIN powerbi_v.v_current_run r ON sc.score_version = r.score_version AND sc.score_run_id = r.score_run_id
     LEFT JOIN mart.fact_claim_scoring_features f ON f.claim_sk = sc.claim_sk AND f.feature_run_id = sc.feature_run_id;

-- powerbi_v.v_client_cohort
CREATE OR REPLACE VIEW powerbi_v.v_client_cohort AS
 SELECT d.client_sk,
    count(DISTINCT d.claim_root_id) AS dossier_count,
    sum(d.dossier_claim_amount) AS total_claim_amount,
    min(d.claim_date) AS first_claim_date,
    max(d.claim_date) AS last_claim_date,
    max(d.dossier_attention_score) AS max_attention_score,
    count(DISTINCT d.claim_root_id) FILTER (WHERE d.dossier_attention_level = ANY (ARRAY['Examen renforce suggere'::text, 'Examen prioritaire suggere'::text])) AS high_attention_dossier_count,
    max(g.client_claim_count_12m) AS max_claim_count_12m,
    max(g.client_claim_count_12m) >= 3 AS is_multiclaim_12m,
    max(d.client_business_id) AS idclt
   FROM powerbi_v.v_dossier_attention d
     LEFT JOIN powerbi_v.v_claim_attention_guarantee g ON g.claim_root_id = d.claim_root_id
  WHERE d.client_sk IS NOT NULL AND d.client_sk <> 0
  GROUP BY d.client_sk;

-- powerbi_v.v_current_run
CREATE OR REPLACE VIEW powerbi_v.v_current_run AS
 SELECT s.score_version,
    max(s.score_run_id) AS score_run_id
   FROM mart.fact_claim_attention_score s
     JOIN powerbi_v.v_score_version_config c ON s.score_version = c.score_version
  GROUP BY s.score_version;

-- powerbi_v.v_dossier_attention
CREATE OR REPLACE VIEW powerbi_v.v_dossier_attention AS
 WITH ranked AS (
         SELECT g.claim_sk,
            g.claim_business_id,
            g.claim_root_id,
            g.numero_sinistre,
            g.code_garantie,
            g.client_sk,
            g.contrat_sk,
            g.vehicle_sk,
            g.garantie_sk,
            g.claim_date,
            g.declaration_date,
            g.contract_start_date,
            g.claim_amount,
            g.client_claim_count_12m,
            g.client_claim_count_24m,
            g.days_since_previous_claim,
            g.days_claim_to_declaration,
            g.days_contract_start_to_claim,
            g.attention_score,
            g.attention_level,
            g.confidence_level,
            g.main_reason_1,
            g.main_reason_2,
            g.main_reason_3,
            g.score_version,
            g.score_run_id,
            g.feature_run_id,
            g.created_at,
            g.claim_geo_sk,
            row_number() OVER (PARTITION BY g.claim_root_id ORDER BY g.attention_score DESC, g.claim_sk) AS rn
           FROM powerbi_v.v_claim_attention_guarantee g
        ), agg AS (
         SELECT v_claim_attention_guarantee.claim_root_id,
            count(*) AS guarantee_row_count,
            count(DISTINCT v_claim_attention_guarantee.code_garantie) AS guarantee_code_count,
            sum(v_claim_attention_guarantee.claim_amount) AS dossier_claim_amount,
            min(v_claim_attention_guarantee.claim_date) AS claim_date,
            min(v_claim_attention_guarantee.declaration_date) AS declaration_date
           FROM powerbi_v.v_claim_attention_guarantee
          GROUP BY v_claim_attention_guarantee.claim_root_id
        )
 SELECT r.claim_root_id,
    r.numero_sinistre,
    r.attention_score AS dossier_attention_score,
    r.attention_level AS dossier_attention_level,
    r.confidence_level,
    r.main_reason_1,
    r.main_reason_2,
    r.main_reason_3,
    r.client_sk,
    r.contrat_sk,
    r.vehicle_sk,
    a.guarantee_row_count,
    a.guarantee_code_count,
    a.dossier_claim_amount,
    a.claim_date,
    a.declaration_date,
    r.score_version,
    r.score_run_id,
    COALESCE(
        CASE
            WHEN geo.gouvernorat = 'UNKNOWN'::text THEN NULL::text
            ELSE geo.gouvernorat
        END, 'Non renseigne'::text) AS gouvernorat,
    COALESCE(
        CASE
            WHEN geo.region = 'UNKNOWN'::text THEN NULL::text
            ELSE geo.region
        END, 'Non renseigne'::text) AS geo_region,
    cl.idclt AS client_business_id
   FROM ranked r
     LEFT JOIN dwh.dim_geo geo ON geo.geo_sk = r.claim_geo_sk
     LEFT JOIN dwh.dim_client cl ON cl.client_sk = r.client_sk
     JOIN agg a ON a.claim_root_id = r.claim_root_id
  WHERE r.rn = 1;

-- powerbi_v.v_governance
CREATE OR REPLACE VIEW powerbi_v.v_governance AS
 SELECT 'CLAIM_ATTENTION'::text AS component,
    r.score_version AS version,
    r.score_run_id AS run_id,
    ( SELECT max(s.created_at) AS max
           FROM mart.fact_claim_attention_score s
          WHERE s.score_run_id = r.score_run_id) AS created_at,
    ( SELECT count(*) AS count
           FROM mart.fact_claim_attention_score s
          WHERE s.score_run_id = r.score_run_id) AS row_count
   FROM powerbi_v.v_current_run r
UNION ALL
 SELECT 'ML_ANOMALY'::text AS component,
    max(fact_claim_ml_anomaly_signal.signal_version) AS version,
    max(fact_claim_ml_anomaly_signal.signal_run_id) AS run_id,
    max(fact_claim_ml_anomaly_signal.created_at) AS created_at,
    count(*) FILTER (WHERE fact_claim_ml_anomaly_signal.signal_run_id = (( SELECT max(fact_claim_ml_anomaly_signal_1.signal_run_id) AS max
           FROM mart.fact_claim_ml_anomaly_signal fact_claim_ml_anomaly_signal_1))) AS row_count
   FROM mart.fact_claim_ml_anomaly_signal
UNION ALL
 SELECT 'POST_INSPECTION'::text AS component,
    max(fact_post_inspection_attention_signal.signal_version) AS version,
    max(fact_post_inspection_attention_signal.signal_run_id) AS run_id,
    max(fact_post_inspection_attention_signal.created_at) AS created_at,
    count(*) FILTER (WHERE fact_post_inspection_attention_signal.signal_run_id = (( SELECT max(fact_post_inspection_attention_signal_1.signal_run_id) AS max
           FROM mart.fact_post_inspection_attention_signal fact_post_inspection_attention_signal_1))) AS row_count
   FROM mart.fact_post_inspection_attention_signal
UNION ALL
 SELECT 'VHS'::text AS component,
    max(fact_vhs_score.rule_version) AS version,
    max(fact_vhs_score.run_id) AS run_id,
    max(fact_vhs_score.created_at) AS created_at,
    count(*) FILTER (WHERE fact_vhs_score.run_id = (( SELECT max(fact_vhs_score_1.run_id) AS max
           FROM mart.fact_vhs_score fact_vhs_score_1))) AS row_count
   FROM mart.fact_vhs_score;

-- powerbi_v.v_inspection
CREATE OR REPLACE VIEW powerbi_v.v_inspection AS
 SELECT i.inspection_key,
    i.vehicule_sk,
    COALESCE(i.immatriculation_norm, 'Non renseigne'::text) AS immatriculation_norm,
        CASE
            WHEN i.date_inspection_sk > 19000101 THEN to_date(i.date_inspection_sk::text, 'YYYYMMDD'::text)
            ELSE NULL::date
        END AS inspection_date,
    count(c.checkpoint_code) AS checkpoint_count,
    count(*) FILTER (WHERE c.est_anomalie) AS defect_count,
    count(*) FILTER (WHERE c.est_anomalie_critique) AS critical_defect_count,
    i.indicateur_inspection_complete,
    COALESCE(NULLIF(btrim(split_part(regexp_replace(i.agent_controle, '\s*-\s*'::text, ' - '::text), ' - '::text, 1)), ''::text), 'Non renseigne'::text) AS garage_nom,
    COALESCE(NULLIF(btrim(split_part(regexp_replace(i.agent_controle, '\s*-\s*'::text, ' - '::text), ' - '::text, 2)), ''::text), 'Non renseigne'::text) AS garage_localite
   FROM dwh.fact_inspection_vehicule i
     LEFT JOIN dwh.fact_inspection_checkpoint c ON c.inspection_key = i.inspection_key
  GROUP BY i.inspection_key, i.vehicule_sk, i.immatriculation_norm, i.indicateur_inspection_complete, i.date_inspection_sk, i.agent_controle;

-- powerbi_v.v_inspection_checkpoint_defect
CREATE OR REPLACE VIEW powerbi_v.v_inspection_checkpoint_defect AS
 SELECT zone_controle,
    checkpoint_code,
    checkpoint_libelle,
    count(*) AS observed_count,
    count(*) FILTER (WHERE est_anomalie) AS defect_count,
    count(*) FILTER (WHERE est_anomalie_critique) AS critical_defect_count
   FROM dwh.fact_inspection_checkpoint c
  GROUP BY zone_controle, checkpoint_code, checkpoint_libelle;

-- powerbi_v.v_ml_anomaly
CREATE OR REPLACE VIEW powerbi_v.v_ml_anomaly AS
 SELECT claim_sk,
    claim_business_id,
    split_part(claim_business_id, '|'::text, 1) AS claim_root_id,
    raw_anomaly_score,
    anomaly_percentile_score,
    score_ml,
    ml_attention_level,
    COALESCE(top_variable_1, 'Non renseigne'::text) AS top_variable_1,
    COALESCE(top_variable_2, 'Non renseigne'::text) AS top_variable_2,
    COALESCE(top_variable_3, 'Non renseigne'::text) AS top_variable_3,
    signal_version,
    signal_run_id
   FROM mart.fact_claim_ml_anomaly_signal m
  WHERE signal_run_id = (( SELECT max(fact_claim_ml_anomaly_signal.signal_run_id) AS max
           FROM mart.fact_claim_ml_anomaly_signal));

-- powerbi_v.v_post_inspection_signal
CREATE OR REPLACE VIEW powerbi_v.v_post_inspection_signal AS
 SELECT claim_sk,
    inspection_sk,
    client_sk,
    vehicule_sk,
    immatriculation,
    inspection_date,
    claim_date,
    days_inspection_to_claim,
    delay_bucket,
    COALESCE(defective_zone, 'Non renseigne'::text) AS defective_zone,
    defective_checkpoint_count,
    critical_checkpoint_count,
    claim_guarantee_code,
    COALESCE(claim_guarantee_label, 'Non renseigne'::text) AS claim_guarantee_label,
    COALESCE(zone_match_status, 'Non renseigne'::text) AS zone_match_status,
    attention_level,
    COALESCE(confidence_level, 'Non renseigne'::text) AS confidence_level,
    COALESCE(business_explanation, 'Non renseigne'::text) AS business_explanation,
    scenario_code,
    signal_version,
    signal_run_id
   FROM mart.fact_post_inspection_attention_signal p
  WHERE signal_run_id = (( SELECT max(fact_post_inspection_attention_signal.signal_run_id) AS max
           FROM mart.fact_post_inspection_attention_signal));

-- powerbi_v.v_quality_kpis
CREATE OR REPLACE VIEW powerbi_v.v_quality_kpis AS
 SELECT count(*) AS guarantee_rows,
    count(DISTINCT split_part(sc.claim_business_id, '|'::text, 1)) AS dossier_count,
    avg(
        CASE
            WHEN f.client_sk IS NULL OR f.client_sk = 0 THEN 1.0
            ELSE 0.0
        END) AS pct_unknown_client,
    avg(
        CASE
            WHEN f.missing_vehicle_flag THEN 1.0
            ELSE 0.0
        END) AS pct_missing_vehicle,
    avg(
        CASE
            WHEN f.invalid_claim_date_flag OR f.invalid_declaration_date_flag THEN 1.0
            ELSE 0.0
        END) AS pct_invalid_dates,
    avg(
        CASE
            WHEN f.migration_2019_flag THEN 1.0
            ELSE 0.0
        END) AS pct_migration_2019,
    avg(
        CASE
            WHEN sc.confidence_level = 'HIGH'::text THEN 1.0
            ELSE 0.0
        END) AS pct_confidence_high,
    ( SELECT avg(
                CASE
                    WHEN v2.immatriculation_norm IS NULL THEN 1.0
                    ELSE 0.0
                END) AS avg
           FROM mart.fact_vhs_score v2
          WHERE v2.run_id = (( SELECT max(fact_vhs_score.run_id) AS max
                   FROM mart.fact_vhs_score))) AS pct_vhs_missing_immatriculation
   FROM mart.fact_claim_attention_score sc
     JOIN powerbi_v.v_current_run r ON sc.score_version = r.score_version AND sc.score_run_id = r.score_run_id
     LEFT JOIN mart.fact_claim_scoring_features f ON f.claim_sk = sc.claim_sk AND f.feature_run_id = sc.feature_run_id;

-- powerbi_v.v_score_version_config
CREATE OR REPLACE VIEW powerbi_v.v_score_version_config AS
 SELECT 'IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE'::text AS score_version;

-- powerbi_v.v_signal_detail
CREATE OR REPLACE VIEW powerbi_v.v_signal_detail AS
 SELECT d.claim_sk,
    d.claim_business_id,
    split_part(d.claim_business_id, '|'::text, 1) AS claim_root_id,
    d.signal_family,
    d.signal_code,
    COALESCE(d.signal_label, 'Non renseigne'::text) AS signal_label,
    d.signal_value,
    d.points,
    d.severity,
    COALESCE(d.business_explanation, 'Non renseigne'::text) AS business_explanation,
    d.score_version,
    d.score_run_id
   FROM mart.fact_claim_attention_signal_detail d
     JOIN powerbi_v.v_current_run r ON d.score_version = r.score_version AND d.score_run_id = r.score_run_id;

-- powerbi_v.v_vhs_score
CREATE OR REPLACE VIEW powerbi_v.v_vhs_score AS
 SELECT v.inspection_key,
    v.vehicule_sk,
    v.immatriculation_norm,
    v.kilometrage,
    v.vhs_final_score,
    v.safety_score,
    v.functional_score,
    v.cosmetic_score,
    v.safety_grade,
    v.decision,
    v.is_drivable,
    v.hard_cap_applied,
    v.nb_penalties_applied,
    v.nb_anomalies_total,
    v.nb_anomalies_critiques,
    v.rule_version,
    v.run_id,
        CASE v.safety_grade
            WHEN 'A'::text THEN 'Aucun signal technique majeur'::text
            WHEN 'B'::text THEN 'Quelques points a surveiller'::text
            WHEN 'C'::text THEN 'Degradation technique notable'::text
            WHEN 'D'::text THEN 'Situation technique sensible'::text
            ELSE 'Non renseigne'::text
        END AS grade_label,
        CASE v.decision
            WHEN 'OK'::text THEN 'Etat satisfaisant'::text
            WHEN 'DEGRADE'::text THEN 'Etat a surveiller'::text
            WHEN 'IMMOBILISE'::text THEN 'Usage deconseille'::text
            WHEN 'CRITIQUE'::text THEN 'Examen prioritaire suggere'::text
            ELSE 'Non renseigne'::text
        END AS decision_label,
        CASE v.decision
            WHEN 'OK'::text THEN 'Le vehicule ne presente pas de signal technique majeur dans les points analyses.'::text
            WHEN 'DEGRADE'::text THEN 'Le vehicule presente plusieurs points techniques a surveiller. Une verification complementaire peut etre utile.'::text
            WHEN 'IMMOBILISE'::text THEN 'IRIS a releve un point technique sensible. L''usage du vehicule est deconseille sans verification complementaire.'::text
            WHEN 'CRITIQUE'::text THEN 'IRIS a releve plusieurs signaux techniques importants. Un examen prioritaire du dossier est suggere.'::text
            ELSE 'Non renseigne'::text
        END AS business_explanation,
    i.indicateur_inspection_complete,
    COALESCE(NULLIF(btrim(split_part(regexp_replace(i.agent_controle, '\s*-\s*'::text, ' - '::text), ' - '::text, 1)), ''::text), 'Non renseigne'::text) AS garage_nom,
    COALESCE(NULLIF(btrim(split_part(regexp_replace(i.agent_controle, '\s*-\s*'::text, ' - '::text), ' - '::text, 2)), ''::text), 'Non renseigne'::text) AS garage_localite,
        CASE
            WHEN v.date_inspection_sk > 19000101 THEN to_date(v.date_inspection_sk::text, 'YYYYMMDD'::text)
            ELSE NULL::date
        END AS inspection_date
   FROM mart.fact_vhs_score v
     LEFT JOIN dwh.fact_inspection_vehicule i ON i.inspection_key = v.inspection_key
  WHERE v.run_id = (( SELECT fact_vhs_score.run_id
           FROM mart.fact_vhs_score
          ORDER BY fact_vhs_score.created_at DESC, fact_vhs_score.run_id DESC
         LIMIT 1)) AND v.immatriculation_norm IS NOT NULL;

