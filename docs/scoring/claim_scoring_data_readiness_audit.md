# Audit de préparation des données pour le score d’attention dossier IRIS

> **Module :** Claim Attention Scoring / Score d’attention dossier  
> **Projet :** IRIS Auto Fraud Decision Platform — BNA Assurances  
> **Statut :** Audit de préparation des données — V1  
> **Version cible :** `IRIS_CLAIM_ATTENTION_V1_CANDIDATE`  
> **Principe :** audit read-only avant toute implémentation du scoring  
> **Auteur :** Wiem Benzarti

---

## 1. Objectif du document

Ce document définit l’audit de préparation des données nécessaire avant la construction du **score d’attention dossier IRIS**.

L’objectif est de vérifier si le Data Warehouse PostgreSQL contient les données, jointures, clés et indicateurs nécessaires pour construire un score de priorisation des dossiers sinistres automobiles.

Ce document ne crée pas encore le score.  
Il ne définit pas encore les règles finales.  
Il ne modifie aucune table.  
Il sert à évaluer si les données sont prêtes.

Le score d’attention dossier doit rester une **aide à l’analyse**, et non une preuve de fraude.

> **Les éléments présentés constituent une aide à l’analyse ; la décision finale reste sous la responsabilité du gestionnaire.**

---

## 2. Positionnement de l’audit

Avant de construire un score dossier, il faut s’assurer que les données sont suffisamment fiables.

Un score construit sur des jointures faibles, des clés manquantes ou des dimensions incomplètes pourrait produire des signaux trompeurs.

L’audit de préparation des données répond donc à trois questions :

1. Les données nécessaires au scoring sont-elles disponibles ?
2. Les jointures entre les entités métier sont-elles suffisamment fiables ?
3. Les limites de qualité des données sont-elles connues et documentées ?

Cet audit doit être réalisé avant :

- la création du feature mart scoring ;
- la définition des seuils ;
- l’implémentation du score V1 ;
- la publication Power BI ;
- toute interprétation métier des résultats.

---

## 3. Périmètre fonctionnel audité

Le périmètre de l’audit est limité aux **sinistres automobiles**.

Le score V1 ne doit pas inclure les branches non automobiles.

### 3.1 Entité centrale

L’entité centrale du futur scoring est le **dossier sinistre automobile**.

Chaque dossier sinistre devra idéalement pouvoir être relié à :

- un client ;
- un contrat ;
- un véhicule ;
- une garantie ;
- une agence ;
- une géographie ;
- un historique de sinistres ;
- un conducteur ou tiers si disponible ;
- une inspection STAFFIM / VHS si disponible.

### 3.2 Granularité attendue

La granularité cible du futur scoring est :

```text
1 ligne = 1 dossier sinistre automobile
```

Le futur feature mart devra donc produire une table du type :

`mart.fact_claim_scoring_features`

avec une ligne par dossier.

---

## 4. Sources de données à inspecter

L’audit doit inspecter les tables du DWH et des marts déjà construits.

Les noms exacts peuvent varier selon l’implémentation actuelle, mais les familles suivantes doivent être recherchées.

| Famille | Tables ou zones probables | Objectif |
|---|---|---|
| **Sinistres** | `fact_sinistre`, tables claim, tables auto | Identifier le dossier central |
| **Clients** | `dim_client` | Rattacher le sinistre à une personne ou entité |
| **Contrats** | `dim_contrat`, `fact_production` | Analyser le contexte contrat |
| **Véhicules** | `dim_vehicule` | Suivre l’historique véhicule |
| **Garanties** | `dim_garantie` | Limiter le périmètre auto et analyser les montants |
| **Agences** | `dim_agence` | Rattacher le dossier au réseau BNA |
| **Géographie** | `dim_geo`, tables région/gouvernorat/localité | Construire les signaux géographiques |
| **Tiers** | tables tiers / adversaire si disponibles | Identifier les récurrences tiers |
| **Conducteurs** | tables conducteur si disponibles | Identifier les récurrences conducteur |
| **VHS** | `mart.fact_vhs_score`, `mart.fact_vhs_penalty_detail` | Ajouter le contexte technique véhicule |
| **Référentiels** | tables de mapping | Vérifier les libellés, codes et `UNKNOWN` |

