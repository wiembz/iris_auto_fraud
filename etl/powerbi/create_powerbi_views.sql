-- ============================================================================
-- IRIS - Vues Power BI (schema powerbi_v)
-- ============================================================================
-- Couche de restitution analytique en LECTURE SEULE pour Power BI.
-- Aucune table n'est creee ni modifiee : uniquement CREATE OR REPLACE VIEW.
--
-- Principes :
--   * Power BI ne lit jamais les tables mart/dwh brutes : uniquement ces vues.
--   * La version de score est pilotee par UNE seule vue de configuration
--     (v_score_version_config). Le run le plus recent de cette version est
--     resolu automatiquement (format run_id = VERSION_YYYYMMDD_HHMMSS,
--     donc MAX() lexicographique = plus recent).
--   * Le grain dossier applique la regle de l'ADR_CLAIM_DECISION_GRAIN :
--     score dossier = MAX des scores garanties, pas de somme, pas de bonus
--     multi-garanties. (Le mart V2 dossier n'etant pas persiste, la regle
--     est implementee ici en SQL sur le score persiste.)
--   * Les cohortes clients excluent client_sk = 0 / NULL (cles non
--     identifiees, effet migration 2019) ; le taux d'exclusion est expose
--     dans v_quality_kpis.
--   * Wording non accusatoire : les libelles proviennent des tables mart,
--     deja testees.
--   * Convention d'affichage : tout champ texte nullable expose a Power BI
--     est enveloppe dans COALESCE(..., 'Non renseigne') pour eviter les
--     cellules/segments vides (Blank) cote rapport.
--   * idclt (identifiant metier client, dwh.dim_client) est expose a cote de
--     client_sk. Il n'existe PAS de nom/raison sociale client dans les
--     sources actuelles (Clients.xlsx ne contient aucun champ nom) : c'est
--     une limite de donnee source, pas un oubli de vue.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS powerbi_v;

-- ----------------------------------------------------------------------------
-- 0. Configuration : LA seule vue a modifier pour changer de version de score
--    (ex. basculer vers HYBRID ou V2 quand ils seront valides metier).
-- ----------------------------------------------------------------------------
-- Alignee sur la version servie par l'application Angular (backend/config.py :
-- DEFAULT_SCORE_VERSION) pour que les deux restitutions racontent les memes chiffres.
CREATE OR REPLACE VIEW powerbi_v.v_score_version_config AS
SELECT 'IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE'::text AS score_version;

-- Run le plus recent de la version configuree.
CREATE OR REPLACE VIEW powerbi_v.v_current_run AS
SELECT
    s.score_version,
    MAX(s.score_run_id) AS score_run_id
FROM mart.fact_claim_attention_score s
JOIN powerbi_v.v_score_version_config c
  ON s.score_version = c.score_version
GROUP BY s.score_version;

-- ----------------------------------------------------------------------------
-- 1. Grain sinistre x garantie : score + contexte features
--    (source de la page masquee de drill-through et des analyses garanties)
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW powerbi_v.v_claim_attention_guarantee AS
SELECT
    sc.claim_sk,
    sc.claim_business_id,
    split_part(sc.claim_business_id, '|', 1) AS claim_root_id,
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
    COALESCE(sc.confidence_level, 'Non renseigne') AS confidence_level,
    COALESCE(sc.main_reason_1, 'Non renseigne')    AS main_reason_1,
    COALESCE(sc.main_reason_2, 'Non renseigne')    AS main_reason_2,
    COALESCE(sc.main_reason_3, 'Non renseigne')    AS main_reason_3,
    sc.score_version,
    sc.score_run_id,
    sc.feature_run_id,
    sc.created_at,
    f.claim_geo_sk
FROM mart.fact_claim_attention_score sc
JOIN powerbi_v.v_current_run r
  ON sc.score_version = r.score_version
 AND sc.score_run_id  = r.score_run_id
LEFT JOIN mart.fact_claim_scoring_features f
  ON f.claim_sk       = sc.claim_sk
 AND f.feature_run_id = sc.feature_run_id;

