# Claim Business Rule Signals V1 Candidate

## Objectif

Ce document specifie une couche deterministe de signaux metier pour IRIS Claim Attention.

La couche produit des signaux explicables par dossier afin d'aider le gestionnaire a prioriser la verification. Elle ne constitue pas une conclusion automatique, ne prouve pas une irregularite et ne modifie pas Claim Attention Score V1.

## Positionnement

Le mart `mart.fact_claim_business_rule_signal` est une couche intermediaire entre les features V1 et un futur score hybride. Il transforme les indicateurs prepares dans `mart.fact_claim_scoring_features` en signaux metier audites, versionnes et tracables.

Cette approche permet de separer clairement :

- les donnees et features,
- les regles metier deterministes,
- le score global futur,
- les modules specifiques comme le post-inspection,
- les analyses avancees futures, uniquement apres labellisation humaine.

## Versioning

- `signal_version = IRIS_CLAIM_BUSINESS_RULE_SIGNAL_V1_CANDIDATE`
- `signal_run_id = IRIS_CLAIM_BUSINESS_RULE_SIGNAL_V1_CANDIDATE_YYYYMMDD_HHMMSS`

Chaque execution doit etre recalculable et tracable par `signal_run_id`.

## Source

Source unique V1 :

```text
mart.fact_claim_scoring_features
```

La couche ne lit pas directement les tables DWH brutes. Les corrections de dates, cles techniques `0`, recurrence client et montant atypique restent centralisees dans le feature mart V1.

## Grain

Une ligne represente un signal metier declenche pour un dossier :

```text
signal_run_id
+ signal_version
+ claim_sk
+ rule_code
```

Ce grain evite les doublons et permet d'expliquer plusieurs signaux pour un meme dossier sans forcer une conclusion unique.

## Familles V1

### Recurrence client

Les signaux utilisent uniquement les sinistres anterieurs deja calcules dans le feature mart.

Regles candidates :

- `CLIENT_CLAIMS_12M_HIGH` : au moins 3 sinistres client sur 12 mois.
- `CLIENT_CLAIMS_12M_MEDIUM` : 2 sinistres client sur 12 mois.
- `CLIENT_CLAIMS_12M_LOW` : 1 sinistre client sur 12 mois.
- `CLIENT_RECENT_PREVIOUS_CLAIM` : precedent sinistre client dans les 30 jours.

### Montant atypique

Les signaux comparent le montant evalue au profil observe dans la garantie.

Regles candidates :

- `AMOUNT_HIGH_BY_GUARANTEE` : percentile >= 0.95, ratio >= 3.0 ou flag montant eleve.
- `AMOUNT_MEDIUM_BY_GUARANTEE` : percentile >= 0.90 ou ratio >= 2.0.
- `AMOUNT_LOW_BY_GUARANTEE` : percentile >= 0.80 ou ratio >= 1.5.

### Chronologie

Les signaux utilisent des dates calendaires deja parsees et controlees dans le feature mart.

Regles candidates :

- `CLAIM_BEFORE_CONTRACT_START` : sinistre avant debut contrat rattache.
- `CLAIM_SOON_AFTER_CONTRACT_START` : sinistre dans les 30 jours apres debut contrat.
- `CLAIM_WITHIN_90D_CONTRACT_START` : sinistre entre 31 et 90 jours apres debut contrat.
- `DECLARATION_BEFORE_CLAIM_DATE` : declaration avant date de sinistre.
- `LONG_DECLARATION_DELAY_HIGH` : declaration apres 90 jours ou plus.
- `LONG_DECLARATION_DELAY_MEDIUM` : declaration entre 30 et 89 jours.

### Qualite des donnees

Les signaux de qualite ne donnent aucun point candidat.

Ils documentent les limites d'interpretation :

- cles structurantes manquantes,
- dates invalides,
- date future,
- confiance faible ou non prete.

## Points candidats

Les points sont des poids metier candidats, pas un score final.

Ils servent a mesurer l'intensite relative d'un signal avant gouvernance :

- severite forte : verification prioritaire suggeree,
- severite moyenne : signal metier a examiner,
- severite faible : contexte a verifier,
- qualite donnees : 0 point.

Les points qualite restent toujours a `0` afin que les donnees faibles reduisent la confiance sans augmenter l'attention metier.

## Colonnes cibles

Table cible :

```text
mart.fact_claim_business_rule_signal
```

Colonnes principales :

```text
signal_run_id
signal_version
source_feature_run_id
claim_sk
claim_business_id
client_sk
contrat_sk
vehicule_sk
rule_family
rule_code
rule_label
rule_severity_rank
attention_level
confidence_level
rule_threshold_value
rule_observed_value
candidate_points
business_explanation
source_tables
payload_json
is_data_quality_signal
profile_name
created_at
```

## Rapports qualite

Chemin :

```text
data/quality_reports/scoring/business_rules/v1_candidate/
```

Rapports attendus :

- `business_rule_load_summary.csv`
- `business_rule_duplicate_grain_check.csv`
- `business_rule_attention_distribution.csv`
- `business_rule_confidence_distribution.csv`
- `business_rule_family_distribution.csv`
- `business_rule_not_ready_reasons.csv`
- `business_rule_threshold_breaches.csv`
- `business_rule_validation_summary.csv`
- `business_rule_validation_summary.md`

## Tests

Tests unitaires :

- mapping des niveaux d'attention,
- recurrence client,
- montant atypique,
- coherence temporelle,
- qualite donnees a zero point,
- unicite du grain,
- absence de vocabulaire accusatoire.

Tests de regression :

- Claim Scoring Features V1,
- Claim Attention Score V1,
- Post-inspection Signal V1 Candidate.

## Non-goals

Cette couche ne doit pas :

- modifier VHS,
- modifier Claim Attention Score V1,
- ajouter des points post-inspection au score global,
- utiliser du ML, SHAP ou Isolation Forest,
- produire une conclusion automatique,
- remplacer l'appreciation humaine du gestionnaire.

## Prochaine etape

Apres validation des distributions et des rapports, la prochaine etape est une specification d'agregation Claim Attention Score V1.1 ou V2.

Cette future version pourra combiner :

- signaux metier deterministes,
- signal post-inspection Scenario A,
- niveau de confiance,
- puis, uniquement apres labellisation humaine, une couche avancee supervisee ou hybride.
