# Audit de faisabilite - Signaux post-inspection Inspection x Sinistre / Avenant

Date : 2026-07-07  
Statut : audit read-only, aucune ecriture en base  
Perimetre : module prioritaire IRIS demande par BNA Assurances

## 1. Positionnement metier

Ce module ne doit pas conclure a une fraude. Il doit identifier des situations post-inspection qui meritent une verification prioritaire.

Formulation recommandee :

```text
IRIS detecte des situations post-inspection necessitant une verification prioritaire.
```

Formulation a eviter :

```text
Fraude post-inspection detectee.
```

Le module repond a deux questions metier :

1. Apres une inspection STAFFIM, un sinistre est-il survenu rapidement sur une zone deja signalee comme defaillante ?
2. Apres une inspection STAFFIM, un avenant ou changement de couverture est-il intervenu rapidement sur un contrat potentiellement lie au vehicule inspecte ?

Le resultat attendu est un signal explicable, pas une accusation.

## 2. Contraintes de securite

Pour cette phase :

- ne pas modifier VHS ;
- ne pas modifier Claim Attention Score V1 ;
- ne pas creer de modele ML ;
- ne pas utiliser Isolation Forest, SHAP ou scoring opaque ;
- ne pas ecrire dans PostgreSQL ;
- ne pas creer ou alterer de tables ;
- ne pas utiliser de vocabulaire accusatoire ;
- traiter les jointures faibles comme des limites de confiance, pas comme des points d'attention.

## 3. Inventaire des sources identifiees

### 3.1 Inspections STAFFIM

Sources existantes :

| Table / script | Role | Observations |
|---|---|---|
| `staging.stg_inspection` | source staging inspection | contient l'immatriculation et les checkpoints bruts |
| `dwh.fact_inspection_vehicule` | une ligne par inspection vehicule | table centrale inspection |
| `dwh.fact_inspection_checkpoint` | une ligne par inspection x checkpoint | meilleure source pour les defauts par zone |
| `mart.dim_checkpoint` | referentiel checkpoints VHS | utile pour qualifier les checkpoints, sans modifier VHS |
| `mart.fact_vhs_penalty_detail` | detail checkpoint score VHS | utile comme contexte, pas comme preuve |
| `mart.fact_vhs_score` | score VHS par inspection | contexte uniquement |

Colonnes utiles cote inspection :

| Champ | Table | Usage |
|---|---|---|
| `inspection_key` | `dwh.fact_inspection_vehicule`, `dwh.fact_inspection_checkpoint` | identifiant metier inspection |
| `immatriculation_norm` | `dwh.fact_inspection_vehicule`, `dwh.fact_inspection_checkpoint` | meilleure cle de rattachement vehicule cote inspection |
| `vehicule_sk` | `dwh.fact_inspection_vehicule`, `dwh.fact_inspection_checkpoint` | cle technique vehicule, a traiter avec `0` = manquant |
| `date_inspection_sk` | `dwh.fact_inspection_vehicule`, `dwh.fact_inspection_checkpoint` | date inspection au format `YYYYMMDD` |
| `zone_controle` | `dwh.fact_inspection_checkpoint` | zone technique du checkpoint |
| `checkpoint_code` | `dwh.fact_inspection_checkpoint` | code du checkpoint |
| `checkpoint_libelle` | `dwh.fact_inspection_checkpoint` | libelle metier du checkpoint |
| `valeur_controle` | `dwh.fact_inspection_checkpoint` | etat observe |
| `est_anomalie` | `dwh.fact_inspection_checkpoint` | defaut constate |
| `est_anomalie_critique` | `dwh.fact_inspection_checkpoint` | defaut critique |

Mesures deja disponibles :

| Mesure | Valeur |
|---|---:|
| Inspections chargees | 286 |
| Inspections avec `vehicule_sk = 0` | 2 |
| Checkpoints chargees | 12 298 |
| Colonnes checkpoints detectees | 43 |
| Lignes checkpoint avec anomalie | 1 395 |
| Lignes checkpoint avec anomalie critique | 498 |
| Doublons `inspection_key` | 0 |
| Doublons `inspection_checkpoint_key` | 0 |

Lecture : la partie inspection est exploitable. Les defauts sont documentes au niveau checkpoint et zone. La limite principale n'est pas cote inspection, elle est cote rattachement au sinistre et au contrat.

### 3.2 Sinistres

Source centrale :

```text
dwh.fact_sinistre
```

Colonnes utiles :