---

## 5. Questions clés de readiness

L’audit doit répondre aux questions suivantes.

### 5.1 Questions sur les sinistres
- Combien de dossiers sinistres automobiles sont disponibles ?
- Quelle est la période couverte ?
- Les dates de sinistre sont-elles disponibles ?
- Les dates de déclaration sont-elles disponibles ?
- Les montants sont-ils disponibles ?
- Les garanties sont-elles correctement rattachées ?
- Le périmètre automobile est-il clairement isolé ?

### 5.2 Questions sur les clients
- Chaque sinistre est-il relié à un client ?
- Le client possède-t-il une clé stable ?
- Peut-on calculer l’historique sinistre du client ?
- Existe-t-il des clients `UNKNOWN` ?
- Existe-t-il des doublons clients ?
- La migration 2019 affecte-t-elle les identifiants clients ?

### 5.3 Questions sur les contrats
- Chaque sinistre est-il relié à un contrat ?
- La date de début du contrat est-elle disponible ?
- La date de fin est-elle disponible ?
- Les avenants ou modifications sont-ils exploitables ?
- Peut-on détecter un sinistre proche du début de contrat ?
- Peut-on détecter un changement récent de garantie ?

### 5.4 Questions sur les véhicules
- Chaque sinistre automobile est-il relié à un véhicule ?
- L’immatriculation est-elle disponible et fiable ?
- Peut-on suivre l’historique sinistre du même véhicule ?
- Peut-on relier le véhicule à une inspection STAFFIM ?
- Les véhicules `UNKNOWN` sont-ils nombreux ?
- Les changements d’immatriculation ou formats différents sont-ils traités ?

### 5.5 Questions sur les tiers et conducteurs
- Existe-t-il une table tiers exploitable ?
- Le tiers possède-t-il une clé stable ?
- Peut-on détecter la répétition d’un même tiers ?
- Peut-on détecter une répétition client/tiers ?
- Le conducteur est-il disponible ?
- Le conducteur est-il distinct du client ?
- Le conducteur peut-il être suivi dans le temps ?

### 5.6 Questions sur les montants
- Le montant du sinistre est-il disponible ?
- Le montant est-il numérique et exploitable ?
- Y a-t-il des montants nuls ou négatifs ?
- Y a-t-il des valeurs extrêmes ?
- Peut-on comparer les montants par garantie ?
- Peut-on comparer les montants par région/agence ?
- Peut-on calculer des percentiles ou ratios ?

### 5.7 Questions sur la géographie
- La région du client est-elle disponible ?
- La région de l’agence est-elle disponible ?
- Le lieu du sinistre est-il disponible ?
- Les gouvernorats, délégations ou localités sont-ils mappés ?
- Existe-t-il beaucoup de valeurs `UNKNOWN` ?
- Existe-t-il des incohérences entre agence, région et lieu sinistre ?
- La partie GEO de l’ETL est-elle stable ?

### 5.8 Questions sur VHS
- Le VHS est-il rattachable au véhicule ou à l’immatriculation ?
- Peut-on identifier une inspection avant le sinistre ?
- Peut-on calculer le délai entre inspection et sinistre ?
- Le score VHS est-il disponible ?
- Le niveau d’attention VHS est-il disponible ?
- Le taux de rattachement VHS aux sinistres est-il suffisant ?

---

## 6. Indicateurs candidats à vérifier

Le futur score d’attention dossier s’appuiera sur plusieurs familles de signaux. L’audit doit vérifier si les indicateurs candidats peuvent être calculés.

### 6.1 Récurrence client

