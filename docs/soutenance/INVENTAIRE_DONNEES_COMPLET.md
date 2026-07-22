# Inventaire complet des données — IRIS Auto Fraud

> Généré le 20/07/2026 par introspection directe de PostgreSQL (`information_schema`).
> Trois parties : (1) processus/architecture data, (2) schémas SQL (dwh, mart, app, powerbi_v)
> avec toutes les colonnes réelles, (3) modèle Power BI chargé — tables, colonnes ajoutées, mesures DAX.

---

## 1. Processus de données (architecture en couches)

```
Sources Excel (data/raw/*.xlsx)
        │  Python/pandas — normalisation clés, nettoyage, profilage
        ▼
staging.stg_* (PostgreSQL)          4 tables : stg_clients, stg_production, stg_sinistres, stg_inspection
        │  ETL dwh (etl/dwh/load_*.py) — clés de substitution, ligne UNKNOWN=0 par dimension
        ▼
dwh.*  (constellation, vérité métier, jamais recalculée)
        │  ETL mart (etl/mart/compute_*.py) — moteurs de score, versionnés (run_id)
        ▼
mart.*  (résultats dérivés, recalculables, jamais écrasés)
        │  app.claim_review_decision — SEULE table en écriture (décision humaine, append-only)
        ▼
powerbi_v.*  (vues de restitution, lecture seule, verrouillées sur score_version)
        │
        ├──► Backend Flask (API read-only) ──► Frontend Angular (opérationnel, par dossier)
        └──► Power BI Desktop ──► Rapport (analytique, par cohorte)
```

Règles structurantes :
- **dwh** : clé technique `*_sk = 0` réservée aux lignes UNKNOWN — aucune FK de fait n'est jamais NULL
- **mart** : chaque table de fait porte `(profile_name/rule_version, run_id, created_at)` — recalcul = nouvelles lignes, jamais UPDATE
- **app** : trigger PostgreSQL interdisant UPDATE/DELETE sur `claim_review_decision` — corrections via `corrects_decision_id`
- **powerbi_v** : ne lit jamais `mart.*`/`dwh.*` directement côté rapport ; `v_score_version_config` verrouille la version servie (alignée avec `backend/config.py`)

---

## 2. Schéma `dwh` — Data Warehouse (constellation)

### Dimensions

| Table | Colonnes |
|---|---|
| **dim_client** | client_sk, idclt, typeid, id_piece, nature_client, adr1, cpost, cite, gouvernor, pays, localite, date_naissance, sexe, nombre_enfant, situation_familiale, source_system, created_at |
| **dim_contrat** | contrat_sk, contrat_key, numero_contrat, date_debut_contrat, date_fin_contrat, date_debut_effet, date_fin_effet, statut_contrat, type_resiliation, libelle_resiliation, source_system, created_at |
| **dim_vehicule** | vehicule_sk, immatriculation, vin, motorisation, source_system, created_at |
| **dim_conducteur** | conducteur_sk, nom_conducteur, date_naissance_conducteur, numero_permis, categorie_permis, date_permis, age_conducteur, anciennete_permis, source_system, created_at |
| **dim_tiers** | tiers_sk, nom_tiers, immatriculation_vehicule_tiers, numero_contrat_tiers, numero_sinistre_tiers, source_system, created_at |
| **dim_camtier** | camtier_sk, nature_camtier, id_camtier, code_camtier, source_system, created_at |
| **dim_intermediaire** | intermediaire_sk, code_intermediaire, nature_intermediaire, id_intermediaire, libelle_intermediaire, source_system, created_at |
| **dim_produit** | produit_sk, code_produit, libelle_produit, code_famille, libelle_famille, source_system, created_at |
| **dim_garantie** | garantie_sk, garantie_key, code_produit, code_garantie, libelle_garantie, garantie_quality_level, source_system, created_at |
| **dim_sinistre** | sinistre_sk, numero_sinistre, cause_sinistre, libelle_cause_sinistre, code_etat, indicateur_forcage, cas_ida, coassur, reassur, indicateur_transaction, source_system, created_at |
| **dim_geo** | geo_sk, pays, region, gouvernorat, localite, adresse_fragment, code_postal, geo_entity_type, geo_quality_level, needs_review, geo_key, source_system, source_context, created_at |
| **dim_date** | date_sk, date_complete, annee, trimestre, mois, libelle_mois, jour, jour_semaine, libelle_jour, semaine_annee, est_weekend |