| Champ | Usage |
|---|---|
| `fact_sinistre_sk` | cle technique sinistre, future `claim_sk` |
| `sinistre_garantie_key` | identifiant metier sinistre x garantie |
| `numero_sinistre` | numero sinistre |
| `code_garantie` | garantie sinistre |
| `client_sk` | rattachement client |
| `contrat_sk` | rattachement contrat |
| `vehicule_sk` | rattachement vehicule, mais couverture tres faible |
| `date_survenance_sk` | date evenement sinistre |
| `date_declaration_sk` | date declaration |
| `montant_evaluation` | montant declare/evalue |
| `motif_cloture_garantie` | contexte cloture |
| `etat_garantie_sinistre` | etat garantie sinistre |

Mesures deja disponibles :

| Mesure | Valeur |
|---|---:|
| Sinistres charges | 381 893 |
| Doublons grain `sinistre_garantie_key` | 0 |
| `vehicule_sk = 0` | 380 968 |
| `client_sk = 0` | 17 |
| `contrat_sk = 0` | 289 |
| `date_survenance_sk = 0` | 0 |
| `date_declaration_sk = 0` | 9 |
| `garantie_sk = 0` | 3 726 |
| `geo_sinistre_sk = 0` | 2 141 |
| Delais survenance -> declaration negatifs | 51 109 |

Lecture : `dwh.fact_sinistre` est solide pour le score dossier general, mais `vehicule_sk` est inutilisable comme seule cle de croisement post-inspection. Seulement 925 lignes de sinistre ont un `vehicule_sk` non nul.

### 3.3 Contrats et avenants

Source centrale :

```text
dwh.fact_contrat
```

Colonnes utiles :

| Champ | Usage |
|---|---|
| `fact_contrat_sk` | cle technique mouvement contrat |
| `contrat_mouvement_key` | grain contrat x avenant x mise a jour |
| `contrat_key` | identifiant contrat |
| `numero_contrat` | numero contrat |
| `numero_avenant` | numero avenant |
| `numero_mise_a_jour` | numero mise a jour |
| `contrat_sk` | cle contrat |
| `client_sk` | cle client |
| `produit_sk` | produit contrat |
| `date_debut_contrat_sk` | date debut contrat |
| `date_debut_effet_sk` | date debut effet |
| `date_derniere_operation_sk` | date derniere operation |
| `total_prime` | prime |
| `est_avenant` | indicateur avenant |
| `est_mise_a_jour` | indicateur mise a jour |
| `situation_contrat` | etat contrat |

Mesures deja disponibles :

| Mesure | Valeur |
|---|---:|
| Mouvements contrat charges | 585 514 |
| Doublons grain | 0 |
| `contrat_sk = 0` | 0 |
| `client_sk = 0` | 1 577 |
| `date_debut_contrat_sk = 0` | 8 |
| `date_debut_effet_sk = 0` | 6 |
| `date_derniere_operation_sk = 0` | 301 659 |
| `produit_sk = 0` | 67 914 |
| `numero_avenant` manquant | 0 |
| `numero_mise_a_jour` manquant | 0 |

Lecture : les mouvements et avenants existent. En revanche, la table ne prouve pas encore qu'une garantie precise a ete ajoutee ou modifiee, ni que le mouvement concerne le vehicule inspecte. Ce point doit etre audite avant de calculer des points d'attention.

## 4. Faisabilite par scenario

### 4.1 Scenario A - Inspection -> sinistre rapide

Regle metier candidate :

```text
inspection STAFFIM avant sinistre
+ delai court
+ defaut constate sur une zone
+ sinistre concernant la meme zone ou une zone proche
= signal post-inspection a examiner
```

Elements disponibles :

| Besoin | Disponibilite | Commentaire |
|---|---|---|
| Date inspection | Disponible | `date_inspection_sk` |
| Date sinistre | Disponible | `date_survenance_sk` |
| Defaut checkpoint | Disponible | `est_anomalie`, `est_anomalie_critique` |
| Zone defaut | Disponible | `zone_controle`, `checkpoint_libelle` |
| Lien vehicule inspection -> sinistre | Bloquant | `fact_sinistre.vehicule_sk` presque toujours `0` |
| Zone dommage sinistre | A auditer | pas de colonne zone dommage evidente dans `fact_sinistre` |
| Nature sinistre / garantie | Partiel | `code_garantie`, `dim_sinistre`, libelles cause possibles |

Decision readiness :