| Indicateur candidat | Description | Readiness attendue |
|---|---|---|
| `client_claim_count_total` | Nombre total de sinistres du client | Client relié au sinistre |
| `client_claim_count_12m` | Nombre de sinistres client sur 12 mois | Date sinistre disponible |
| `client_claim_count_24m` | Nombre de sinistres client sur 24 mois | Historique suffisant |
| `days_since_previous_claim` | Délai depuis le précédent sinistre | Tri chronologique fiable |

### 6.2 Récurrence véhicule

| Indicateur candidat | Description | Readiness attendue |
|---|---|---|
| `vehicle_claim_count_total` | Nombre total de sinistres du véhicule | Véhicule relié au sinistre |
| `vehicle_claim_count_12m` | Nombre de sinistres véhicule sur 12 mois | Date sinistre disponible |
| `vehicle_claim_count_24m` | Nombre de sinistres véhicule sur 24 mois | Historique suffisant |
| `vehicle_changed_recently_flag` | Changement récent de véhicule | Données contrat/véhicule exploitables |

### 6.3 Récurrence tiers / conducteur

| Indicateur candidat | Description | Readiness attendue |
|---|---|---|
| `third_party_claim_count_total` | Nombre d’occurrences du même tiers | Tiers identifié |
| `client_third_party_pair_count` | Répétition du couple client/tiers | Client et tiers reliés |
| `driver_claim_count_total` | Nombre de sinistres par conducteur | Conducteur identifié |
| `same_driver_vehicle_count` | Répétition conducteur/véhicule | Conducteur et véhicule reliés |

### 6.4 Chronologie

| Indicateur candidat | Description | Readiness attendue |
|---|---|---|
| `days_contract_start_to_claim` | Délai entre début contrat et sinistre | Date début contrat disponible |
| `days_claim_to_declaration` | Délai entre sinistre et déclaration | Deux dates disponibles |
| `recent_contract_change_flag` | Modification contrat récente | Historique avenants disponible |
| `recent_guarantee_change_flag` | Changement de garantie récent | Historique garantie disponible |

### 6.5 Montants

| Indicateur candidat | Description | Readiness attendue |
|---|---|---|
| `claim_amount` | Montant du dossier | Montant disponible |
| `amount_vs_guarantee_median_ratio` | Ratio par rapport à la médiane garantie | Garantie fiable |
| `amount_percentile_by_guarantee` | Percentile par garantie | Volume suffisant |
| `amount_vs_region_median_ratio` | Ratio par rapport à la médiane région | GEO fiable |
| `high_amount_flag` | Montant atypique | Seuil ou percentile défini |

### 6.6 Géographie

| Indicateur candidat | Description | Readiness attendue |
|---|---|---|
| `claim_geo_sk` | Géographie du sinistre | Lieu sinistre mappé |
| `client_geo_sk` | Géographie du client | Client géographiquement mappé |
| `agency_geo_sk` | Géographie agence | Agence mappée |
| `geo_mismatch_flag` | Incohérence client/agence/sinistre | Trois géographies fiables |
| `unknown_geo_flag` | Géographie inconnue | `UNKNOWN` documentés |
| `same_location_claim_count` | Récurrence même lieu | Localité exploitable |

### 6.7 VHS

| Indicateur candidat | Description | Readiness attendue |
|---|---|---|
| `linked_vhs_score` | Score technique véhicule | Rattachement inspection/véhicule |
| `vhs_attention_level` | Niveau métier VHS | VHS disponible |
| `days_between_vhs_and_claim` | Délai inspection/sinistre | Dates disponibles |
| `vhs_before_claim_flag` | Inspection avant sinistre | Chronologie fiable |

### 6.8 Qualité des données

| Indicateur candidat | Description | Readiness attendue |
|---|---|---|
| `missing_keys_count` | Nombre de clés manquantes | Clés auditées |
| `unknown_dimensions_count` | Nombre de dimensions `UNKNOWN` | Dimensions standardisées |
| `weak_join_flag` | Jointure incertaine | Règles de jointure documentées |
| `migration_2019_flag` | Effet migration potentiel | Période 2019 identifiée |