### Faits

| Table | Grain | Colonnes |
|---|---|---|
| **fact_sinistre** | sinistre × garantie | fact_sinistre_sk, numero_sinistre, code_garantie, sinistre_garantie_key, sinistre_sk, garantie_sk, client_sk, contrat_sk, vehicule_sk, conducteur_sk, tiers_sk, camtier_sk, geo_sinistre_sk, date_survenance_sk, date_declaration_sk, date_ouverture_sk, date_cloture_sk, montant_evaluation, montant_reglement, montant_reserve, montant_recours, montant_charge_sinistre, delai_survenance_declaration_jours, delai_declaration_ouverture_jours, delai_ouverture_cloture_jours, est_cloture, est_corporel, est_materiel, est_ida, est_transaction, est_forcage, est_coassurance, est_reassurance, motif_cloture_garantie, etat_garantie_sinistre, source_system, created_at |
| **fact_contrat** | contrat × avenant × mise à jour | fact_contrat_sk, contrat_mouvement_key, contrat_key, numero_contrat, numero_avenant, numero_mise_a_jour, contrat_sk, client_sk, produit_sk, intermediaire_sk, date_debut_contrat_sk, date_fin_contrat_sk, date_debut_effet_sk, date_fin_effet_sk, date_derniere_operation_sk, date_resiliation_sk, duree_contrat, total_prime, nombre_contrat_mouvement, est_contrat_actif, est_contrat_resilie, est_coassurance, est_avenant, est_mise_a_jour, est_auto_scope, situation_contrat, type_resiliation, libelle_resiliation, source_system, created_at |
| **fact_inspection_vehicule** | 1 inspection | fact_inspection_vehicule_sk, inspection_key, immatriculation_norm, vehicule_sk, date_inspection_sk, kilometrage, nb_anomalies_tour_vehicule, nb_anomalies_interieur, nb_anomalies_sous_capot, nb_anomalies_sous_vehicule, nb_anomalies_entretien, nb_anomalies_total, nb_anomalies_critiques, indicateur_anomalie_critique, indicateur_inspection_complete, agent_controle, source_system, created_at |
| **fact_inspection_checkpoint** | 1 checkpoint × inspection | fact_inspection_checkpoint_sk, inspection_checkpoint_key, inspection_key, vehicule_sk, date_inspection_sk, immatriculation_norm, zone_controle, checkpoint_code, checkpoint_libelle, valeur_controle, commentaire_zone, est_anomalie, est_anomalie_critique, est_controle_renseigne, source_system, created_at |

---

## 3. Schéma `mart` — résultats de scoring (versionnés)

### Référentiel

| Table | Colonnes |
|---|---|
| **dim_checkpoint** | checkpoint_sk, checkpoint_code, checkpoint_libelle, zone_controle, tier, is_vhs_scored, is_vital, is_important, is_critical_functional, is_immobilizing, penalty_worn, penalty_broken, rule_version, is_active, valid_from, valid_to, review_status, review_reason, created_at |

### Faits — chaîne VHS

