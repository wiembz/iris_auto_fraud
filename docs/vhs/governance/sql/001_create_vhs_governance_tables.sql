-- =============================================================================
-- IRIS_AUTO_FRAUD — VHS Governance Tables
-- DESIGN SQL ONLY
-- DO NOT EXECUTE WITHOUT PROJECT / BNA VALIDATION
--
-- This file documents the proposed DDL for the VHS governance layer.
-- It is not an executed migration.
-- It must be reviewed before any database deployment.
-- =============================================================================
--
-- Référence architecture : docs/vhs/governance/vhs_human_in_the_loop_and_history_architecture.md
-- Référence design       : docs/vhs/governance/vhs_governance_table_design.md
-- Moteur VHS actif       : etl/mart/compute_vhs_v3_candidate.py  (non modifié)
-- Profil validé          : VHS_BALANCED_V3_CANDIDATE
-- Date de rédaction      : 2026-07-04
-- Dialecte               : PostgreSQL 13+
--
-- Tables proposées :
--   1. mart.dim_vhs_rule_version
--   2. mart.fact_vhs_score_history
--   3. mart.fact_vhs_penalty_detail_history
--   4. mart.vhs_human_review
--   5. mart.vhs_stability_metrics
-- =============================================================================


-- =============================================================================
-- SCHEMA
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS mart;


-- =============================================================================
-- 1. mart.dim_vhs_rule_version
--    Référentiel des versions de règles VHS.
--    Chaque ligne correspond à un profil/version de calcul.
--    Toute modification du moteur VHS doit créer une nouvelle entrée
--    avant l'exécution d'un nouveau run.
-- =============================================================================

CREATE TABLE IF NOT EXISTS mart.dim_vhs_rule_version (

    rule_version_id     BIGSERIAL       NOT NULL,
    profile_name        VARCHAR(100)    NOT NULL,
    rule_version_label  VARCHAR(150)    NOT NULL,
    active_script       VARCHAR(255)    NOT NULL,
    description         TEXT            NULL,
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by          VARCHAR(100)    NULL,
    is_active           BOOLEAN         NOT NULL DEFAULT FALSE,
    notes               TEXT            NULL,

    CONSTRAINT pk_dim_vhs_rule_version
        PRIMARY KEY (rule_version_id),

    CONSTRAINT chk_dim_vhs_rule_version_profile_name_nonempty
        CHECK (TRIM(profile_name) <> ''),

    CONSTRAINT chk_dim_vhs_rule_version_script_nonempty
        CHECK (TRIM(active_script) <> '')
);

-- Index : recherche par profil
CREATE INDEX IF NOT EXISTS idx_dim_vhs_rule_version_profile_name
    ON mart.dim_vhs_rule_version (profile_name);

-- Index : filtrage par version active
CREATE INDEX IF NOT EXISTS idx_dim_vhs_rule_version_is_active
    ON mart.dim_vhs_rule_version (is_active);

-- Contrainte partielle : une seule version active par profil
CREATE UNIQUE INDEX IF NOT EXISTS uq_dim_vhs_rule_version_active_profile
    ON mart.dim_vhs_rule_version (profile_name)
    WHERE is_active = TRUE;

-- Commentaires
COMMENT ON TABLE  mart.dim_vhs_rule_version IS
    'Référentiel des versions de règles VHS. Une ligne par version de profil de calcul. '
    'Toute modification du moteur VHS exige une nouvelle entrée avant exécution.';
COMMENT ON COLUMN mart.dim_vhs_rule_version.rule_version_id IS
    'Identifiant technique auto-incrémenté.';
COMMENT ON COLUMN mart.dim_vhs_rule_version.profile_name IS
    'Nom du profil VHS (ex. VHS_BALANCED_V3_CANDIDATE). Unique pour is_active = TRUE.';
COMMENT ON COLUMN mart.dim_vhs_rule_version.active_script IS
    'Chemin du script de calcul actif (relatif à la racine du projet).';
COMMENT ON COLUMN mart.dim_vhs_rule_version.is_active IS
    'TRUE = version actuellement active pour ce profil. '
    'Une seule ligne active par profile_name (garanti par index partiel unique).';
COMMENT ON COLUMN mart.dim_vhs_rule_version.description IS
    'Description des changements introduits par cette version.';