```text
PARTIEL - scenario metier pertinent, mais implementation mart non prete tant que le lien vehicule/immatriculation et la zone sinistre ne sont pas audites.
```

### 4.2 Scenario B - Inspection -> avenant / changement couverture

Regle metier candidate :

```text
inspection STAFFIM avant avenant
+ delai court
+ defaut constate
+ mouvement de garantie/couverture potentiellement lie au defaut
= signal post-inspection a examiner
```

Elements disponibles :

| Besoin | Disponibilite | Commentaire |
|---|---|---|
| Date inspection | Disponible | `date_inspection_sk` |
| Mouvement contrat / avenant | Disponible | `est_avenant`, `numero_avenant`, `numero_mise_a_jour` |
| Date effet / operation | Partiel | `date_debut_effet_sk` fiable, `date_derniere_operation_sk` souvent manquante |
| Defaut checkpoint | Disponible | `fact_inspection_checkpoint` |
| Lien inspection -> contrat | A auditer | pas encore prouve dans le DWH final |
| Changement garantie precis | A auditer | `fact_contrat` expose produit/prime/situation, pas le detail garantie ajoutee |
| Couverture pertinente pour le defaut | A auditer | necessite mapping garantie/produit/checkpoint |

Decision readiness :

```text
PARTIEL - les avenants existent, mais le lien inspection -> contrat et la preuve de changement de garantie doivent etre audites avant scoring.
```

## 5. Blocage principal : rattachement vehicule

Le blocage majeur est le suivant :

```text
dwh.fact_sinistre.vehicule_sk = 0 pour 380 968 lignes sur 381 893.
```

Consequences :

- une jointure directe `inspection.vehicule_sk = sinistre.vehicule_sk` aurait une couverture tres faible ;
- elle serait utile seulement pour un test de faisabilite haute confiance sur un petit sous-ensemble ;
- le module prioritaire ne doit pas etre construit sur cette seule cle ;
- il faut auditer une strategie alternative par immatriculation, contrat ou client + contrat + date.

Pistes de rattachement a tester en read-only :

| Strategie | Confiance | Couverture attendue | Statut |
|---|---|---:|---|
| `inspection.vehicule_sk` -> `sinistre.vehicule_sk` | Haute si non zero | Tres faible | test rapide uniquement |
| `inspection.immatriculation_norm` -> `dim_vehicule` -> `sinistre.vehicule_sk` | Haute si cle non zero | Tres faible cote sinistre | insuffisant seul |
| `inspection.immatriculation_norm` -> immatriculation brute sinistre staging | Potentiellement haute | Mesuree comme disponible cote sinistre staging | prioritaire pour audit |
| `inspection` -> vehicule -> contrat -> sinistre | Moyenne/haute | A mesurer | depend d'une table pont vehicule-contrat |
| `inspection` -> client + contrat + fenetre dates | Moyenne/faible | A mesurer | confiance reduite |
| `inspection` -> client seul + fenetre dates | Faible | Risque bruit | ne pas scorer en V1 |

### 5.1 Mesures complementaires sur l'immatriculation sinistre

Audit manuel read-only effectue le 2026-07-07 :

| Controle | Resultat | Lecture |
|---|---:|---|
| `staging.stg_sinistres` total | 381 893 | meme volume que `dwh.fact_sinistre` |
| lignes sinistre staging sans `immat` | 3 923 | 1,0 % environ |
| lignes sinistre staging avec `immat` renseignee | 377 970 | couverture brute tres forte |
| immatriculations brutes distinctes | 128 052 | avant suppression des caracteres non alphanumeriques |
| immatriculations normalisees distinctes | 128 032 | apres UPPER(REGEXP_REPLACE(TRIM(immat), '[^A-Z0-9]', '', 'g')) |
| lignes vides apres normalisation | 0 | la normalisation ne detruit pas les valeurs non vides |
| valeurs invalides evidentes (`0`, `NULL`, `PIETON`, etc.) | 0 | pas de bruit evident sur les valeurs non vides |
| lignes sinistre staging joignant `dwh.dim_vehicule` par `immat` | 925 | confirme la limite de `dim_vehicule` actuel |
| lignes sinistre staging avec `immat` non joignable a `dwh.dim_vehicule` | 377 045 | confirme que `dim_vehicule` est surtout alimente par inspections |
| vehicules dans `dwh.dim_vehicule` | 280 | dimension tres petite par rapport aux immatriculations sinistres |
| `vehicule_sk = 0` dans `dwh.dim_vehicule` | 0 | la dimension elle-meme n'a pas de ligne technique 0 |
Distribution des longueurs apres normalisation :