---

## 7. Contrôles qualité à réaliser

L’audit doit produire des contrôles qualité structurés.

### 7.1 Contrôles de volumétrie
- **Nombre total de sinistres** : Comprendre la base de calcul
- **Nombre de sinistres automobiles** : Vérifier le périmètre
- **Nombre de sinistres scorables** : Identifier les dossiers utilisables
- **Nombre de clients distincts** : Mesurer la profondeur client
- **Nombre de véhicules distincts** : Mesurer la profondeur véhicule
- **Nombre d’agences distinctes** : Vérifier la couverture réseau
- **Nombre de garanties auto** : Vérifier la cohérence garantie

### 7.2 Contrôles de clés
- **Sinistres sans client** : Identifier les ruptures de jointure
- **Sinistres sans contrat** : Mesurer la fiabilité contrat
- **Sinistres sans véhicule** : Mesurer la couverture véhicule
- **Sinistres sans garantie** : Identifier les cas non exploitables
- **Sinistres sans agence** : Mesurer le rattachement réseau
- **Sinistres sans géographie** : Mesurer la couverture GEO

### 7.3 Contrôles de dates
- **Date sinistre manquante** : Bloquant pour l’historique
- **Date déclaration manquante** : Bloquant pour le délai de déclaration
- **Date sinistre avant début contrat** : Chronologie à examiner
- **Date déclaration avant date sinistre** : Incohérence de date
- **Délai sinistre-déclaration extrême** : Valeur atypique
- **Rupture autour de 2019** : Effet migration potentiel

### 7.4 Contrôles de montants
- **Montants manquants** : Limite scoring montant
- **Montants nuls** : Cas à documenter
- **Montants négatifs** : Incohérence potentielle
- **Montants extrêmes** : Vérifier outliers
- **Distribution par garantie** : Préparer ratios
- **Distribution par région** : Préparer comparaison GEO

### 7.5 Contrôles géographiques
- **Valeurs `UNKNOWN`** : Mesurer la qualité GEO
- **Régions non mappées** : Identifier mapping incomplet
- **Gouvernorats non mappés** : Identifier défaut référentiel
- **Agences sans région** : Corriger `dim_agence` ou `dim_geo`
- **Sinistres sans lieu exploitable** : Limite signal GEO
- **Incohérences agence/région** : Vérifier rattachement réseau

### 7.6 Contrôles VHS
- **Sinistres rattachables à VHS** : Mesurer couverture inspection
- **VHS avant sinistre** : Identifier inspections exploitables
- **VHS après sinistre** : À exclure ou interpréter différemment
- **Délai VHS-sinistre** : Mesurer proximité temporelle
- **Distribution VHS des dossiers** : Vérifier impact potentiel
- **Absence VHS** : Ne doit pas bloquer le scoring

---

## 8. Critères de readiness

L’audit doit conclure pour chaque famille de signaux avec un statut.

| Statut | Interprétation |
|---|---|
| **READY** | Les données permettent de calculer le signal correctement |
| **PARTIAL** | Le signal est calculable mais avec limites |
| **NOT_READY** | Le signal ne peut pas être calculé de manière fiable |
| **NOT_AVAILABLE** | Les données nécessaires n’existent pas ou ne sont pas encore intégrées |

### 8.1 Critères READY

Un signal est considéré **READY** si :
- les colonnes nécessaires existent ;
- les clés de jointure sont disponibles ;
- le taux de données manquantes est acceptable ;
- les valeurs `UNKNOWN` sont limitées ou documentées ;
- la logique métier est claire ;
- le résultat peut être expliqué.

### 8.2 Critères PARTIAL

Un signal est **PARTIAL** si :
- une partie des données existe ;
- certaines valeurs sont manquantes ;
- la période historique est limitée ;
- la jointure est exploitable mais pas parfaite ;
- un fallback métier est nécessaire.

### 8.3 Critères NOT_READY