-- Exemple de valeur initiale (COMMENTÉ — ne pas exécuter sans validation)
--
-- INSERT INTO mart.dim_vhs_rule_version (
--     profile_name,
--     rule_version_label,
--     active_script,
--     description,
--     created_by,
--     is_active,
--     notes
-- )
-- VALUES (
--     'VHS_BALANCED_V3_CANDIDATE',
--     'V3 candidate finale — correction Usage déconseillé',
--     'etl/mart/compute_vhs_v3_candidate.py',
--     'Correctif IMMOBILISE : exige is_immobilizing=TRUE ET observed_status=BROKEN simultanément. '
--     'Réduction de 25 à 13 cas Usage déconseillé. 286 inspections validées à 0 anomalie de mapping.',
--     'iris_etl_team',
--     TRUE,
--     'Run de référence : VHS_BALANCED_V3_CANDIDATE_20260703_181257'
-- );


-- =============================================================================
-- 2. mart.fact_vhs_score_history
--    Table de faits en append-only.
--    Chaque ligne = un score VHS calculé pour une inspection et un run donné.
--    Les lignes historiques ne sont jamais supprimées.
--    is_current = TRUE identifie le score le plus récent par inspection/profil.
-- =============================================================================

CREATE TABLE IF NOT EXISTS mart.fact_vhs_score_history (

    vhs_score_history_id    BIGSERIAL       NOT NULL,
    run_id                  VARCHAR(120)    NOT NULL,
    profile_name            VARCHAR(100)    NOT NULL,
    rule_version_id         BIGINT          NULL,
    inspection_id           VARCHAR(120)    NOT NULL,
    vehicle_key             VARCHAR(120)    NULL,
    score_value             NUMERIC(5,2)    NOT NULL,
    technical_grade         CHAR(1)         NOT NULL,
    business_grade_label    VARCHAR(100)    NOT NULL,
    technical_decision      VARCHAR(30)     NOT NULL,
    business_decision_label VARCHAR(100)    NOT NULL,
    score_created_at        TIMESTAMP       NOT NULL,
    loaded_at               TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_current              BOOLEAN         NOT NULL DEFAULT FALSE,

    CONSTRAINT pk_fact_vhs_score_history
        PRIMARY KEY (vhs_score_history_id),

    CONSTRAINT fk_fact_vhs_score_history_rule_version
        FOREIGN KEY (rule_version_id)
        REFERENCES mart.dim_vhs_rule_version (rule_version_id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,

    CONSTRAINT uq_fact_vhs_score_history_run_inspection
        UNIQUE (run_id, inspection_id, profile_name),

    CONSTRAINT chk_fact_vhs_score_history_score_range
        CHECK (score_value BETWEEN 0 AND 100),

    CONSTRAINT chk_fact_vhs_score_history_grade
        CHECK (technical_grade IN ('A', 'B', 'C', 'D')),

    CONSTRAINT chk_fact_vhs_score_history_decision
        CHECK (technical_decision IN ('OK', 'DEGRADE', 'IMMOBILISE', 'CRITIQUE')),

    CONSTRAINT chk_fact_vhs_score_history_business_label
        CHECK (business_decision_label IN (
            'État satisfaisant',
            'État à surveiller',
            'Usage déconseillé',
            'Examen prioritaire suggéré'
        ))
);

-- Index : recherche par inspection
CREATE INDEX IF NOT EXISTS idx_vhs_score_history_inspection
    ON mart.fact_vhs_score_history (inspection_id);

-- Index : recherche par run
CREATE INDEX IF NOT EXISTS idx_vhs_score_history_run
    ON mart.fact_vhs_score_history (run_id);

-- Index : accès rapide aux scores courants
CREATE INDEX IF NOT EXISTS idx_vhs_score_history_current
    ON mart.fact_vhs_score_history (is_current);

-- Index : filtrage par niveau d'attention (libellé métier)
CREATE INDEX IF NOT EXISTS idx_vhs_score_history_decision
    ON mart.fact_vhs_score_history (business_decision_label);

-- Index : recherche par date de calcul
CREATE INDEX IF NOT EXISTS idx_vhs_score_history_created_at
    ON mart.fact_vhs_score_history (score_created_at);

-- Contrainte partielle : un seul score courant par inspection et profil
CREATE UNIQUE INDEX IF NOT EXISTS uq_vhs_score_current_inspection_profile
    ON mart.fact_vhs_score_history (inspection_id, profile_name)
    WHERE is_current = TRUE;

-- Commentaires
COMMENT ON TABLE  mart.fact_vhs_score_history IS
    'Table de faits append-only. Stocke chaque score VHS calculé par run et inspection. '
    'Les lignes historiques sont immuables. is_current = TRUE identifie le score le plus récent.';
COMMENT ON COLUMN mart.fact_vhs_score_history.run_id IS
    'Identifiant du run VHS ayant produit ce score '
    '(ex. VHS_BALANCED_V3_CANDIDATE_20260703_181257).';
COMMENT ON COLUMN mart.fact_vhs_score_history.score_value IS
    'Score VHS calculé, compris entre 0.00 et 100.00.';
COMMENT ON COLUMN mart.fact_vhs_score_history.technical_decision IS
    'Décision technique interne du moteur VHS : OK, DEGRADE, IMMOBILISE, CRITIQUE.';
COMMENT ON COLUMN mart.fact_vhs_score_history.business_decision_label IS
    'Libellé métier affiché aux utilisateurs. '
    'Ne jamais exposer technical_decision dans les interfaces non techniques.';
COMMENT ON COLUMN mart.fact_vhs_score_history.is_current IS
    'TRUE = score le plus récent pour cette inspection et ce profil. '
    'Avant d''insérer un nouveau score courant, mettre is_current = FALSE sur la ligne précédente. '
    'Ne jamais supprimer les lignes historiques.';
COMMENT ON COLUMN mart.fact_vhs_score_history.rule_version_id IS
    'Référence à dim_vhs_rule_version. NULL si la version n''a pas encore été enregistrée.';


-- =============================================================================
-- 3. mart.fact_vhs_penalty_detail_history
--    Table de faits append-only.
--    Chaque ligne = une pénalité checkpoint pour une inspection et un run.
--    Explication score par score, checkpoint par checkpoint.
--    Relation logique : run_id + inspection_id + profile_name
--    → mart.fact_vhs_score_history
-- =============================================================================

CREATE TABLE IF NOT EXISTS mart.fact_vhs_penalty_detail_history (

    vhs_penalty_detail_history_id   BIGSERIAL       NOT NULL,
    run_id                          VARCHAR(120)    NOT NULL,
    profile_name                    VARCHAR(100)    NOT NULL,
    inspection_id                   VARCHAR(120)    NOT NULL,
    checkpoint_code                 VARCHAR(150)    NOT NULL,
    checkpoint_label                VARCHAR(255)    NULL,
    raw_value                       VARCHAR(255)    NULL,
    normalized_status               VARCHAR(50)     NOT NULL,
    business_status_label           VARCHAR(100)    NOT NULL,
    penalty_value                   NUMERIC(8,2)    NOT NULL,
    penalty_abs                     NUMERIC(8,2)    NOT NULL,
    tier                            VARCHAR(50)     NULL,
    is_immobilizing                 BOOLEAN         NULL,
    is_critical_functional          BOOLEAN         NULL,
    loaded_at                       TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_fact_vhs_penalty_detail_history
        PRIMARY KEY (vhs_penalty_detail_history_id),

    CONSTRAINT uq_fact_vhs_penalty_history_run_insp_ckpt
        UNIQUE (run_id, inspection_id, checkpoint_code),

    CONSTRAINT chk_fact_vhs_penalty_history_status
        CHECK (normalized_status IN (
            'OK', 'WORN', 'WORN_STRONG', 'BROKEN', 'REPAIRED', 'UNKNOWN'
        )),

    CONSTRAINT chk_fact_vhs_penalty_history_penalty_abs
        CHECK (penalty_abs >= 0),

    CONSTRAINT chk_fact_vhs_penalty_history_business_label
        CHECK (business_status_label IN (
            'Élément conforme',
            'Usure observée',
            'Intervention conseillée',
            'Défaut confirmé',
            'Élément réparé',
            'Information non exploitable'
        ))

    -- Note : pas de clé étrangère composite sur fact_vhs_score_history.
    -- La jointure logique s'effectue via (run_id, inspection_id, profile_name).
    -- Cette convention évite une clé composite difficile à maintenir.
);

-- Index : recherche par inspection
CREATE INDEX IF NOT EXISTS idx_vhs_penalty_history_inspection
    ON mart.fact_vhs_penalty_detail_history (inspection_id);

-- Index : recherche par run
CREATE INDEX IF NOT EXISTS idx_vhs_penalty_history_run
    ON mart.fact_vhs_penalty_detail_history (run_id);

-- Index : filtrage par statut normalisé
CREATE INDEX IF NOT EXISTS idx_vhs_penalty_history_status
    ON mart.fact_vhs_penalty_detail_history (normalized_status);

-- Index : tri par pénalité décroissante (top N pénalités)
CREATE INDEX IF NOT EXISTS idx_vhs_penalty_history_penalty_abs
    ON mart.fact_vhs_penalty_detail_history (penalty_abs DESC);

-- Index partiel : checkpoints immobilisants seulement
CREATE INDEX IF NOT EXISTS idx_vhs_penalty_history_immobilizing
    ON mart.fact_vhs_penalty_detail_history (is_immobilizing)
    WHERE is_immobilizing = TRUE;

-- Commentaires
COMMENT ON TABLE  mart.fact_vhs_penalty_detail_history IS
    'Table de faits append-only. Stocke le détail des pénalités checkpoint par checkpoint '
    'pour chaque score VHS. Répond à la question : pourquoi le score a-t-il diminué ? '
    'Jointure logique avec fact_vhs_score_history via (run_id, inspection_id, profile_name).';
COMMENT ON COLUMN mart.fact_vhs_penalty_detail_history.normalized_status IS
    'Statut normalisé interne du moteur VHS. '
    'Ne pas exposer directement dans les interfaces utilisateurs. '
    'Utiliser business_status_label pour l''affichage.';
COMMENT ON COLUMN mart.fact_vhs_penalty_detail_history.business_status_label IS
    'Libellé métier du statut checkpoint. '
    'Correspondances officielles : OK→Élément conforme, WORN→Usure observée, '
    'WORN_STRONG→Intervention conseillée, BROKEN→Défaut confirmé, '
    'REPAIRED→Élément réparé, UNKNOWN→Information non exploitable.';
COMMENT ON COLUMN mart.fact_vhs_penalty_detail_history.is_immobilizing IS
    'TRUE si ce checkpoint peut déclencher le niveau Usage déconseillé '
    'lorsque normalized_status = BROKEN (règle V3).';


-- =============================================================================
-- 4. mart.vhs_human_review
--    Table de workflow pour la validation humaine des propositions VHS.
--    La revue humaine ne modifie JAMAIS le score VHS original.
--    Elle stocke la réponse de l''expert à côté du score calculé.
-- =============================================================================

CREATE TABLE IF NOT EXISTS mart.vhs_human_review (

    review_id               BIGSERIAL       NOT NULL,
    run_id                  VARCHAR(120)    NOT NULL,
    profile_name            VARCHAR(100)    NOT NULL,
    inspection_id           VARCHAR(120)    NOT NULL,
    vhs_score_value         NUMERIC(5,2)    NOT NULL,
    vhs_technical_decision  VARCHAR(30)     NOT NULL,
    vhs_business_label      VARCHAR(100)    NOT NULL,
    expert_decision         VARCHAR(30)     NULL,
    expert_decision_label   VARCHAR(100)    NULL,
    review_status           VARCHAR(30)     NOT NULL DEFAULT 'PENDING',
    reviewer_role           VARCHAR(50)     NULL,
    reviewed_by             VARCHAR(120)    NULL,
    reviewed_at             TIMESTAMP       NULL,
    review_comment          TEXT            NULL,
    correction_reason       VARCHAR(255)    NULL,
    created_at              TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP       NULL,

    CONSTRAINT pk_vhs_human_review
        PRIMARY KEY (review_id),

    CONSTRAINT uq_vhs_human_review_run_inspection_profile
        UNIQUE (run_id, inspection_id, profile_name),

    CONSTRAINT chk_vhs_human_review_score_range
        CHECK (vhs_score_value BETWEEN 0 AND 100),

    CONSTRAINT chk_vhs_human_review_vhs_decision
        CHECK (vhs_technical_decision IN ('OK', 'DEGRADE', 'IMMOBILISE', 'CRITIQUE')),

    CONSTRAINT chk_vhs_human_review_vhs_business_label
        CHECK (vhs_business_label IN (
            'État satisfaisant',
            'État à surveiller',
            'Usage déconseillé',
            'Examen prioritaire suggéré'
        )),

    CONSTRAINT chk_vhs_human_review_status
        CHECK (review_status IN (
            'PENDING', 'CONFIRMED', 'CORRECTED', 'REJECTED', 'NEEDS_MORE_INFO'
        )),

    CONSTRAINT chk_vhs_human_review_expert_decision
        CHECK (expert_decision IS NULL
            OR expert_decision IN ('OK', 'DEGRADE', 'IMMOBILISE', 'CRITIQUE')),

    CONSTRAINT chk_vhs_human_review_expert_label
        CHECK (expert_decision_label IS NULL
            OR expert_decision_label IN (
                'État satisfaisant',
                'État à surveiller',
                'Usage déconseillé',
                'Examen prioritaire suggéré'
            )),

    -- Règle de cohérence : toute revue non-PENDING doit avoir une date
    CONSTRAINT chk_vhs_human_review_reviewed_at_required
        CHECK (review_status = 'PENDING' OR reviewed_at IS NOT NULL),

    -- Règle de cohérence : CORRECTED exige un motif de correction
    CONSTRAINT chk_vhs_human_review_corrected_reason
        CHECK (review_status <> 'CORRECTED' OR correction_reason IS NOT NULL),

    -- Règle de cohérence : CONFIRMED exige expert_decision = vhs_technical_decision
    CONSTRAINT chk_vhs_human_review_confirmed_coherence
        CHECK (review_status <> 'CONFIRMED'
            OR expert_decision = vhs_technical_decision),

    -- Règle de cohérence : CORRECTED exige expert_decision <> vhs_technical_decision
    CONSTRAINT chk_vhs_human_review_corrected_coherence
        CHECK (review_status <> 'CORRECTED'
            OR expert_decision <> vhs_technical_decision),

    -- Règle de cohérence : REJECTED exige un commentaire
    CONSTRAINT chk_vhs_human_review_rejected_comment
        CHECK (review_status <> 'REJECTED' OR review_comment IS NOT NULL),

    -- Règle de cohérence : NEEDS_MORE_INFO exige un commentaire
    CONSTRAINT chk_vhs_human_review_needs_info_comment
        CHECK (review_status <> 'NEEDS_MORE_INFO' OR review_comment IS NOT NULL),

    -- Règle de cohérence : PENDING ne doit pas avoir de date de revue
    CONSTRAINT chk_vhs_human_review_pending_no_date
        CHECK (review_status <> 'PENDING' OR reviewed_at IS NULL)
);

-- Index : filtrage par statut de revue (file de traitement)
CREATE INDEX IF NOT EXISTS idx_vhs_human_review_status
    ON mart.vhs_human_review (review_status);

-- Index : recherche par inspection
CREATE INDEX IF NOT EXISTS idx_vhs_human_review_inspection
    ON mart.vhs_human_review (inspection_id);

-- Index : recherche par relecteur
CREATE INDEX IF NOT EXISTS idx_vhs_human_review_reviewer
    ON mart.vhs_human_review (reviewed_by);

-- Index : tri par date de revue
CREATE INDEX IF NOT EXISTS idx_vhs_human_review_reviewed_at
    ON mart.vhs_human_review (reviewed_at);

-- Index : filtrage par niveau d'attention proposé
CREATE INDEX IF NOT EXISTS idx_vhs_human_review_decision
    ON mart.vhs_human_review (vhs_business_label);

-- Commentaires
COMMENT ON TABLE  mart.vhs_human_review IS
    'Table de workflow pour la validation humaine des propositions VHS. '
    'La revue humaine ne modifie JAMAIS le score original dans fact_vhs_score_history. '
    'Elle stocke la décision de l''expert à côté du score calculé pour une traçabilité complète.';
COMMENT ON COLUMN mart.vhs_human_review.review_status IS
    'Statut de la revue : '
    'PENDING (en attente), CONFIRMED (confirmé), CORRECTED (corrigé), '
    'REJECTED (rejeté), NEEDS_MORE_INFO (information complémentaire demandée).';
COMMENT ON COLUMN mart.vhs_human_review.expert_decision IS
    'Décision retenue par l''expert (code technique). '
    'NULL tant que review_status = PENDING. '
    'Doit être identique à vhs_technical_decision si CONFIRMED, différent si CORRECTED.';
COMMENT ON COLUMN mart.vhs_human_review.correction_reason IS
    'Motif de correction. Obligatoire lorsque review_status = CORRECTED.';
COMMENT ON COLUMN mart.vhs_human_review.vhs_score_value IS
    'Copie immuable du score VHS proposé au moment de la création de la revue. '
    'Ne pas mettre à jour ce champ.';


-- =============================================================================
-- 5. mart.vhs_stability_metrics
--    Table d''agrégation.
--    Stocke les indicateurs de fiabilité métier des propositions VHS
--    calculés à partir de vhs_human_review sur une période donnée.
-- =============================================================================

CREATE TABLE IF NOT EXISTS mart.vhs_stability_metrics (

    metric_id                   BIGSERIAL       NOT NULL,
    metric_period_start         DATE            NOT NULL,
    metric_period_end           DATE            NOT NULL,
    profile_name                VARCHAR(100)    NOT NULL,
    business_decision_label     VARCHAR(100)    NOT NULL,
    proposed_count              INTEGER         NOT NULL DEFAULT 0,
    confirmed_count             INTEGER         NOT NULL DEFAULT 0,
    corrected_count             INTEGER         NOT NULL DEFAULT 0,
    rejected_count              INTEGER         NOT NULL DEFAULT 0,
    needs_more_info_count       INTEGER         NOT NULL DEFAULT 0,
    confirmation_rate           NUMERIC(6,4)    NULL,
    correction_rate             NUMERIC(6,4)    NULL,
    rejection_rate              NUMERIC(6,4)    NULL,
    needs_more_info_rate        NUMERIC(6,4)    NULL,
    top_corrected_checkpoint    VARCHAR(255)    NULL,
    created_at                  TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_vhs_stability_metrics
        PRIMARY KEY (metric_id),

    CONSTRAINT uq_vhs_stability_metrics_period_profile_label
        UNIQUE (metric_period_start, metric_period_end, profile_name, business_decision_label),

    CONSTRAINT chk_vhs_stability_metrics_period_order
        CHECK (metric_period_end >= metric_period_start),

    CONSTRAINT chk_vhs_stability_metrics_proposed_count
        CHECK (proposed_count >= 0),

    CONSTRAINT chk_vhs_stability_metrics_confirmed_count
        CHECK (confirmed_count >= 0 AND confirmed_count <= proposed_count),

    CONSTRAINT chk_vhs_stability_metrics_corrected_count
        CHECK (corrected_count >= 0 AND corrected_count <= proposed_count),

    CONSTRAINT chk_vhs_stability_metrics_rejected_count
        CHECK (rejected_count >= 0 AND rejected_count <= proposed_count),

    CONSTRAINT chk_vhs_stability_metrics_needs_more_info_count
        CHECK (needs_more_info_count >= 0 AND needs_more_info_count <= proposed_count),

    CONSTRAINT chk_vhs_stability_metrics_confirmation_rate
        CHECK (confirmation_rate IS NULL
            OR confirmation_rate BETWEEN 0 AND 1),

    CONSTRAINT chk_vhs_stability_metrics_correction_rate
        CHECK (correction_rate IS NULL
            OR correction_rate BETWEEN 0 AND 1),

    CONSTRAINT chk_vhs_stability_metrics_rejection_rate
        CHECK (rejection_rate IS NULL
            OR rejection_rate BETWEEN 0 AND 1),

    CONSTRAINT chk_vhs_stability_metrics_needs_more_info_rate
        CHECK (needs_more_info_rate IS NULL
            OR needs_more_info_rate BETWEEN 0 AND 1),

    CONSTRAINT chk_vhs_stability_metrics_business_label
        CHECK (business_decision_label IN (
            'État satisfaisant',
            'État à surveiller',
            'Usage déconseillé',
            'Examen prioritaire suggéré'
        ))
);

-- Index : filtrage par période
CREATE INDEX IF NOT EXISTS idx_vhs_stability_period
    ON mart.vhs_stability_metrics (metric_period_start, metric_period_end);

-- Index : filtrage par profil
CREATE INDEX IF NOT EXISTS idx_vhs_stability_profile
    ON mart.vhs_stability_metrics (profile_name);

-- Index : filtrage par niveau d'attention
CREATE INDEX IF NOT EXISTS idx_vhs_stability_label
    ON mart.vhs_stability_metrics (business_decision_label);

-- Commentaires
COMMENT ON TABLE  mart.vhs_stability_metrics IS
    'Indicateurs de fiabilité métier des propositions VHS, calculés par période '
    'à partir de mart.vhs_human_review. '
    'Un taux de correction > 20 % sur un niveau d''attention doit déclencher une revue des règles.';
COMMENT ON COLUMN mart.vhs_stability_metrics.confirmation_rate IS
    'Taux de confirmation = confirmed_count / proposed_count. '
    'NULL si proposed_count = 0. Valeur entre 0 et 1.';
COMMENT ON COLUMN mart.vhs_stability_metrics.correction_rate IS
    'Taux de correction = corrected_count / proposed_count. '
    'Un taux > 0.20 sur Usage déconseillé indique un recalibrage potentiel de is_immobilizing.';
COMMENT ON COLUMN mart.vhs_stability_metrics.top_corrected_checkpoint IS
    'Code ou libellé du checkpoint le plus fréquemment à l''origine des corrections '
    'sur la période analysée. Calculé en batch depuis fact_vhs_penalty_detail_history.';


-- =============================================================================
-- REQUÊTES DE CONTRÔLE QUALITÉ DES DONNÉES
-- TOUTES COMMENTÉES — NE PAS EXÉCUTER SANS ANALYSE PRÉALABLE
-- =============================================================================

-- -----------------------------------------------------------------------------
-- A. Contrôles — mart.dim_vhs_rule_version
-- -----------------------------------------------------------------------------

-- A1. Nombre de versions actives par profil (doit être = 1 par profil)
-- SELECT profile_name, COUNT(*) AS active_versions
-- FROM mart.dim_vhs_rule_version
-- WHERE is_active = TRUE
-- GROUP BY profile_name
-- HAVING COUNT(*) <> 1;

-- A2. Lignes avec active_script vide ou NULL
-- SELECT rule_version_id, profile_name, active_script
-- FROM mart.dim_vhs_rule_version
-- WHERE TRIM(COALESCE(active_script, '')) = '';

-- A3. Profils avec plusieurs versions actives (doublons)
-- SELECT profile_name, COUNT(*) AS cnt
-- FROM mart.dim_vhs_rule_version
-- WHERE is_active = TRUE
-- GROUP BY profile_name
-- HAVING COUNT(*) > 1;


-- -----------------------------------------------------------------------------
-- B. Contrôles — mart.fact_vhs_score_history
-- -----------------------------------------------------------------------------

-- B1. Scores hors plage [0, 100]
-- SELECT vhs_score_history_id, inspection_id, run_id, score_value
-- FROM mart.fact_vhs_score_history
-- WHERE score_value < 0 OR score_value > 100;

-- B2. Décisions techniques invalides
-- SELECT vhs_score_history_id, inspection_id, technical_decision
-- FROM mart.fact_vhs_score_history
-- WHERE technical_decision NOT IN ('OK', 'DEGRADE', 'IMMOBILISE', 'CRITIQUE');

-- B3. Libellés métier manquants ou vides
-- SELECT vhs_score_history_id, inspection_id, business_decision_label
-- FROM mart.fact_vhs_score_history
-- WHERE TRIM(COALESCE(business_decision_label, '')) = '';

-- B4. Doublons (run_id, inspection_id, profile_name)
-- SELECT run_id, inspection_id, profile_name, COUNT(*) AS cnt
-- FROM mart.fact_vhs_score_history
-- GROUP BY run_id, inspection_id, profile_name
-- HAVING COUNT(*) > 1;

-- B5. Plus d'un score courant par inspection/profil
-- SELECT inspection_id, profile_name, COUNT(*) AS cnt
-- FROM mart.fact_vhs_score_history
-- WHERE is_current = TRUE
-- GROUP BY inspection_id, profile_name
-- HAVING COUNT(*) > 1;


-- -----------------------------------------------------------------------------
-- C. Contrôles — mart.fact_vhs_penalty_detail_history
-- -----------------------------------------------------------------------------

-- C1. Statuts normalisés invalides
-- SELECT vhs_penalty_detail_history_id, inspection_id, normalized_status
-- FROM mart.fact_vhs_penalty_detail_history
-- WHERE normalized_status NOT IN ('OK', 'WORN', 'WORN_STRONG', 'BROKEN', 'REPAIRED', 'UNKNOWN');

-- C2. Libellés métier manquants ou vides
-- SELECT vhs_penalty_detail_history_id, inspection_id, business_status_label
-- FROM mart.fact_vhs_penalty_detail_history
-- WHERE TRIM(COALESCE(business_status_label, '')) = '';

-- C3. Pénalités absolues négatives
-- SELECT vhs_penalty_detail_history_id, inspection_id, penalty_abs
-- FROM mart.fact_vhs_penalty_detail_history
-- WHERE penalty_abs < 0;

-- C4. Lignes BROKEN sans libellé 'Défaut confirmé'
-- SELECT vhs_penalty_detail_history_id, inspection_id, normalized_status, business_status_label
-- FROM mart.fact_vhs_penalty_detail_history
-- WHERE normalized_status = 'BROKEN'
--   AND business_status_label <> 'Défaut confirmé';

-- C5. Lignes WORN_STRONG sans libellé 'Intervention conseillée'
-- SELECT vhs_penalty_detail_history_id, inspection_id, normalized_status, business_status_label
-- FROM mart.fact_vhs_penalty_detail_history
-- WHERE normalized_status = 'WORN_STRONG'
--   AND business_status_label <> 'Intervention conseillée';

-- C6. Lignes orphelines (sans score correspondant dans fact_vhs_score_history)
-- SELECT p.inspection_id, p.run_id, p.profile_name
-- FROM mart.fact_vhs_penalty_detail_history p
-- LEFT JOIN mart.fact_vhs_score_history s
--     ON p.run_id = s.run_id
--    AND p.inspection_id = s.inspection_id
--    AND p.profile_name = s.profile_name
-- WHERE s.vhs_score_history_id IS NULL;


-- -----------------------------------------------------------------------------
-- D. Contrôles — mart.vhs_human_review
-- -----------------------------------------------------------------------------

-- D1. Statuts de revue invalides
-- SELECT review_id, inspection_id, review_status
-- FROM mart.vhs_human_review
-- WHERE review_status NOT IN (
--     'PENDING', 'CONFIRMED', 'CORRECTED', 'REJECTED', 'NEEDS_MORE_INFO'
-- );

-- D2. Revues non-PENDING sans date de revue
-- SELECT review_id, inspection_id, review_status, reviewed_at
-- FROM mart.vhs_human_review
-- WHERE review_status <> 'PENDING'
--   AND reviewed_at IS NULL;

-- D3. Revues CORRECTED sans motif
-- SELECT review_id, inspection_id, review_status, correction_reason
-- FROM mart.vhs_human_review
-- WHERE review_status = 'CORRECTED'
--   AND (correction_reason IS NULL OR TRIM(correction_reason) = '');

-- D4. Revues CONFIRMED où expert_decision diffère de vhs_technical_decision
-- SELECT review_id, inspection_id, vhs_technical_decision, expert_decision
-- FROM mart.vhs_human_review
-- WHERE review_status = 'CONFIRMED'
--   AND expert_decision <> vhs_technical_decision;

-- D5. Revues PENDING avec date de revue renseignée
-- SELECT review_id, inspection_id, review_status, reviewed_at
-- FROM mart.vhs_human_review
-- WHERE review_status = 'PENDING'
--   AND reviewed_at IS NOT NULL;


-- -----------------------------------------------------------------------------
-- E. Contrôles — mart.vhs_stability_metrics
-- -----------------------------------------------------------------------------

-- E1. Taux hors plage [0, 1]
-- SELECT metric_id, profile_name, business_decision_label,
--        confirmation_rate, correction_rate, rejection_rate, needs_more_info_rate
-- FROM mart.vhs_stability_metrics
-- WHERE confirmation_rate    NOT BETWEEN 0 AND 1
--    OR correction_rate      NOT BETWEEN 0 AND 1
--    OR rejection_rate       NOT BETWEEN 0 AND 1
--    OR needs_more_info_rate NOT BETWEEN 0 AND 1;

-- E2. Compteurs dépassant proposed_count
-- SELECT metric_id, profile_name, business_decision_label,
--        proposed_count, confirmed_count, corrected_count,
--        rejected_count, needs_more_info_count
-- FROM mart.vhs_stability_metrics
-- WHERE confirmed_count      > proposed_count
--    OR corrected_count      > proposed_count
--    OR rejected_count       > proposed_count
--    OR needs_more_info_count > proposed_count;

-- E3. Doublons de période/profil/libellé
-- SELECT metric_period_start, metric_period_end, profile_name,
--        business_decision_label, COUNT(*) AS cnt
-- FROM mart.vhs_stability_metrics
-- GROUP BY metric_period_start, metric_period_end, profile_name, business_decision_label
-- HAVING COUNT(*) > 1;

-- E4. proposed_count = 0 avec des taux non NULL
-- SELECT metric_id, profile_name, business_decision_label,
--        proposed_count, confirmation_rate, correction_rate
-- FROM mart.vhs_stability_metrics
-- WHERE proposed_count = 0
--   AND (   confirmation_rate    IS NOT NULL
--        OR correction_rate      IS NOT NULL
--        OR rejection_rate       IS NOT NULL
--        OR needs_more_info_rate IS NOT NULL);


-- =============================================================================
-- END OF DESIGN SQL
-- This file is a proposal only.
-- Do not execute directly before technical review, data owner validation
-- and explicit migration approval.
-- =============================================================================
