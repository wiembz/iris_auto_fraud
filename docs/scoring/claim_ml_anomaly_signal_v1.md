# IRIS Claim ML Anomaly Signal V1 Candidate

## Objectif

Ce module ajoute un signal d'atypicite statistique non supervise au dispositif IRIS Claim Attention. Il sert a prioriser la verification humaine des dossiers, sans produire de conclusion automatique et sans qualifier un dossier comme fraude.

Le module ne remplace pas les regles metier. Il les complete par une lecture statistique prudente des dossiers atypiques.

## Positionnement

- Version: `IRIS_CLAIM_ML_ANOMALY_SIGNAL_V1_CANDIDATE`
- Score global avec ML: `IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE`
- Modele: Isolation Forest
- Usage: signal d'attention et de priorisation
- Decision finale: humaine

## Pourquoi Isolation Forest

Isolation Forest est adapte a un contexte sans labels confirmes, car il cherche les observations atypiques dans une population sans apprentissage supervise. Dans IRIS, ce choix reste candidat et auditable.

Le score brut du modele n'est pas interprete directement comme une probabilite. Il est calibre en percentile population.

## Calibration

Pipeline de calibration:

```text
raw_anomaly_score
-> anomaly_percentile_score
-> score_ml entre 0 et 1
```

Interpretation:

```text
score_ml = 0.95
```

signifie:

```text
Le dossier est plus atypique que 95% des dossiers du run.
```

Cette formulation est plus explicable qu'un score brut Isolation Forest.

## Variables ML utilisees

Les variables sont definies dans:

```text
config/scoring/claim_attention_ml_anomaly_v1_candidate.json
```

Elles couvrent principalement:

- montant du sinistre
- atypicite du montant par garantie
- recurrence client
- recurrence vehicule
- recurrence conducteur
- recurrence tiers
- repetition client-garantie
- delais chronologiques
- contexte post-inspection Scenario A

La liste exacte des variables est stockee dans chaque run via `feature_list_json`.

## Explicabilite

Pour chaque dossier, le module stocke:

- `feature_value_json`: valeurs ML utilisees
- `feature_percentile_json`: percentile de chaque variable
- `top_variable_1..3`: variables les plus atypiques du dossier
- `model_params_json`: parametres du modele
- `imputation_json`: valeurs d'imputation utilisees

Exemple d'explication:

```text
claim_amount: value=50000, percentile=0.99
days_claim_to_declaration: value=120, percentile=0.97
client_claim_count_12m: value=5, percentile=0.95
```

## Integration score

Le signal ML est integre seulement dans une version separee:

```text
IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE
```

Le score hybride de base reste conserve. Les points ML sont plafonnes et ne peuvent pas faire depasser le score global de 100.

## Tables cible

Signal ML:

```text
mart.fact_claim_ml_anomaly_signal
```

Score global candidat avec ML:

```text
mart.fact_claim_attention_score
mart.fact_claim_attention_signal_detail
```

avec `score_version = IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE`.

## Non-goals

Ce module ne fait pas:

- detection automatique de fraude
- preuve ou conclusion juridique
- modification VHS
- modification Claim Attention Score V1
- remplacement des regles metier
- apprentissage supervise
- SHAP ou explication causale

## Validation attendue

Avant usage metier, verifier:

- score_ml dans [0, 1]
- aucun doublon `(signal_run_id, signal_version, claim_sk)`
- features ML stockees
- aucun wording accusatoire
- score global dans [0, 100]
- coherence entre points de detail et score final
- exemples top percentiles revus par un gestionnaire metier