Un signal est **NOT_READY** si :
- les clés sont trop faibles ;
- les dates sont incohérentes ;
- les mappings ne sont pas stables ;
- le volume est insuffisant ;
- les résultats risquent d’être trompeurs.

---

## 9. Matrice de readiness attendue

La synthèse finale de l’audit devra produire une matrice comme suit.

| Famille de signal | Readiness | Commentaire |
|---|---|---|
| **Récurrence client** | À déterminer | Dépend du rattachement client/sinistre |
| **Récurrence véhicule** | À déterminer | Dépend de l’immatriculation et `dim_vehicule` |
| **Récurrence tiers / conducteur** | À déterminer | Dépend de la disponibilité tiers/conducteur |
| **Chronologie** | À déterminer | Dépend des dates contrat/sinistre/déclaration |
| **Montant atypique** | À déterminer | Dépend des montants et garanties |
| **Cohérence géographique** | À déterminer | Dépend de la correction ETL GEO |
| **VHS / état technique** | À déterminer | Dépend du rattachement sinistre-véhicule-inspection |
| **Qualité des données** | À déterminer | Dépend des dimensions `UNKNOWN` et weak joins |

---

## 10. Sorties attendues de l’audit

L’audit doit produire des livrables lisibles et traçables.

### 10.1 Document principal
`docs/scoring/claim_scoring_data_readiness_audit.md`

Ce document décrit :
- les sources inspectées ;
- les colonnes disponibles ;
- les jointures possibles ;
- les limites ;
- les familles de signaux prêtes ou non ;
- les recommandations avant scoring.

### 10.2 Rapports qualité futurs

Les rapports pourront être stockés dans le répertoire :  
`data/quality_reports/scoring/data_readiness/`

Exemples de rapports :
- `claim_scoring_table_inventory.csv`
- `claim_scoring_key_coverage.csv`
- `claim_scoring_date_quality.csv`
- `claim_scoring_amount_quality.csv`
- `claim_scoring_geo_readiness.csv`
- `claim_scoring_vhs_linkage_readiness.csv`
- `claim_scoring_signal_readiness_matrix.csv`

### 10.3 Notebook read-only futur

Un notebook d’audit pourra être créé ensuite :  
`notebooks/validation_scoring/01_claim_scoring_data_readiness.ipynb`

Il devra :
- lire PostgreSQL/DWH en lecture seule ;
- ne pas écrire en base ;
- produire les contrôles qualité ;
- exporter éventuellement des rapports locaux ;
- documenter les limites.

---

## 11. Requêtes SQL d’audit à prévoir

Les requêtes devront rester en lecture seule.

Elles pourront inclure :

```sql
SELECT COUNT(*) FROM mart.fact_sinistre;

SELECT COUNT(*) 
FROM mart.fact_sinistre
WHERE garantie_sk IS NOT NULL;

SELECT COUNT(*) 
FROM mart.fact_sinistre
WHERE client_sk IS NULL;

SELECT COUNT(*) 
FROM mart.fact_sinistre
WHERE vehicle_sk IS NULL;

SELECT COUNT(*) 
FROM mart.fact_sinistre
WHERE claim_date IS NULL;

SELECT attention_level, COUNT(*)
FROM mart.fact_vhs_score
GROUP BY attention_level;
```

Les noms de tables et colonnes devront être adaptés à l’architecture réelle du DWH.

Aucune requête d’écriture n’est autorisée dans cette phase.

**Requêtes interdites :**
`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE TABLE`, `TRUNCATE`, `MERGE`.

---

## 12. Risques identifiés avant scoring