-- ----------------------------------------------------------------------------
-- 2. Grain dossier : regle ADR (MAX, pas de somme)
--    Les raisons et la confiance affichees sont celles de la garantie au
--    score maximal (representant conservateur du dossier).
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW powerbi_v.v_dossier_attention AS
WITH ranked AS (
    SELECT
        g.*,
        ROW_NUMBER() OVER (
            PARTITION BY g.claim_root_id
            ORDER BY g.attention_score DESC, g.claim_sk
        ) AS rn
    FROM powerbi_v.v_claim_attention_guarantee g
),
agg AS (
    SELECT
        claim_root_id,
        COUNT(*)                        AS guarantee_row_count,
        COUNT(DISTINCT code_garantie)   AS guarantee_code_count,
        SUM(claim_amount)               AS dossier_claim_amount,
        MIN(claim_date)                 AS claim_date,
        MIN(declaration_date)           AS declaration_date
    FROM powerbi_v.v_claim_attention_guarantee
    GROUP BY claim_root_id
)
SELECT
    r.claim_root_id,
    r.numero_sinistre,
    r.attention_score      AS dossier_attention_score,
    r.attention_level      AS dossier_attention_level,
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
        CASE WHEN geo.gouvernorat = 'UNKNOWN' THEN NULL ELSE geo.gouvernorat END,
        'Non renseigne'
    ) AS gouvernorat,
    COALESCE(
        CASE WHEN geo.region = 'UNKNOWN' THEN NULL ELSE geo.region END,
        'Non renseigne'
    ) AS geo_region,
    cl.idclt                AS client_business_id
FROM ranked r
LEFT JOIN dwh.dim_geo geo
  ON geo.geo_sk = r.claim_geo_sk
LEFT JOIN dwh.dim_client cl
  ON cl.client_sk = r.client_sk
JOIN agg a ON a.claim_root_id = r.claim_root_id
WHERE r.rn = 1;

-- ----------------------------------------------------------------------------
-- 3. Details des signaux (waterfall drill-through, contributions par famille)
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW powerbi_v.v_signal_detail AS
SELECT
    d.claim_sk,
    d.claim_business_id,
    split_part(d.claim_business_id, '|', 1) AS claim_root_id,
    d.signal_family,
    d.signal_code,
    COALESCE(d.signal_label, 'Non renseigne')         AS signal_label,
    d.signal_value,
    d.points,
    d.severity,
    COALESCE(d.business_explanation, 'Non renseigne') AS business_explanation,
    d.score_version,
    d.score_run_id
FROM mart.fact_claim_attention_signal_detail d
JOIN powerbi_v.v_current_run r
  ON d.score_version = r.score_version
 AND d.score_run_id  = r.score_run_id;

-- ----------------------------------------------------------------------------
-- 4. Cohortes clients (page P3) - grain client, HORS clients non identifies.
--    "Multisinistre 12m" suit la definition du catalogue de regles
--    (>= 3 dossiers sur 12 mois, observe au moment du sinistre).
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW powerbi_v.v_client_cohort AS
SELECT
    d.client_sk,
    COUNT(DISTINCT d.claim_root_id)             AS dossier_count,
    SUM(d.dossier_claim_amount)                 AS total_claim_amount,
    MIN(d.claim_date)                           AS first_claim_date,
    MAX(d.claim_date)                           AS last_claim_date,
    MAX(d.dossier_attention_score)              AS max_attention_score,
    COUNT(DISTINCT d.claim_root_id) FILTER (
        WHERE d.dossier_attention_level IN
            ('Examen renforce suggere', 'Examen prioritaire suggere')
    )                                           AS high_attention_dossier_count,
    MAX(g.client_claim_count_12m)               AS max_claim_count_12m,
    (MAX(g.client_claim_count_12m) >= 3)        AS is_multiclaim_12m,
    MAX(d.client_business_id)                   AS idclt
FROM powerbi_v.v_dossier_attention d
LEFT JOIN powerbi_v.v_claim_attention_guarantee g
  ON g.claim_root_id = d.claim_root_id