| Longueur normalisee | Lignes | Valeurs distinctes | Lecture |
|---:|---:|---:|---|
| 5 | 95 | 33 | format court atypique, volume faible |
| 6 | 880 | 355 | format court atypique, a controler |
| 7 | 8 980 | 3 649 | format plausible court |
| 8 | 92 178 | 35 970 | format courant |
| 9 | 275 587 | 87 896 | format dominant |
| 10 | 161 | 82 | format long atypique, volume faible |
| 11 | 21 | 8 | format long atypique |
| 12 | 2 | 1 | format long atypique |
| 13 | 4 | 3 | format long atypique |
| 14 | 6 | 4 | format long atypique |
| 15 | 56 | 31 | format long atypique |

Lecture : les longueurs 8 et 9 representent 367 765 lignes sur 377 970 immatriculations renseignees. La qualite globale est donc exploitable pour un bridge DWH, avec une file de controle dediee pour les formats courts/longs.

Conclusion :

```text
L'immatriculation brute de staging.stg_sinistres est le meilleur candidat de bridge read-only pour le module post-inspection.
En revanche, elle n'est pas encore portee par dwh.fact_sinistre ni gouvernee comme une dimension vehicule complete.
```

Implication :

- ne pas construire le module sur `fact_sinistre.vehicule_sk` seul ;
- ne pas elargir `dwh.dim_vehicule` sans decision DWH separee ;
- utiliser `staging.stg_sinistres.immat` uniquement comme bridge d'audit pour valider la faisabilite ;
- si le module est valide, prevoir une specification dediee de bridge immatriculation ou d'enrichissement vehicule.

Plan DWH dedie :

```text
docs/dwh/vehicle_dimension_correction_plan.md
```

Note importante sur les dates :

```text
date_survenance_sk <= date_inspection_sk + 90
```

ne doit pas etre utilise comme calcul de delai, car les cles dates sont des entiers `YYYYMMDD`. Le calcul doit parser les cles en vraies dates ou passer par `dim_date`, puis calculer un nombre de jours calendaire.

## 6. Mapping zones et couvertures a auditer

### 6.1 Zones inspection disponibles

Les zones checkpoint existantes sont notamment :

```text
TOUR_DU_VEHICULE
INTERIEUR
SOUS_CAPOT
SOUS_VEHICULE
ENTRETIEN
```

Pour le scenario A, il faudra construire un mapping prudent :

| Zone inspection | Exemple interpretation | Statut |
|---|---|---|
| `TOUR_DU_VEHICULE` | carrosserie, optiques, pare-chocs, portes | exploitable si sinistre expose zone/cause |
| `INTERIEUR` | habitacle, accessoires interieurs | a relier avec prudence |
| `SOUS_CAPOT` | moteur, organes visibles sous capot | a relier a nature mecanique si disponible |
| `SOUS_VEHICULE` | chassis, soubassement, trains | a relier a cause/nature si disponible |
| `ENTRETIEN` | etat general / maintenance | contexte, pas preuve de zone |

### 6.2 Zone sinistre

La table `dwh.fact_sinistre` ne montre pas encore de champ explicite du type `claim_damage_area`. Les candidats indirects sont :

- `code_garantie` ;
- `garantie_sk` / `dwh.dim_garantie` ;
- `sinistre_sk` / `dwh.dim_sinistre` ;
- `motif_cloture_garantie` ;
- `etat_garantie_sinistre`.

Une analyse de schema et de valeurs est necessaire pour savoir si un vrai `area_match_flag` est defendable.

### 6.3 Couverture avenant

Pour le scenario B, il faudra verifier si le DWH permet de detecter :

- une garantie ajoutee ;
- une garantie retiree ;
- une modification de formule ;
- une hausse de prime liee a couverture ;
- un changement de produit ;
- un changement de date effet apres inspection.

Si seule l'existence d'un avenant est disponible, le signal doit rester a confiance reduite.

## 7. Table cible proposee

Table a creer plus tard, apres audit de faisabilite et validation metier :

```text
mart.fact_post_inspection_attention_signal
```

Grain :

```text
une ligne = un signal post-inspection potentiel
```

Colonnes proposees :

