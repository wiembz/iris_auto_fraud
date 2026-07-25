# Manifeste de sauvegarde powerbi_v -- 2026-07-24

Proprietaire de toutes les vues et du schema powerbi_v : postgres (role superuser unique de cet environnement local -- aucun role applicatif/PowerBI dedie separe n'existe dans cette base).

Permissions : aucun GRANT explicite au-dela des privileges implicites du proprietaire (DELETE/INSERT/REFERENCES/SELECT/TRIGGER/TRUNCATE/UPDATE, tous portes par postgres). Aucun autre grantee.

## Ordre de recreation (topologique, valide) et dependances

Fichier des definitions completes (CREATE OR REPLACE VIEW) : powerbi_v_definitions_backup_20260724.sql -- executer dans CET ordre exact.

### powerbi_v.v_score_version_config (owner: postgres)
- (aucune dependance vers dwh/mart/powerbi_v detectee)

### powerbi_v.v_current_run (owner: postgres)
- depend de mart.fact_claim_attention_score (table)
- depend de powerbi_v.v_score_version_config (view)

### powerbi_v.v_claim_attention_guarantee (owner: postgres)
- depend de mart.fact_claim_attention_score (table)
- depend de mart.fact_claim_scoring_features (table)
- depend de powerbi_v.v_current_run (view)

### powerbi_v.v_dossier_attention (owner: postgres)
- depend de dwh.dim_client (table)
- depend de dwh.dim_geo (table)
- depend de powerbi_v.v_claim_attention_guarantee (view)

### powerbi_v.v_client_cohort (owner: postgres)
- depend de powerbi_v.v_claim_attention_guarantee (view)
- depend de powerbi_v.v_dossier_attention (view)

### powerbi_v.v_governance (owner: postgres)
- depend de mart.fact_claim_attention_score (table)
- depend de mart.fact_claim_ml_anomaly_signal (table)
- depend de mart.fact_post_inspection_attention_signal (table)
- depend de mart.fact_vhs_score (table)
- depend de powerbi_v.v_current_run (view)

### powerbi_v.v_quality_kpis (owner: postgres)
- depend de mart.fact_claim_attention_score (table)
- depend de mart.fact_claim_scoring_features (table)
- depend de mart.fact_vhs_score (table)
- depend de powerbi_v.v_current_run (view)

### powerbi_v.v_signal_detail (owner: postgres)
- depend de mart.fact_claim_attention_signal_detail (table)
- depend de powerbi_v.v_current_run (view)

### powerbi_v.v_ml_anomaly (owner: postgres)
- depend de mart.fact_claim_ml_anomaly_signal (table)

### powerbi_v.v_post_inspection_signal (owner: postgres)
- depend de mart.fact_post_inspection_attention_signal (table)

### powerbi_v.v_inspection (owner: postgres)
- depend de dwh.fact_inspection_checkpoint (table)
- depend de dwh.fact_inspection_vehicule (table)

### powerbi_v.v_inspection_checkpoint_defect (owner: postgres)
- depend de dwh.fact_inspection_checkpoint (table)

### powerbi_v.v_vhs_score (owner: postgres)
- depend de dwh.fact_inspection_vehicule (table)
- depend de mart.fact_vhs_score (table)