| Table | Colonnes |
|---|---|
| **fact_vhs_score** | vhs_score_sk, inspection_key, vehicule_sk, date_inspection_sk, immatriculation_norm, kilometrage, vhs_raw_score, kilometrage_penalty, vhs_before_cap, vhs_final_score, safety_score, functional_score, cosmetic_score, safety_grade, decision, is_drivable, hard_cap_applied, hard_cap_type, nb_penalties_applied, nb_anomalies_total, nb_anomalies_critiques, profile_name, rule_version, run_id, calculated_at, source_system, created_at, nb_checkpoints_scored, nb_ok, nb_worn, nb_worn_strong, nb_broken, nb_unknown, nb_repaired, has_critical_functional, cap_value, nb_systems_penalized, penalty_raw_before_cap, penalty_after_system_cap |
| **fact_vhs_penalty_detail** | penalty_detail_sk, inspection_key, vehicule_sk, date_inspection_sk, immatriculation_norm, checkpoint_code, checkpoint_libelle, zone_controle, observed_value, observed_status, penalty_applied, penalty_reason, tier, is_vital, is_important, is_critical_functional, is_immobilizing, is_hard_cap_trigger, hard_cap_type, profile_name, rule_version, run_id, created_at, valeur_controle, est_anomalie, est_anomalie_critique, penalty_worn, penalty_broken, systeme_fonctionnel, penalty_raw_checkpoint, penalty_capped_by_system |

### Faits — chaîne Claim Attention

| Table | Colonnes |
|---|---|
| **fact_claim_scoring_features** | claim_feature_sk, claim_sk, claim_business_id, numero_sinistre, code_garantie, client_sk, contrat_sk, vehicle_sk, garantie_sk, conducteur_sk, tiers_sk, camtier_sk, claim_geo_sk, claim_date_sk, declaration_date_sk, contract_start_date_sk, claim_date, declaration_date, contract_start_date, claim_amount, client_claim_count_total, client_claim_count_12m, client_claim_count_24m, days_since_previous_claim, client_claim_frequency_band, amount_vs_guarantee_median_ratio, amount_percentile_by_guarantee, high_amount_flag, days_claim_to_declaration, days_contract_start_to_claim, claim_before_contract_start_flag, contract_start_ready_flag, recent_contract_change_flag, recent_guarantee_change_flag, claim_after_recent_update_flag, chronology_ready_flag, missing_keys_count, unknown_dimensions_count, weak_join_flag, migration_2019_flag, missing_client_flag, missing_contract_flag, missing_vehicle_flag, missing_guarantee_flag, missing_geo_flag, missing_driver_flag, missing_third_party_flag, invalid_claim_date_flag, invalid_declaration_date_flag, future_claim_date_flag, vehicle_recurrence_ready_flag, third_party_signal_ready_flag, geo_signal_ready_flag, vhs_signal_ready_flag, confidence_level, scoring_feature_version, feature_run_id, profile_name, source_system, created_at |
| **fact_claim_business_rule_signal** | business_rule_signal_sk, signal_run_id, signal_version, source_feature_run_id, claim_sk, claim_business_id, client_sk, contrat_sk, vehicule_sk, rule_family, rule_code, rule_label, rule_severity_rank, attention_level, confidence_level, rule_threshold_value, rule_observed_value, candidate_points, business_explanation, source_tables, payload_json, is_data_quality_signal, profile_name, created_at |
| **fact_claim_ml_anomaly_signal** | ml_anomaly_signal_sk, signal_run_id, signal_version, source_feature_run_id, claim_sk, claim_business_id, raw_anomaly_score, anomaly_percentile_score, score_ml, ml_attention_points, ml_attention_level, top_variable_1, top_variable_2, top_variable_3, feature_value_json, feature_percentile_json, feature_list_json, model_params_json, imputation_json, profile_name, source_system, created_at |
| **fact_post_inspection_attention_signal** | post_inspection_signal_sk, signal_run_id, signal_version, scenario_code, scenario_label, inspection_sk, claim_sk, contract_sk, client_sk, vehicule_sk, immatriculation, inspection_date, claim_date, avenant_date, days_inspection_to_claim, days_inspection_to_avenant, delay_bucket, defective_zone, defective_checkpoint_count, critical_checkpoint_count, defective_checkpoint_codes, representative_checkpoint_labels, claim_area, claim_guarantee_code, claim_guarantee_label, zone_match_status, linkage_method, attention_level, confidence_level, business_explanation, profile_name, created_at |
| **fact_claim_attention_score** | claim_attention_score_sk, claim_sk, claim_business_id, score_version, score_run_id, feature_run_id, attention_score, attention_level, confidence_level, main_reason_1, main_reason_2, main_reason_3, profile_name, source_system, created_at |
| **fact_claim_attention_signal_detail** | signal_detail_sk, claim_sk, claim_business_id, score_run_id, score_version, signal_family, signal_code, signal_label, signal_value, points, severity, business_explanation, profile_name, created_at |