| Risque | Impact | Mitigation |
|---|---|---|
| **Jointure client faible** | Récurrence client incorrecte | Auditer les clés client avant calcul |
| **Véhicule mal relié** | Historique véhicule trompeur | Normaliser immatriculation et contrôler `dim_vehicule` |
| **Tiers indisponible** | Signal tiers impossible | Marquer la famille tiers comme `PARTIAL` ou `NOT_AVAILABLE` |
| **GEO incomplet** | Faux signaux géographiques | Corriger ETL GEO avant utilisation |
| **Montants extrêmes non traités** | Score montant disproportionné | Utiliser percentiles et contrôles outliers |
| **Migration 2019** | Rupture historique | Documenter et créer flag migration |
| **Absence VHS** | Signal technique manquant | VHS doit rester optionnel |
| **Données `UNKNOWN`** | Confiance réduite | Séparer score d’attention et confiance |
| **Confusion qualité/suspicion** | Mauvaise interprétation métier | Qualité des données = confiance, pas suspicion |

---

## 13. Dépendance avec l’ETL GEO

La partie géographique est une dépendance importante du scoring.

Les signaux géographiques ne doivent être utilisés dans le score V1 que si :
- les agences sont correctement reliées à une région ;
- les gouvernorats, délégations ou localités sont standardisés ;
- les lieux de sinistre sont exploitables ;
- les valeurs `UNKNOWN` sont documentées ;
- les incohérences agence/région sont corrigées ou signalées.

Tant que la partie GEO n’est pas stabilisée, les indicateurs géographiques doivent être :
- soit exclus du score ;
- soit utilisés uniquement comme signaux à faible poids ;
- soit utilisés pour réduire le niveau de confiance.

Un problème GEO ne doit jamais être présenté comme une preuve de suspicion.

---

## 14. Dépendance avec VHS

Le module VHS est finalisé et stable.

Il peut être utilisé comme signal technique complémentaire, mais ne doit pas dominer le score dossier.

### 14.1 Utilisation possible

Le scoring peut exploiter :
- le score VHS ;
- le niveau d’attention VHS ;
- le délai entre inspection STAFFIM et sinistre ;
- la présence d’un état technique sensible avant le sinistre.

### 14.2 Conditions de readiness

Avant d’utiliser VHS, il faut vérifier :
- le taux de sinistres rattachables à une inspection ;
- la capacité à identifier l’inspection la plus proche avant le sinistre ;
- la fiabilité du lien véhicule/immatriculation ;
- la cohérence des dates.

### 14.3 Limite

L’absence de VHS ne doit pas empêcher le scoring.  
VHS doit être considéré comme un signal optionnel.

---

## 15. Séparation entre score et confiance

L’audit doit préparer deux sorties différentes.

### 15.1 Score d’attention

Le score d’attention mesure les signaux métier à examiner.

Exemples :
- récurrence client ;
- montant atypique ;
- chronologie inhabituelle ;
- récurrence tiers ;
- état technique véhicule ;
- cohérence géographique.

### 15.2 Niveau de confiance

Le niveau de confiance mesure la fiabilité de l’analyse.

Exemples d’éléments qui réduisent la confiance :
- client manquant ;
- véhicule manquant ;
- géographie `UNKNOWN` ;
- tiers absent ;
- dates incohérentes ;
- effet migration 2019 ;
- jointure faible.

Cette séparation doit être conservée dans l’implémentation future.

---

## 16. Recommandations avant implémentation

Avant de créer le script de scoring, il faut :
1. Valider le périmètre auto.
2. Vérifier la table centrale des sinistres.
3. Vérifier les clés client, contrat, véhicule, garantie, agence et GEO.
4. Finaliser la correction ETL GEO.
5. Auditer les montants.
6. Auditer les dates.
7. Vérifier la disponibilité des tiers/conducteurs.
8. Vérifier le taux de rattachement VHS.
9. Définir les familles de signaux réellement calculables.
10. Documenter les familles non disponibles ou partielles.
11. Créer une feature specification.
12. Construire seulement ensuite le feature mart.

---

## 17. Roadmap immédiate

La suite recommandée est la suivante.

- **Étape 1 — Audit documentaire**  
  Créer et valider le présent document.  
  `docs/scoring/claim_scoring_data_readiness_audit.md`
  
- **Étape 2 — Inventaire read-only des tables**  
  Créer un notebook ou script d’audit read-only pour lister :
  - tables disponibles ;
  - colonnes disponibles ;
  - clés ;
  - volumétrie ;
  - dimensions `UNKNOWN` ;
  - jointures candidates.
  
