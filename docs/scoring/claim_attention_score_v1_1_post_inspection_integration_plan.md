# Plan d'integration post-inspection dans Claim Attention Score V1.1

> **Module :** Claim Attention Score / extension post-inspection  
> **Version cible :** `IRIS_CLAIM_ATTENTION_V1_1_CANDIDATE`  
> **Principe :** priorisation explicable, aide a l'analyse humaine, sans conclusion automatique

---

## 1. Objectif

Ce document definit le plan d'integration future des signaux post-inspection
dans une version separee du Claim Attention Score :

```text
IRIS_CLAIM_ATTENTION_V1_1_CANDIDATE
```

La version V1 existante reste stable. L'integration post-inspection doit etre
faite dans une V1.1 candidate afin de conserver une comparaison claire entre :

```text
V1   = score dossier stable sans post-inspection
V1.1 = score dossier candidat avec famille post-inspection Scenario A
```

Le score reste un outil de priorisation. Il ne constitue pas une accusation, une
preuve ou une decision automatique.

## 2. Sources

La V1.1 doit consommer les sources deja stabilisees :

```text
mart.fact_claim_scoring_features
mart.fact_post_inspection_attention_signal
```

La V1.1 ne doit pas recalculer directement le croisement inspection x sinistre a
partir du DWH. Le flux robuste est :

```text
dwh.fact_inspection_vehicule
+ dwh.fact_inspection_checkpoint
+ dwh.fact_sinistre
-> mart.fact_post_inspection_attention_signal
-> Claim Attention Score V1.1
```

## 3. Perimetre V1.1

La V1.1 ajoute une nouvelle famille :

```text
Post-inspection attention
```

Seul le Scenario A est actif pour les points :

```text
A_INSPECTION_TO_CLAIM
```

Le Scenario B reste exclu des points :

```text
B_INSPECTION_TO_AVENANT = readiness/context only
```

## 4. Scenario A actif

Scenario A est considere GO car le mart post-inspection produit des signaux
valides avec :

- meme `vehicule_sk` non nul ;
- dates inspection et sinistre valides ;
- inspection avant ou egale au sinistre ;
- delai reel 0-90 jours ;
- grain controle par `inspection_sk + claim_sk + defective_zone` ;
- absence de doublons de grain ;
- explication metier prudente.

La V1.1 doit utiliser uniquement les lignes du mart :

```text
scenario_code = 'A_INSPECTION_TO_CLAIM'
```

## 5. Scenario B exclu

Scenario B reste `PARTIAL` car le timing inspection -> avenant est mesurable,
mais le changement exact de garantie, produit ou couverture n'est pas encore
prouve.

Regles V1.1 :

- ne pas donner de points Scenario B ;
- ne pas utiliser Scenario B comme signal fort ;
- conserver Scenario B en rapport readiness uniquement ;
- reevaluer Scenario B si une future source `contrat x garantie x avenant`
  devient disponible.

## 6. Mapping points V1.1

La famille post-inspection doit etre plafonnee pour eviter qu'un seul domaine
ecrase les autres familles V1.

Maximum propose :

```text
Post-inspection attention max = 25 points
```

Regles candidates :

| Condition mart post-inspection | Points |
|---|---:|
| au moins un signal Scenario A `HIGH` pour le dossier | 25 |
| sinon au moins un signal Scenario A `MEDIUM` | 15 |
| sinon seulement signal Scenario A `LOW` | 0 |
| Scenario B `PARTIAL` | 0 |

Raison :

- `HIGH` signifie delai court ou moyen, anomalie documentee et zone disponible ;
- `MEDIUM` signifie lien solide mais delai plus long ou contexte moins fort ;
- `LOW` reste un contexte technique, pas un signal de priorisation fort.

## 7. Aggregation claim-level

Le mart post-inspection est au grain :

```text
signal_run_id + signal_version + scenario_code + inspection_sk + claim_sk + defective_zone
```

Le Claim Attention Score est au grain dossier :

```text
claim_sk
```

La V1.1 doit donc agreger les signaux post-inspection par dossier :

```text
claim_sk
+ latest or selected signal_run_id
+ signal_version
```

Aggregation recommandee :

- `post_inspection_signal_count` = nombre de lignes Scenario A ;
- `post_inspection_high_count` = nombre de lignes `HIGH` ;
- `post_inspection_medium_count` = nombre de lignes `MEDIUM` ;
- `post_inspection_low_count` = nombre de lignes `LOW` ;
- `post_inspection_min_delay_days` = delai minimum inspection -> sinistre ;
- `post_inspection_zones` = zones distinctes concatenees ;
- `post_inspection_main_explanation` = explication metier la plus prioritaire.

Les points sont calcules une seule fois par dossier, meme si plusieurs zones
sont presentes.

## 8. Score total

Le score final reste borne :

```text
0 <= attention_score <= 100
```

Familles V1 conservees :

| Famille | Max V1 | Statut V1.1 |
|---|---:|---|
| Recurrence client | 25 | conserve |
| Montant atypique | 25 | conserve |
| Chronologie | 20 | conserve |
| Qualite donnees | 0 | conserve comme confiance |

Nouvelle famille V1.1 :

| Famille | Max V1.1 | Statut |
|---|---:|---|
| Post-inspection attention | 25 | Scenario A uniquement |

Le total theorique reste inferieur ou egal a 95 avant borne 100 :

```text
25 + 25 + 20 + 25 = 95
```