WHERE d.client_sk IS NOT NULL
  AND d.client_sk <> 0
GROUP BY d.client_sk;

-- ----------------------------------------------------------------------------
-- 5. Inspections STAFIM (page P4) - grain inspection avec agregats checkpoints
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW powerbi_v.v_inspection AS
SELECT
    i.inspection_key,
    i.vehicule_sk,
    COALESCE(i.immatriculation_norm, 'Non renseigne') AS immatriculation_norm,
    CASE
        WHEN i.date_inspection_sk > 19000101
        THEN to_date(i.date_inspection_sk::text, 'YYYYMMDD')
    END                                          AS inspection_date,
    COUNT(c.checkpoint_code)                     AS checkpoint_count,
    COUNT(*) FILTER (WHERE c.est_anomalie)           AS defect_count,
    COUNT(*) FILTER (WHERE c.est_anomalie_critique)  AS critical_defect_count,
    i.indicateur_inspection_complete,
    -- Le champ source ("NOM DE L'AGENT") melange nom du garage et localite,
    -- ex. "HM AUTO - BIZERTE" -> garage_nom="HM AUTO", garage_localite="BIZERTE".
    COALESCE(NULLIF(BTRIM(split_part(regexp_replace(i.agent_controle, '\s*-\s*', ' - '), ' - ', 1)), ''), 'Non renseigne') AS garage_nom,
    COALESCE(NULLIF(BTRIM(split_part(regexp_replace(i.agent_controle, '\s*-\s*', ' - '), ' - ', 2)), ''), 'Non renseigne') AS garage_localite
FROM dwh.fact_inspection_vehicule i
LEFT JOIN dwh.fact_inspection_checkpoint c
  ON c.inspection_key = i.inspection_key
GROUP BY i.inspection_key, i.vehicule_sk, i.immatriculation_norm,
         i.indicateur_inspection_complete, i.date_inspection_sk, i.agent_controle;

-- Pareto des defauts par checkpoint (page P4).
CREATE OR REPLACE VIEW powerbi_v.v_inspection_checkpoint_defect AS
SELECT
    c.zone_controle,
    c.checkpoint_code,
    c.checkpoint_libelle,
    COUNT(*)                                         AS observed_count,
    COUNT(*) FILTER (WHERE c.est_anomalie)           AS defect_count,
    COUNT(*) FILTER (WHERE c.est_anomalie_critique)  AS critical_defect_count
FROM dwh.fact_inspection_checkpoint c
GROUP BY c.zone_controle, c.checkpoint_code, c.checkpoint_libelle;

-- ----------------------------------------------------------------------------
-- 6. VHS (page P4) - dernier run persiste, contexte technique uniquement.
--    Ne jamais croiser avec le niveau d'attention dans un meme visuel.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW powerbi_v.v_vhs_score AS
SELECT
    v.inspection_key,
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
    -- Le grade A-D est un code technique backend : le gestionnaire voit le
    -- libelle metier (docs/vhs/vhs_business_label_mapping.md).
    CASE v.safety_grade
        WHEN 'A' THEN 'Aucun signal technique majeur'
        WHEN 'B' THEN 'Quelques points a surveiller'
        WHEN 'C' THEN 'Degradation technique notable'
        WHEN 'D' THEN 'Situation technique sensible'
        ELSE 'Non renseigne'
    END                                          AS grade_label,
    CASE v.decision
        WHEN 'OK'         THEN 'Etat satisfaisant'
        WHEN 'DEGRADE'    THEN 'Etat a surveiller'
        WHEN 'IMMOBILISE' THEN 'Usage deconseille'
        WHEN 'CRITIQUE'   THEN 'Examen prioritaire suggere'
        ELSE 'Non renseigne'
    END                                          AS decision_label,
    -- Explication metier courte (docs/vhs/vhs_business_explanation.md,
    -- section "Lecture recommandee dans IRIS").
    CASE v.decision
        WHEN 'OK' THEN
            'Le vehicule ne presente pas de signal technique majeur dans les points analyses.'
        WHEN 'DEGRADE' THEN
            'Le vehicule presente plusieurs points techniques a surveiller. Une verification complementaire peut etre utile.'
        WHEN 'IMMOBILISE' THEN
            'IRIS a releve un point technique sensible. L''usage du vehicule est deconseille sans verification complementaire.'
        WHEN 'CRITIQUE' THEN
            'IRIS a releve plusieurs signaux techniques importants. Un examen prioritaire du dossier est suggere.'
        ELSE 'Non renseigne'
    END                                          AS business_explanation,
    i.indicateur_inspection_complete,
    COALESCE(NULLIF(BTRIM(split_part(regexp_replace(i.agent_controle, '\s*-\s*', ' - '), ' - ', 1)), ''), 'Non renseigne') AS garage_nom,
    COALESCE(NULLIF(BTRIM(split_part(regexp_replace(i.agent_controle, '\s*-\s*', ' - '), ' - ', 2)), ''), 'Non renseigne') AS garage_localite
