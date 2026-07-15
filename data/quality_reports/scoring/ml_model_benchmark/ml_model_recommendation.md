# ML anomaly model benchmark recommendation

- Recommended model: `Isolation Forest`
- Feature run ID: `IRIS_CLAIM_ATTENTION_FEATURES_V1_CANDIDATE_20260708_144724`
- Models executed: 6
- Rows in ML feature matrix: 381893
- Features used: 17

## Decision perimeter

This benchmark compares statistical atypicality signals. It does not measure supervised precision because no human-confirmed labels are available.

## Rationale

- Le benchmark confirme Isolation Forest comme modele candidat principal pour le signal d'atypicite statistique IRIS.
- Ce choix repose sur sa couverture complete du portefeuille, sa calibration en percentile, son integration deja versionnee dans le mart ML, son temps d'execution maitrise et sa coherence avec les signaux metier deterministes.
- Son score est interpretable comme un rang d'atypicite dans la population du run.
- Son top 5% recouvre 31.8% des dossiers fortement priorises par le score Hybrid deterministe sans ML.
- Il couvre 381,893 dossiers, ce qui evite une conclusion fondee seulement sur un echantillon.
- HBOS est disponible et peut rester un comparateur rapide et interpretable.
- Local Outlier Factor reste exploratoire: status=executed_on_sample, rows=50000.
- One-Class SVM reste exploratoire: status=executed_on_small_sample, rows=10000.
- Robust Covariance reste exploratoire: status=executed_on_sample, rows=50000.

## Model decision matrix

- Isolation Forest: coverage=volume complet, runtime=0.052s, business_overlap=0.31762241424456666, status=principal_candidate
- HBOS: coverage=echantillon large, runtime=0.045s, business_overlap=0.4112, status=comparison_candidate
- Robust Covariance: coverage=echantillon large, runtime=3.542s, business_overlap=0.118, status=exploratory
- One-Class SVM: coverage=echantillon limite, runtime=1.312s, business_overlap=0.192, status=exploratory
- Local Outlier Factor: coverage=echantillon large, runtime=7.833s, business_overlap=0.0244, status=exploratory
- Autoencoder simple: coverage=echantillon limite, runtime=1.539s, business_overlap=0.11, status=exploratory

## Business limitations

No unsupervised model is presented as an automatic decision tool. The scores are statistical atypicality signals for human review only.
The final interpretation must combine score percentile, business rules, post-inspection context and human review.

## Failed or skipped models

- None
