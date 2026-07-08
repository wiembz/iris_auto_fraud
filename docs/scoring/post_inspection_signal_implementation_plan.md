# Plan d'implementation du mart post-inspection IRIS

> **Module :** Inspection x Sinistre - signaux post-inspection a examiner  
> **Version cible :** `IRIS_POST_INSPECTION_SIGNAL_V1_CANDIDATE`  
> **Principe :** aide a l'analyse humaine, sans conclusion automatique

---

## 1. Objective

Ce document decrit le plan technique pour creer, dans une phase ulterieure, le
mart explicatif :

```text
mart.fact_post_inspection_attention_signal
```

Le mart doit identifier des situations post-inspection necessitant une
verification prioritaire par un gestionnaire. Il ne constitue pas une preuve, ne
declenche aucune decision automatique, et ne modifie pas le Claim Attention
Score V1.

## 2. Scope

La premiere implementation couvre uniquement le Scenario A, deja mesure comme
pret pour une specification technique.

Le Scenario B reste limite a un suivi readiness, car le changement exact de
garantie, produit ou couverture n'est pas encore prouve.

Le module reste separe de :

- VHS ;
- Claim Attention Score V1 ;
- tout modele ML ;
- tout scoring global.

## 3. Scenario A GO

Le Scenario A est :

```text
Inspection STAFFIM -> Sinistre sur le meme vehicule dans les 0 a 90 jours
```

Statut : **GO pour implementation mart V1 candidate**.

Un signal candidat est cree seulement si :

- l'inspection et le sinistre partagent le meme `vehicule_sk` non nul ;
- la date d'inspection est valide ;
- la date du sinistre est valide ;
- l'inspection est anterieure ou egale au sinistre ;
- le delai est compris entre 0 et 90 jours calendaires ;
- le contexte d'anomalie inspection est agrege et expose prudemment.

## 4. Scenario B PARTIAL

Le Scenario B est :

```text
Inspection STAFFIM -> Avenant ou mouvement contrat dans les 0 a 90 jours
```

Statut : **PARTIAL / readiness-only**.

Le timing inspection -> avenant est mesurable, mais le detail de changement de
garantie, produit ou couverture doit etre confirme avant exploitation metier.

Pour V1 candidate :

- ne pas creer de signal metier fort Scenario B ;
- ne pas attribuer de points ;
- ne pas integrer au Claim Attention Score ;
- conserver uniquement des controles readiness/reporting si les sources sont
  disponibles.

## 5. Source tables

Sources principales Scenario A :

| Table | Usage |
|---|---|
| `dwh.fact_inspection_vehicule` | inspection, vehicule, date inspection |
| `dwh.fact_inspection_checkpoint` | zones, checkpoints, anomalies documentees |
| `dwh.fact_sinistre` | sinistre, vehicule, date de survenance, garantie |
| `dwh.dim_vehicule` | contexte vehicule et immatriculation si necessaire |

Sources optionnelles :

| Table | Usage |
|---|---|
| `dwh.fact_contrat` | readiness Scenario B uniquement |
| date dimension | conversion ou verification des dates si utile |

## 6. Target grain

Grain cible recommande :

```text
signal_run_id
+ signal_version
+ scenario_code
+ inspection_sk
+ claim_sk
+ defective_zone
```

Ce grain evite une ligne par checkpoint et limite la multiplication artificielle
des signaux. Les checkpoints defaillants d'une meme zone sont agreges dans une
seule ligne explicative.

Contrainte attendue :

```text
UNIQUE(signal_run_id, signal_version, scenario_code, inspection_sk, claim_sk, defective_zone)
```

## 7. Join logic

Join Scenario A :

```text
dwh.fact_inspection_vehicule.vehicule_sk = dwh.fact_sinistre.vehicule_sk
```

Conditions obligatoires :

- `vehicule_sk <> 0` cote inspection ;
- `vehicule_sk <> 0` cote sinistre ;
- dates converties en vraies dates ;
- `inspection_date <= claim_date` ;
- `days_inspection_to_claim BETWEEN 0 AND 90`.

La methode de rattachement doit etre tracee :

```text
linkage_method = VEHICULE_SK
```