FROM mart.fact_vhs_score v
LEFT JOIN dwh.fact_inspection_vehicule i
  ON i.inspection_key = v.inspection_key
WHERE v.run_id = (SELECT MAX(run_id) FROM mart.fact_vhs_score)
  -- Regle metier : pas de score exploitable sans immatriculation complete
  -- (le gestionnaire ne peut pas rattacher le score a un vehicule identifie).
  AND v.immatriculation_norm IS NOT NULL;

-- ----------------------------------------------------------------------------
-- 7. Croisement inspection -> sinistre (page P4) - dernier run du signal
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW powerbi_v.v_post_inspection_signal AS
SELECT
    p.claim_sk,
    p.inspection_sk,
    p.client_sk,
    p.vehicule_sk,
    p.immatriculation,
    p.inspection_date,
    p.claim_date,
    p.days_inspection_to_claim,
    p.delay_bucket,
    COALESCE(p.defective_zone, 'Non renseigne')       AS defective_zone,
    p.defective_checkpoint_count,
    p.critical_checkpoint_count,
    p.claim_guarantee_code,
    COALESCE(p.claim_guarantee_label, 'Non renseigne') AS claim_guarantee_label,
    COALESCE(p.zone_match_status, 'Non renseigne')     AS zone_match_status,
    p.attention_level,
    COALESCE(p.confidence_level, 'Non renseigne')      AS confidence_level,
    COALESCE(p.business_explanation, 'Non renseigne')  AS business_explanation,
    p.scenario_code,
    p.signal_version,
    p.signal_run_id
FROM mart.fact_post_inspection_attention_signal p
WHERE p.signal_run_id = (
    SELECT MAX(signal_run_id) FROM mart.fact_post_inspection_attention_signal
);

-- ----------------------------------------------------------------------------
-- 8. Signal ML d'atypicite (encart P2) - dernier run, signal PARALLELE.
--    Jamais fusionne dans le score metier.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW powerbi_v.v_ml_anomaly AS
SELECT
    m.claim_sk,
    m.claim_business_id,
    split_part(m.claim_business_id, '|', 1) AS claim_root_id,
    m.raw_anomaly_score,
    m.anomaly_percentile_score,
    m.score_ml,
    m.ml_attention_level,
    COALESCE(m.top_variable_1, 'Non renseigne') AS top_variable_1,
    COALESCE(m.top_variable_2, 'Non renseigne') AS top_variable_2,
    COALESCE(m.top_variable_3, 'Non renseigne') AS top_variable_3,
    m.signal_version,
    m.signal_run_id
FROM mart.fact_claim_ml_anomaly_signal m
WHERE m.signal_run_id = (
    SELECT MAX(signal_run_id) FROM mart.fact_claim_ml_anomaly_signal
);