## 9. Signal detail

La V1.1 doit ajouter une ligne explicative dans :

```text
mart.fact_claim_attention_signal_detail
```

Famille :

```text
Post-inspection
```

Codes proposes :

```text
POST_INSPECTION_HIGH
POST_INSPECTION_MEDIUM
POST_INSPECTION_CONTEXT_ONLY
```

Libelles prudents :

- `Signal post-inspection a examiner`
- `Verification prioritaire suggeree`
- `Contexte technique post-inspection documente`

Exemple d'explication :

```text
Un sinistre est survenu apres une inspection STAFFIM du meme vehicule.
Des elements techniques documentes peuvent justifier une verification
prioritaire par un gestionnaire.
```

## 10. Main reasons

Les motifs principaux `main_reason_1..3` peuvent inclure le signal
post-inspection si les points sont positifs.

Priorite de tri :

```text
points desc
signal_code asc
```

Si le signal post-inspection a 0 point, il peut apparaitre dans le detail avec
`points = 0`, mais ne doit pas devenir motif principal.

## 11. Confidence

La V1.1 doit conserver la logique :

```text
missing / weak data lowers confidence, not attention
```

Le `confidence_level` global peut rester celui de la feature mart V1 dans une
premiere candidate.

Option future :

```text
score confidence = min(claim_feature_confidence, post_inspection_confidence)
```

Cette option doit etre testee separement avant activation.

## 12. Implementation recommandee

Ne pas modifier le moteur V1 stable directement.

Creer une version separee :

```text
etl/mart/compute_claim_attention_score_v1_1_candidate.py
tests/test_claim_attention_score_v1_1.py
```

Avantages :

- V1 reste stable et comparable ;
- V1.1 peut etre presentee comme candidate ;
- rollback simple ;
- tests de non-regression plus clairs.

## 13. Tables de sortie

Deux options sont possibles.

Option recommandee pour audit :

```text
mart.fact_claim_attention_score
mart.fact_claim_attention_signal_detail
```

avec :

```text
score_version = IRIS_CLAIM_ATTENTION_V1_1_CANDIDATE
score_run_id = IRIS_CLAIM_ATTENTION_V1_1_CANDIDATE_YYYYMMDD_HHMMSS
```

Cette option garde les memes tables et distingue les versions par
`score_version`.

## 14. Quality reports

Dossier recommande :

```text
data/quality_reports/scoring/claim_attention_v1_1/
```

Rapports attendus :

```text
claim_attention_v1_1_score_distribution.csv
claim_attention_v1_1_signal_family_summary.csv
claim_attention_v1_1_post_inspection_contribution.csv
claim_attention_v1_1_validation_summary.csv
claim_attention_v1_1_validation_summary.md
claim_attention_v1_vs_v1_1_comparison.csv
```

Le rapport comparaison V1 vs V1.1 doit montrer :

- nombre de dossiers dont le score augmente ;
- augmentation moyenne ;
- score max ;
- distribution par niveau ;
- nombre de dossiers avec contribution post-inspection.

## 15. Tests unitaires

Tests a creer :

- aggregation post-inspection par `claim_sk` ;
- `HIGH` donne 25 points ;
- `MEDIUM` donne 15 points ;
- `LOW` donne 0 point ;
- Scenario B donne 0 point ;
- plusieurs zones pour un meme claim ne multiplient pas les points ;
- detail signal contient une explication non accusatoire ;
- score final reste entre 0 et 100 ;
- `main_reason_1..3` incluent uniquement des signaux positifs ;
- V1 active families restent inchangees.

## 16. Tests de regression

Executer :

```powershell
python -m pytest tests/test_claim_scoring_features_v1.py tests/test_claim_attention_score_v1.py -q
python -m pytest tests/test_post_inspection_attention_signal_v1.py -q
python -m pytest tests/test_claim_attention_score_v1_1.py -q
```

Les tests V1 doivent continuer a passer sans changement de logique.

## 17. Non-goals

La V1.1 ne doit pas :

- modifier VHS ;
- modifier le moteur V1 stable ;
- utiliser Scenario B comme points ;
- utiliser ML, Isolation Forest ou SHAP ;
- utiliser un wording accusatoire ;
- conclure a une fraude ;
- remplacer la decision humaine ;
- recalculer le mart post-inspection depuis les tables DWH.

## 18. Acceptance criteria

La V1.1 est acceptable si :

- V1 reste executable et testee ;
- V1.1 utilise uniquement `mart.fact_post_inspection_attention_signal` ;
- Scenario A contribue aux points selon la confiance ;
- Scenario B reste a 0 point ;
- aucune duplication de points par zone ;
- les explications sont remplies et prudentes ;
- les rapports V1.1 sont generes ;
- la comparaison V1 vs V1.1 est disponible ;
- aucun changement VHS n'est introduit ;
- aucun ML n'est introduit.

## 19. Exact files to create later

Fichiers a creer pour implementation :

```text
etl/mart/compute_claim_attention_score_v1_1_candidate.py
tests/test_claim_attention_score_v1_1.py
```

Fichier documentaire cree par ce plan :

```text
docs/scoring/claim_attention_score_v1_1_post_inspection_integration_plan.md
```

Fichiers a ne pas modifier sans validation explicite :

```text
etl/mart/compute_claim_attention_score_v1_candidate.py
etl/mart/compute_claim_scoring_features_v1.py
etl/mart/compute_vhs_v3_candidate.py
```