Les rattachements faibles par client, contrat ou immatriculation brute ne doivent
pas produire de signal V1. Ils peuvent etre suivis dans des rapports
d'exclusion ou de readiness.

## 8. Date logic

Les dates doivent etre parsees en vraies dates calendaires avant tout calcul.

Regles :

- traiter `0` comme date manquante ;
- rejeter les dates invalides ;
- rejeter les dates futures incoherentes si le controle existe dans le projet ;
- calculer le delai par soustraction de dates reelles ;
- ne jamais utiliser une arithmetique directe du type `YYYYMMDD + 90`.

Colonnes derivees :

```text
inspection_date
claim_date
days_inspection_to_claim
delay_bucket
```

## 9. Anomaly aggregation

Les anomalies viennent de `dwh.fact_inspection_checkpoint`.

Aggregation par :

```text
inspection_sk + defective_zone
```

Champs agreges recommandes :

```text
defective_checkpoint_count
critical_checkpoint_count
defective_checkpoint_codes
representative_checkpoint_labels
defective_zone
```

Si aucune anomalie n'est documentee, le candidat peut etre conserve dans les
rapports de validation, mais ne doit pas etre presente comme signal fort.

## 10. Delay buckets

Buckets V1 :

| Delai | Libelle technique | Lecture prudente |
|---|---|---|
| 0-7 jours | `DAYS_0_7` | Chronologie post-inspection courte |
| 8-30 jours | `DAYS_8_30` | Proximite chronologique moyenne |
| 31-90 jours | `DAYS_31_90` | Proximite chronologique faible, a examiner avec prudence |

Tout delai negatif ou superieur a 90 jours est exclu du mart V1 candidate.

## 11. Confidence rules

La confiance mesure la robustesse technique du lien. Elle ne transforme jamais
un signal en preuve.

| Niveau | Conditions |
|---|---|
| `HIGH` | Meme `vehicule_sk`, dates valides, delai 0-30 jours, anomalie documentee, zone disponible |
| `MEDIUM` | Meme `vehicule_sk`, dates valides, delai 31-90 jours, anomalie documentee |
| `LOW` | Meme `vehicule_sk`, dates valides, contexte anomalie ou zone faible |
| `NOT_READY` | Cle vehicule manquante, date invalide, inspection apres sinistre, ou lien faible |

Les lignes `NOT_READY` ne doivent pas etre ecrites comme signaux metier
exploitables dans le mart final. Elles doivent etre mesurees dans les rapports.

## 12. Attention labels

Libelles autorises :

- `Signal post-inspection a examiner`
- `Verification prioritaire suggeree`
- `Chronologie post-inspection courte`
- `Contexte technique documente`
- `Confiance elevee`
- `Confiance moyenne`
- `Confiance faible`

Les libelles doivent rester dans une logique d'aide a l'analyse et de
priorisation. Ils ne doivent pas formuler de conclusion accusatoire.

## 13. Target mart columns

Colonnes cibles proposees :

```text
post_inspection_signal_sk
signal_run_id
signal_version
scenario_code
scenario_label
inspection_sk
claim_sk
contract_sk
client_sk
vehicule_sk
immatriculation
inspection_date
claim_date
avenant_date
days_inspection_to_claim
days_inspection_to_avenant
delay_bucket
defective_zone
defective_checkpoint_count
critical_checkpoint_count
defective_checkpoint_codes
representative_checkpoint_labels
claim_area
claim_guarantee_code
claim_guarantee_label
zone_match_status
linkage_method
attention_level
confidence_level
business_explanation
created_at
```

Pour Scenario A V1, les champs `avenant_date` et
`days_inspection_to_avenant` restent nuls.

## 14. Quality reports

Dossier recommande :

```text
data/quality_reports/scoring/post_inspection_signals/v1_candidate/
```

Rapports attendus :

```text
post_inspection_signal_load_summary.csv
post_inspection_duplicate_grain_check.csv
post_inspection_delay_distribution.csv
post_inspection_confidence_distribution.csv
post_inspection_zone_distribution.csv
post_inspection_excluded_candidates.csv
post_inspection_validation_summary.csv
post_inspection_validation_summary.md
scenario_b_readiness_context.csv
```

Les rapports doivent permettre de verifier les volumes, les exclusions, les
niveaux de confiance, les zones et la non-duplication du grain.