-- ----------------------------------------------------------------------------
-- 9. KPIs qualite (page P5) - une ligne, calcules sur le run courant
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW powerbi_v.v_quality_kpis AS
SELECT
    COUNT(*)                                                    AS guarantee_rows,
    COUNT(DISTINCT split_part(sc.claim_business_id, '|', 1))    AS dossier_count,
    AVG(CASE WHEN f.client_sk IS NULL OR f.client_sk = 0
             THEN 1.0 ELSE 0.0 END)                             AS pct_unknown_client,
    AVG(CASE WHEN f.missing_vehicle_flag THEN 1.0 ELSE 0.0 END) AS pct_missing_vehicle,
    AVG(CASE WHEN f.invalid_claim_date_flag
               OR f.invalid_declaration_date_flag
             THEN 1.0 ELSE 0.0 END)                             AS pct_invalid_dates,
    AVG(CASE WHEN f.migration_2019_flag THEN 1.0 ELSE 0.0 END)  AS pct_migration_2019,
    AVG(CASE WHEN sc.confidence_level = 'HIGH'
             THEN 1.0 ELSE 0.0 END)                             AS pct_confidence_high,
    (SELECT AVG(CASE WHEN v2.immatriculation_norm IS NULL THEN 1.0 ELSE 0.0 END)
       FROM mart.fact_vhs_score v2
      WHERE v2.run_id = (SELECT MAX(run_id) FROM mart.fact_vhs_score)
    )                                                            AS pct_vhs_missing_immatriculation
FROM mart.fact_claim_attention_score sc
JOIN powerbi_v.v_current_run r
  ON sc.score_version = r.score_version
 AND sc.score_run_id  = r.score_run_id
LEFT JOIN mart.fact_claim_scoring_features f
  ON f.claim_sk       = sc.claim_sk
 AND f.feature_run_id = sc.feature_run_id;

-- ----------------------------------------------------------------------------
-- 10. Gouvernance (page P5) - versions et runs affiches dans le rapport
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW powerbi_v.v_governance AS
SELECT
    'CLAIM_ATTENTION'::text AS component,
    r.score_version         AS version,
    r.score_run_id          AS run_id,
    (SELECT MAX(created_at) FROM mart.fact_claim_attention_score s
      WHERE s.score_run_id = r.score_run_id) AS created_at,
    (SELECT COUNT(*) FROM mart.fact_claim_attention_score s
      WHERE s.score_run_id = r.score_run_id) AS row_count
FROM powerbi_v.v_current_run r
UNION ALL
SELECT
    'ML_ANOMALY',
    MAX(signal_version),
    MAX(signal_run_id),
    MAX(created_at),
    COUNT(*) FILTER (WHERE signal_run_id =
        (SELECT MAX(signal_run_id) FROM mart.fact_claim_ml_anomaly_signal))
FROM mart.fact_claim_ml_anomaly_signal
UNION ALL
SELECT
    'POST_INSPECTION',
    MAX(signal_version),
    MAX(signal_run_id),
    MAX(created_at),
    COUNT(*) FILTER (WHERE signal_run_id =
        (SELECT MAX(signal_run_id) FROM mart.fact_post_inspection_attention_signal))
FROM mart.fact_post_inspection_attention_signal
UNION ALL
SELECT
    'VHS',
    MAX(rule_version),
    MAX(run_id),
    MAX(created_at),
    COUNT(*) FILTER (WHERE run_id = (SELECT MAX(run_id) FROM mart.fact_vhs_score))
FROM mart.fact_vhs_score;

-- ----------------------------------------------------------------------------
-- Acces lecture seule pour Power BI (a executer par un administrateur ;
-- adapter le nom du role et le mot de passe hors script versionne).
-- ----------------------------------------------------------------------------
-- CREATE ROLE powerbi_reader LOGIN PASSWORD '<a-definir-hors-repo>';
-- GRANT USAGE ON SCHEMA powerbi_v TO powerbi_reader;
-- GRANT SELECT ON ALL TABLES IN SCHEMA powerbi_v TO powerbi_reader;
-- ALTER DEFAULT PRIVILEGES IN SCHEMA powerbi_v GRANT SELECT ON TABLES TO powerbi_reader;