- **Étape 3 — Matrice de readiness**  
  Produire une matrice :  
  `claim_scoring_signal_readiness_matrix.csv`  
  avec :
  - famille de signal ;
  - indicateurs candidats ;
  - tables sources ;
  - colonnes nécessaires ;
  - disponibilité ;
  - statut readiness ;
  - commentaire.
  
- **Étape 4 — Feature specification**  
  Créer :  
  `docs/scoring/claim_attention_feature_specification.md`  
  Seulement après avoir confirmé ce qui est calculable.
  
- **Étape 5 — Feature mart**  
  Créer le feature mart uniquement après validation de la spécification.
  
- **Étape 6 — Score V1 candidate**  
  Implémenter le score V1 uniquement après validation du feature mart.

---

## 18. Critères de décision après audit

Après l’audit, chaque famille de signal devra être classée.

| Famille | Décision possible |
|---|---|
| **Récurrence client** | Inclure si `client_sk` fiable |
| **Récurrence véhicule** | Inclure si véhicule ou immatriculation fiable |
| **Récurrence tiers** | Inclure si tiers exploitable, sinon reporter |
| **Chronologie** | Inclure si dates fiables |
| **Montant atypique** | Inclure si montants et garanties fiables |
| **Cohérence géographique** | Inclure après correction GEO |
| **VHS** | Inclure comme signal limité si rattachement fiable |
| **Qualité données** | Toujours inclure dans le niveau de confiance |

---

## 19. Conclusion

Cet audit est une étape obligatoire avant la création du score d’attention dossier IRIS.

Il garantit que les futurs signaux de priorisation reposent sur des données disponibles, jointures maîtrisées, dimensions documentées et limites connues.

Le score d’attention dossier ne doit pas être construit uniquement parce que des données existent. Il doit être construit seulement lorsque les données sont suffisamment fiables pour produire une aide à l’analyse compréhensible et défendable.

Un signal n’est utile que s’il est calculable, explicable et interprétable par le métier.

La prochaine étape après ce document est la création d’un audit read-only concret sur le DWH afin de mesurer la disponibilité réelle des données nécessaires au scoring.

---

## Contrôles qualité du document

| Contrôle | Statut attendu |
|---|---|
| Audit avant scoring | OK |
| Lecture seule recommandée | OK |
| Aucun scoring implémenté | OK |
| Pas de Machine Learning | OK |
| Pas de preuve de fraude | OK |
| Périmètre automobile | OK |
| Familles de signaux listées | OK |
| Tables sources à inspecter listées | OK |
| Indicateurs candidats listés | OK |
| Contrôles qualité définis | OK |
| Critères READY / PARTIAL / NOT_READY définis | OK |
| Dépendance GEO documentée | OK |
| Dépendance VHS documentée | OK |
| Séparation score / confiance documentée | OK |
| Roadmap immédiate incluse | OK |

---
Document créé dans le cadre du projet IRIS Auto Fraud Decision Platform — PFE BNA Assurances.

---

## Mise a jour implementation V1

Le notebook canonique `notebooks/validation_scoring/01_claim_scoring_data_readiness.ipynb` existe et a ete consolide. Les controles de readiness tiennent compte des cles techniques `0` comme valeurs manquantes et comparent `date_survenance_sk` avec le seuil entier `20190101`.

Constats retenus pour l'implementation V1 :

- `dwh.fact_sinistre` est la table centrale du score dossier.
- Les familles coeur V1 sont recurrence client, montant atypique, chronologie exploitable et confiance qualite donnees.
- La recurrence vehicule, GEO, VHS et tiers/conducteur restent exclues des points V1 et conservees comme flags de readiness ou limites de confiance.
- Les scripts candidats sont `etl/mart/compute_claim_scoring_features_v1.py` et `etl/mart/compute_claim_attention_score_v1_candidate.py`.