## 15. Unit tests

Fichier de test a creer plus tard :

```text
tests/test_post_inspection_attention_signal_v1.py
```

Tests unitaires recommandes :

- parsing date key `YYYYMMDD` ;
- rejet des dates `0` ou invalides ;
- calcul du delai sur dates reelles ;
- mapping des buckets 0-7, 8-30, 31-90 ;
- exclusion des `vehicule_sk` manquants ou egaux a `0` ;
- exclusion des sinistres avant inspection ;
- aggregation des checkpoints par zone ;
- attribution `confidence_level` ;
- generation d'une explication metier non accusatoire.

## 16. Data validation tests

Tests de validation donnees a executer apres calcul :

- nombre total de signaux par run ;
- absence de doublons sur le grain cible ;
- aucun delai negatif ;
- aucun delai superieur a 90 jours ;
- aucune ligne avec `vehicule_sk = 0` ;
- aucune ligne avec date inspection ou sinistre manquante ;
- `confidence_level` non nul ;
- `attention_level` non nul ;
- `business_explanation` non nul ;
- Scenario B absent des signaux metier V1, sauf reporting readiness separe ;
- aucune regression Claim Attention Score V1 ;
- aucune regression VHS.

## 17. signal_version and signal_run_id strategy

Version cible :

```text
signal_version = IRIS_POST_INSPECTION_SIGNAL_V1_CANDIDATE
```

Identifiant de run :

```text
signal_run_id = IRIS_POST_INSPECTION_SIGNAL_V1_CANDIDATE_YYYYMMDD_HHMMSS
```

Le mart doit etre recalculable et tracable par `signal_run_id`.

Chaque execution doit :

- generer un `signal_run_id` unique ;
- ecrire toutes les lignes avec le meme `signal_run_id` ;
- permettre la suppression/reprise ciblee d'un run ;
- produire les rapports avec le meme identifiant de run.

## 18. Execution order

Ordre cible pour une future implementation :

1. Creer le script candidat sous `etl/mart/`.
2. Definir le DDL garde par `CREATE TABLE IF NOT EXISTS`.
3. Lire les sources DWH.
4. Parser les dates.
5. Calculer les liens Scenario A.
6. Agreger les anomalies checkpoint par zone.
7. Calculer buckets, confiance et libelles.
8. Valider le grain et les controles qualite.
9. Ecrire le mart candidat.
10. Generer les rapports qualite.
11. Lancer les tests unitaires et validations.

Ne pas integrer ce module au Claim Attention Score V1 dans cette phase.

## 19. Acceptance criteria

La future implementation est acceptable si :

- le grain est deterministe ;
- aucun doublon n'existe sur le grain cible ;
- seules les paires post-inspection 0-90 jours sont ecrites ;
- les dates sont calculees avec une vraie logique calendrier ;
- `confidence_level` est renseigne ;
- `attention_level` est renseigne ;
- `business_explanation` est renseigne ;
- les rapports qualite sont generes ;
- Scenario B reste `PARTIAL` et separe ;
- VHS n'est pas modifie ;
- Claim Attention Score V1 n'est pas modifie ;
- aucun wording accusatoire n'est introduit.

## 20. Non-goals

Cette phase ne vise pas a :

- confirmer une fraude ;
- produire une decision automatique ;
- ajouter des points au Claim Attention Score ;
- modifier VHS ;
- modifier Claim Attention Score V1 ;
- creer un modele ML ;
- utiliser Isolation Forest ;
- utiliser SHAP ;
- implementer Scenario B comme signal metier fort ;
- remplacer l'analyse humaine.

## 21. Exact files to create later

Fichiers a creer lors de l'implementation future :

```text
etl/mart/compute_post_inspection_attention_signal_v1_candidate.py
tests/test_post_inspection_attention_signal_v1.py
```

Fichier documentaire cree par ce plan :

```text
docs/scoring/post_inspection_signal_implementation_plan.md
```

Fichiers a ne pas modifier sans validation separee :

```text
etl/mart/compute_claim_attention_score_v1_candidate.py
etl/mart/compute_claim_scoring_features_v1.py
etl/mart/compute_vhs_v3_candidate.py
```