## Schéma `app` — écriture humaine (append-only)

| Table | Colonnes |
|---|---|
| **claim_review_decision** | decision_id, claim_sk, score_version, score_run_id, decision, comment, reviewer_email, reviewer_role, decided_at, created_at, corrects_decision_id |
| **claim_review_decision_latest** (vue) | même colonnes, sans `corrects_decision_id`, dernière décision par dossier |

---

## 4. Schéma `powerbi_v` — vues de restitution (13 vues, lecture seule)

| Vue | Grain | Colonnes |
|---|---|---|
| **v_score_version_config** | config | score_version *(verrouillée : HYBRID_ML_V1, alignée backend)* |
| **v_current_run** | config | score_version, score_run_id |
| **v_claim_attention_guarantee** | sinistre × garantie | claim_sk, claim_business_id, claim_root_id, numero_sinistre, code_garantie, client_sk, contrat_sk, vehicle_sk, garantie_sk, claim_date, declaration_date, contract_start_date, claim_amount, client_claim_count_12m, client_claim_count_24m, days_since_previous_claim, days_claim_to_declaration, days_contract_start_to_claim, attention_score, attention_level, confidence_level, main_reason_1, main_reason_2, main_reason_3, score_version, score_run_id, feature_run_id, created_at, **claim_geo_sk** |
| **v_dossier_attention** | dossier (MAX garanties, règle ADR) | claim_root_id, numero_sinistre, dossier_attention_score, dossier_attention_level, confidence_level, main_reason_1, main_reason_2, main_reason_3, client_sk, contrat_sk, vehicle_sk, guarantee_row_count, guarantee_code_count, dossier_claim_amount, claim_date, declaration_date, score_version, score_run_id, **gouvernorat**, **geo_region** *(ajoutées cette session)* |
| **v_signal_detail** | signal × dossier | claim_sk, claim_business_id, claim_root_id, signal_family, signal_code, signal_label, signal_value, points, severity, business_explanation, score_version, score_run_id |
| **v_client_cohort** | client | client_sk, dossier_count, total_claim_amount, first_claim_date, last_claim_date, max_attention_score, high_attention_dossier_count, max_claim_count_12m, is_multiclaim_12m |
| **v_inspection** | inspection | inspection_key, vehicule_sk, immatriculation_norm, inspection_date, checkpoint_count, defect_count, critical_defect_count |
| **v_inspection_checkpoint_defect** | checkpoint | zone_controle, checkpoint_code, checkpoint_libelle, observed_count, defect_count, critical_defect_count |
| **v_vhs_score** | inspection VHS | inspection_key, vehicule_sk, immatriculation_norm, kilometrage, vhs_final_score, safety_score, functional_score, cosmetic_score, safety_grade, decision, is_drivable, hard_cap_applied, nb_penalties_applied, nb_anomalies_total, nb_anomalies_critiques, rule_version, run_id |
| **v_post_inspection_signal** | lien inspection↔sinistre | claim_sk, inspection_sk, client_sk, vehicule_sk, immatriculation, inspection_date, claim_date, days_inspection_to_claim, delay_bucket, defective_zone, defective_checkpoint_count, critical_checkpoint_count, claim_guarantee_code, claim_guarantee_label, zone_match_status, attention_level, confidence_level, business_explanation, scenario_code, signal_version, signal_run_id |
| **v_ml_anomaly** | sinistre | claim_sk, claim_business_id, claim_root_id, raw_anomaly_score, anomaly_percentile_score, score_ml, ml_attention_level, top_variable_1, top_variable_2, top_variable_3, signal_version, signal_run_id |
| **v_quality_kpis** | config | guarantee_rows, dossier_count, pct_unknown_client, pct_missing_vehicle, pct_invalid_dates, pct_migration_2019, pct_confidence_high |
| **v_governance** | par composant | component, version, run_id, created_at, row_count |