| Colonne | Description |
|---|---|
| `post_inspection_signal_sk` | cle technique |
| `signal_run_id` | identifiant run |
| `signal_version` | version regles |
| `scenario_code` | code scenario |
| `scenario_label` | libelle scenario |
| `inspection_sk` | cle inspection si disponible |
| `inspection_key` | identifiant metier inspection |
| `claim_sk` | cle sinistre si scenario A |
| `contract_sk` | cle contrat si scenario B |
| `client_sk` | cle client |
| `vehicle_sk` | cle vehicule, `0` traite comme manquant |
| `immatriculation` | immatriculation normalisee si disponible |
| `inspection_date` | date inspection |
| `claim_date` | date sinistre |
| `avenant_date` | date avenant / effet / operation |
| `days_inspection_to_claim` | delai inspection -> sinistre |
| `days_inspection_to_avenant` | delai inspection -> avenant |
| `defective_area` | zone defaut inspection |
| `defective_checkpoint_code` | checkpoint defaillant |
| `defective_checkpoint_label` | libelle checkpoint |
| `claim_area` | zone dommage si disponible |
| `claim_guarantee_code` | garantie sinistre |
| `guarantee_changed` | garantie/couverture modifiee si prouvee |
| `area_match_flag` | correspondance zone defaut / zone sinistre |
| `coverage_relevance_flag` | couverture coherente avec defaut |
| `attention_points` | points du signal, si regle validee |
| `attention_level` | niveau attention |
| `confidence_level` | niveau confiance |
| `linkage_method` | methode de rattachement utilisee |
| `linkage_quality` | qualite du rattachement |
| `business_explanation` | explication lisible gestionnaire |
| `created_at` | timestamp de creation |

Codes scenarios candidats :

```text
A_INSPECTION_TO_CLAIM_SAME_AREA
B_INSPECTION_TO_AVENANT_COVERAGE_CHANGE
```

## 8. Regles candidates prudentes

Ces regles sont candidates uniquement. Elles ne doivent pas etre activees tant que le lien et les champs metier ne sont pas audites.

### 8.1 Scenario A

Conditions minimales :

```text
inspection_date < claim_date
days_inspection_to_claim between 0 and 90
inspection checkpoint has est_anomalie = true
vehicle/contract linkage quality is at least medium
```

Seuils candidats :

| Condition | Niveau candidat |
|---|---|
| delai <= 7 jours + zone coherente | fort |
| delai <= 30 jours + zone coherente | moyen |
| delai <= 90 jours + zone coherente | faible |
| delai <= 30 jours sans zone sinistre fiable | confiance reduite |
| inspection apres sinistre | exclu |

### 8.2 Scenario B

Conditions minimales :

```text
inspection_date < avenant_date
days_inspection_to_avenant between 0 and 90
inspection checkpoint has est_anomalie = true
contract linkage quality is at least medium
```

Seuils candidats :

| Condition | Niveau candidat |
|---|---|
| delai <= 7 jours + couverture liee | fort |
| delai <= 30 jours + couverture liee | moyen |
| delai <= 90 jours + couverture liee | faible |
| avenant sans detail garantie | confiance reduite |
| avenant avant inspection | exclu |

## 9. Confiance et limites

La confiance doit etre separee de l'attention.

| Niveau confiance | Definition candidate |
|---|---|
| `HIGH` | rattachement direct et non ambigu, dates valides, zone/couverture exploitable |
| `MEDIUM` | rattachement plausible mais avec champ zone/couverture partiel |
| `LOW` | rattachement faible, zone inconnue, ou seulement lien client/date |
| `NOT_READY` | champ cle manquant ou lien non defendable |

Principes :

- une donnee manquante baisse la confiance ;
- une cle technique `0` est manquante ;
- une date `0` est manquante ;
- une inspection posterieure au sinistre ou a l'avenant est exclue ;
- un lien client seul ne doit pas produire de points d'attention ;
- le VHS global ne doit pas devenir une preuve.

## 10. Rapports qualite recommandes

Repertoire propose :

```text
data/quality_reports/scoring/post_inspection_signals/readiness/
```

Fichiers recommandes :

| Fichier | Objectif |
|---|---|
| `inspection_readiness_summary.csv` | couverture inspection, dates, immatriculations, vehicule_sk |
| `inspection_checkpoint_area_summary.csv` | anomalies par zone/checkpoint |
| `claim_vehicle_linkage_summary.csv` | couverture vehicule sinistre et jointures possibles |
| `claim_raw_immat_profile.csv` | couverture de `staging.stg_sinistres.immat`, valeurs invalides evidentes et jointure vers `dim_vehicule` |
| `claim_raw_immat_top_values.csv` | top immatriculations normalisees cote sinistre staging |
| `claim_raw_immat_length_distribution.csv` | distribution des longueurs apres normalisation immatriculation |
| `claim_damage_area_candidate_values.csv` | audit des champs candidats zone/nature sinistre |
| `contract_avenant_readiness_summary.csv` | couverture avenants et dates mouvement |
| `inspection_to_claim_candidate_links.csv` | echantillon liens scenario A, sans ecriture DB |
| `inspection_to_avenant_candidate_links.csv` | echantillon liens scenario B, sans ecriture DB |
| `post_inspection_readiness_decision.csv` | decision GO / PARTIAL / BLOCKED par scenario |

## 11. Tests recommandes

Tests unitaires a prevoir avant implementation mart :

- parsing des dates `YYYYMMDD` ;
- traitement de `0` comme manquant pour toutes les cles DWH ;
- exclusion des evenements avant inspection ;
- calcul des delais inspection -> sinistre ;
- calcul des delais inspection -> avenant ;
- classification de confiance selon la methode de jointure ;
- mapping checkpoint -> zone normalisee ;
- mapping garantie/nature sinistre -> zone/couverture, si disponible ;
- non-attribution de points lorsque la jointure est faible.

Tests de donnees a prevoir dans le notebook read-only :

- nombre total inspections = 286 ;
- nombre total checkpoints = 12 298 ;
- nombre total sinistres = 381 893 ;
- `vehicule_sk = 0` compte comme manquant ;
- couverture des jointures par methode ;
- distribution des delais 0-7, 8-30, 31-90 jours ;
- aucune ligne avec inspection apres sinistre dans les candidats valides ;
- aucun signal fort sans rattachement defendable.

## 12. Prochaine etape recommandee

Ne pas coder la table mart maintenant.

La prochaine etape est un notebook read-only :

```text
notebooks/validation_scoring/02_post_inspection_signal_readiness.ipynb
```

Objectifs du notebook :

1. lire les schemas existants et les donnees utiles ;
2. mesurer les jointures inspection -> sinistre par `vehicule_sk` non nul ;
3. mesurer les possibilites de jointure par immatriculation brute/staging si disponible ;
4. verifier s'il existe une table pont vehicule -> contrat ;
5. mesurer les jointures inspection -> contrat -> avenant ;
6. auditer les valeurs candidates de zone/nature sinistre ;
7. auditer les changements de produit/garantie/couverture cote avenant ;
8. produire les rapports qualite read-only ;
9. conclure GO / PARTIAL / BLOCKED pour Scenario A et Scenario B.

## 13. Roadmap proposee

| Etape | Livrable | Decision |
|---|---|---|
| 1 | Audit read-only de faisabilite | en cours |
| 2 | Notebook `02_post_inspection_signal_readiness.ipynb` | a faire |
| 3 | Rapports qualite linkage | a faire |
| 4 | Specification fonctionnelle du signal | apres mesures |
| 5 | Implementation `mart.fact_post_inspection_attention_signal` | seulement si lien valide |
| 6 | Integration dans Claim Attention V1.1/V2 | apres validation du module separe |

## 14. Decision actuelle

Decision :

```text
PARTIAL READINESS
```

Justification :

- l'information inspection et checkpoint est disponible et propre ;
- les defauts par zone sont exploitables ;
- les sinistres et contrats sont disponibles ;
- les avenants existent dans `dwh.fact_contrat` ;
- le lien direct vehicule inspection -> sinistre est bloque par la couverture tres faible de `fact_sinistre.vehicule_sk` ;
- la zone dommage sinistre n'est pas encore prouvee ;
- le detail de garantie ajoutee/modifiee cote avenant n'est pas encore prouve ;
- une implementation mart maintenant risquerait de produire des signaux peu defendables.

Conclusion :

Priorite technique immediate : corriger et gouverner le socle `dwh.dim_vehicule` avant de creer le mart post-inspection.
Objectif : integrer les immatriculations issues des sinistres dans une dimension vehicule gouvernee, puis recharger `dwh.fact_sinistre` pour reduire fortement les `vehicule_sk = 0`.

```text
Le module est prioritaire, mais il doit commencer par un audit de linkage read-only.
Claim Attention Score V1 reste intact.
Le signal post-inspection pourra etre integre plus tard dans Claim Attention V1.1 ou V2, apres validation de sa couverture et de sa confiance.
```