---

## 5. Modèle Power BI chargé (`iris_auto_fraudDASH.pbix`)

### 5.1 Tables importées (Import, 13 vues `powerbi_v`)

Toutes les vues ci-dessus sont chargées telles quelles, renommées sans le préfixe `v_` :
`v_score_version_config`, `v_current_run`, `v_claim_attention_guarantee`, `v_dossier_attention`,
`v_signal_detail`, `v_client_cohort`, `v_inspection`, `v_inspection_checkpoint_defect`,
`v_vhs_score`, `v_post_inspection_signal`, `v_ml_anomaly`, `v_quality_kpis`, `v_governance`.

### 5.2 Colonnes calculées ajoutées dans Power BI

| Table | Colonne | Formule DAX |
|---|---|---|
| v_dossier_attention | `score_bin` | `INT('v_dossier_attention'[dossier_attention_score] / 5) * 5` |
| v_dossier_attention | `claim_month` | `DATE(YEAR([claim_date]), MONTH([claim_date]), 1)` |
| v_client_cohort | `tranche_sinistres` | `IF('v_client_cohort'[dossier_count] >= 5, "5+", FORMAT('v_client_cohort'[dossier_count], "0"))` |
| _Mesures (colonne) | `Target Pct Haute Attention` | `0.005` *(seuil plafond 0,5 %)* |

### 5.3 Table `_Mesures` — mesures DAX

**Mesures de base (catalogue initial) :**
```dax
Dossiers Scores = DISTINCTCOUNT('v_dossier_attention'[claim_root_id])

Dossiers Haute Attention =
CALCULATE([Dossiers Scores],
    'v_dossier_attention'[dossier_attention_level]
        IN {"Examen renforce suggere", "Examen prioritaire suggere"})

Pct Haute Attention = DIVIDE([Dossiers Haute Attention], [Dossiers Scores])

Dossiers Prioritaires =
CALCULATE([Dossiers Scores],
    'v_dossier_attention'[dossier_attention_level] = "Examen prioritaire suggere")

Score Median = MEDIAN('v_dossier_attention'[dossier_attention_score])

Montant Sinistres = SUM('v_dossier_attention'[dossier_claim_amount])

Pct Confiance Haute =
DIVIDE(
    CALCULATE([Dossiers Scores], 'v_dossier_attention'[confidence_level] = "HIGH"),
    [Dossiers Scores])

Lignes Garantie = COUNTROWS('v_claim_attention_guarantee')

Signaux Emis = COUNTROWS('v_signal_detail')

Points Attribues = SUM('v_signal_detail'[points])

Dossiers Avec Signal = DISTINCTCOUNT('v_signal_detail'[claim_root_id])

Clients Identifies = COUNTROWS('v_client_cohort')

Clients Multisinistres 12M =
CALCULATE(COUNTROWS('v_client_cohort'), 'v_client_cohort'[is_multiclaim_12m] = TRUE())

Montant Cumule Clients = SUM('v_client_cohort'[total_claim_amount])

Inspections = COUNTROWS('v_inspection')

Pct Inspections Avec Defaut =
DIVIDE(
    CALCULATE(COUNTROWS('v_inspection'), 'v_inspection'[defect_count] > 0),
    COUNTROWS('v_inspection'))

Defauts Observes = SUM('v_inspection_checkpoint_defect'[defect_count])

Inspections VHS = COUNTROWS('v_vhs_score')

Score VHS Moyen = AVERAGE('v_vhs_score'[vhs_final_score])

Signaux Post Inspection = COUNTROWS('v_post_inspection_signal')

Delai Moyen Inspection Sinistre = AVERAGE('v_post_inspection_signal'[days_inspection_to_claim])

Dossiers ML Top 5 Pct =
CALCULATE(DISTINCTCOUNT('v_ml_anomaly'[claim_sk]), 'v_ml_anomaly'[anomaly_percentile_score] >= 0.95)

Pct Client Inconnu = MAX('v_quality_kpis'[pct_unknown_client])
Pct Dates Invalides = MAX('v_quality_kpis'[pct_invalid_dates])
Pct Migration 2019 = MAX('v_quality_kpis'[pct_migration_2019])
```

**Mesures ajoutées pendant la construction de « Vue d'ensemble » (cette session) :**
```dax
Pct Prioritaires = DIVIDE([Dossiers Prioritaires], [Dossiers Scores])

-- Comparaisons mois précédent (M-1), pour les cartes KPI avec flèche de tendance
Dossiers Scores M-1 =
VAR MoisCourant = MAX('v_dossier_attention'[claim_month])
RETURN CALCULATE([Dossiers Scores], 'v_dossier_attention'[claim_month] = EDATE(MoisCourant, -1))

Dossiers Prioritaires M-1 =
VAR MoisCourant = MAX('v_dossier_attention'[claim_month])
RETURN CALCULATE([Dossiers Prioritaires], 'v_dossier_attention'[claim_month] = EDATE(MoisCourant, -1))

Pct Prioritaires M-1 =
VAR MoisCourant = MAX('v_dossier_attention'[claim_month])
RETURN CALCULATE([Pct Prioritaires], 'v_dossier_attention'[claim_month] = EDATE(MoisCourant, -1))

Montant Sinistres M-1 =
VAR MoisCourant = MAX('v_dossier_attention'[claim_month])
RETURN CALCULATE([Montant Sinistres], 'v_dossier_attention'[claim_month] = EDATE(MoisCourant, -1))

Score Median M-1 =
VAR MoisCourant = MAX('v_dossier_attention'[claim_month])
RETURN CALCULATE([Score Median], 'v_dossier_attention'[claim_month] = EDATE(MoisCourant, -1))

Pct Confiance Haute M-1 =
VAR MoisCourant = MAX('v_dossier_attention'[claim_month])
RETURN CALCULATE([Pct Confiance Haute], 'v_dossier_attention'[claim_month] = EDATE(MoisCourant, -1))

-- Cible de gouvernance fixe (plancher de confiance)
Target Confiance Haute = 0.80
```

### 5.4 Formats appliqués

| Mesure | Format |
|---|---|
| Pct Prioritaires, Pct Confiance Haute, Pct Haute Attention, Pct Client Inconnu, Pct Dates Invalides, Pct Migration 2019, Pct Inspections Avec Defaut, Pct Clients Multi (Clients Multisinistres 12M / Clients Identifies) | Percentage, 2 décimales |
| Montant Sinistres, Montant Cumule Clients | Devise personnalisée `#,##0.0,, "M TND"` |
| dossier_claim_amount (colonne) | Devise personnalisée `#,##0 "TND"` |
| Dossiers Scores, Dossiers Prioritaires, Score Median (+ variantes M-1) | Nombre entier, séparateur de milliers |

### 5.5 Relations actives dans le modèle

| De | Vers | Cardinalité | État |
|---|---|---|---|
| v_claim_attention_guarantee[claim_root_id] | v_dossier_attention[claim_root_id] | N:1 | Active |
| v_signal_detail[claim_root_id] | v_dossier_attention[claim_root_id] | N:1 | Active |
| v_ml_anomaly[claim_root_id] | v_dossier_attention[claim_root_id] | N:1 | Active |
| v_dossier_attention[client_sk] | v_client_cohort[client_sk] | N:1 | Active |
| v_post_inspection_signal[claim_sk] | v_claim_attention_guarantee[claim_sk] | N:1 | **Inactive** (désactivée — ambiguïté résolue) |

---

*Document généré par introspection SQL directe le 20/07/2026 — reflète l'état réel de la base, pas une copie de la documentation.*
