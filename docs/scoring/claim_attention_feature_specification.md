# Spécification des features du score d'attention dossier IRIS

> **Module :** Score d'attention dossier / priorisation des dossiers sinistres automobiles
> **Projet :** IRIS Auto Fraud Decision Platform — BNA Assurances
> **Statut :** Spécification des features V1 — Document de référence
> **Référence méthodologique :** `docs/scoring/claim_attention_scoring_methodology.md`
> **Référence audit données :** `docs/scoring/claim_scoring_data_readiness_audit.md`
> **Version proposée :** `IRIS_CLAIM_ATTENTION_FEATURES_V1_CANDIDATE`
> **Auteur :** Wiem Benzarti
> **Principe central :** aide à l'analyse, non accusation — aucune feature ne constitue une preuve de fraude

---

## 1. Objectif du document

Ce document traduit la **méthodologie du score d'attention dossier IRIS** en features concrètes et calculables, destinées à alimenter le moteur de scoring déterministe décrit dans le document méthodologique de référence.

### 1.1 Rôle du document

Ce document constitue le **pont entre trois niveaux** :

| Niveau | Document de référence | Rôle |
|---|---|---|
| Méthodologie métier | `claim_attention_scoring_methodology.md` | Définit les familles de signaux, la pondération et les principes |
| Audit de disponibilité des données | `claim_scoring_data_readiness_audit.md` | Évalue la disponibilité réelle des sources DWH |
| Spécification des features | _Ce document_ | Traduit chaque famille de signaux en features calculables avec source, règle et null handling |

Ce document **ne met pas en œuvre le scoring**. Il ne contient aucune implémentation Python, aucun script ETL, aucun modèle Machine Learning et aucune écriture en base de données. Il pose les fondations nécessaires à la future implémentation contrôlée.

### 1.2 Positionnement des features

Chaque feature est un **indicateur mesurable** extrait du DWH. Une feature seule ne constitue jamais un signal de suspicion suffisant. C'est l'**agrégation pondérée** de plusieurs features qui produit un score d'attention, lequel reste une aide à la priorisation et non une preuve de fraude.

> Les éléments définis dans ce document constituent des **signaux à examiner**. Aucun ne constitue un élément à charge, une preuve de fraude, ni une conclusion sur le comportement du client.

### 1.3 Vocabulaire prudent adopté

Ce document utilise systématiquement le vocabulaire suivant :

- **Signal à examiner**
- **Élément à vérifier**
- **Situation nécessitant une attention**
- **Examen prioritaire suggéré**
- **Contexte à analyser**

Sont exclus de ce document : *fraude confirmée*, *preuve de fraude*, *client fraudeur*, *comportement frauduleux*, *suspicion établie*.

---

## 2. Grain fonctionnel

### 2.1 Définition du grain

Le grain du score d'attention dossier est le **dossier sinistre automobile**.

```
1 ligne = 1 dossier sinistre automobile = 1 score d'attention
```

Chaque feature doit être calculée **au niveau du dossier sinistre**. Les features d'historique (récurrence client, récurrence véhicule, récurrence tiers) sont des agrégations calculées depuis d'autres dossiers mais ramenées à la ligne du dossier courant.

### 2.2 Clé technique primaire

| Clé | Type | Rôle |
|---|---|---|
| `claim_sk` | Surrogate key DWH | Clé technique principale si disponible dans le DWH |
| `NUMSNT` | Identifiant naturel | Numéro de sinistre dans le système source |
| `GRNTSINI` | Identifiant naturel | Numéro de garantie sinistre si utilisé dans le DWH |

La clé `claim_sk` est la référence préférée pour les jointures DWH. Si elle est absente ou non fiable, la combinaison `NUMSNT + GRNTSINI` peut servir d'identifiant naturel de secours, sous réserve de déduplication.

### 2.3 Portée du grain

Toutes les features définies dans ce document doivent être calculées **au niveau du dossier sinistre**. Aucune feature ne peut exister à un grain différent (ligne de garantie, événement, inspection) sans être préalablement agrégée au niveau du dossier.

> **Règle de grain** : si une feature nécessite plusieurs lignes par dossier dans la source, elle doit être agrégée (COUNT, MAX, MIN, DATEDIFF, etc.) avant d'être stockée dans `mart.fact_claim_scoring_features`.

---

## 3. Source de vérité

### 3.1 PostgreSQL / DWH comme référence

La base de données PostgreSQL/DWH constitue la **source de vérité unique** du projet IRIS.

Les features doivent être calculées à partir des **tables DWH et mart validées**, et non à partir de fichiers CSV isolés, d'exports ad hoc ou de sources non contrôlées.

### 3.2 Hiérarchie des sources

| Niveau de priorité | Source | Statut recommandé |
|---|---|---|
| 1 — Prioritaire | Tables `mart.*` validées | Source préférentielle |
| 2 — Acceptable | Tables `dwh.*` dimensionnelles | Source secondaire si mart absent |
| 3 — À éviter | Fichiers CSV isolés | À utiliser uniquement pour exploration initiale |
| 4 — Exclu | Données hors DWH non validées | Non utilisables en production |

### 3.3 Mode de lecture

Pendant la phase d'exploration et de validation des features, toutes les requêtes doivent être exécutées en **mode lecture seule** (SELECT uniquement).

Aucune écriture dans la base (INSERT, UPDATE, CREATE TABLE) ne doit être effectuée pendant l'exploration. La création des tables de features ne sera réalisée que plus tard, au travers d'un script ETL contrôlé, validé et documenté.

### 3.4 Dépendances critiques

Les features définies dans ce document dépendent des tables suivantes, dont la disponibilité doit être confirmée par l'audit de préparation des données :

| Table DWH/mart | Rôle attendu | Critique pour |
|---|---|---|
| `mart.fact_claims` ou équivalent | Dossiers sinistres automobiles | Toutes les features |
| `mart.dim_client` | Dimension client | Récurrence client |
| `mart.dim_vehicle` | Dimension véhicule | Récurrence véhicule |
| `mart.dim_contract` | Dimension contrat | Chronologie |
| `mart.dim_guarantee` | Dimension garantie | Montant, chronologie |
| `mart.dim_agency` | Dimension agence | Géographie |
| `mart.dim_geo` | Dimension géographique | Cohérence géographique |
| `mart.fact_vhs_scores` ou équivalent | Scores VHS | Features VHS |
| `mart.fact_third_party` ou équivalent | Tiers impliqués | Récurrence tiers |

---

## 4. Table feature cible proposée

### 4.1 Définition conceptuelle

La table cible suivante est définie de manière **conceptuelle uniquement** dans ce document.

```
mart.fact_claim_scoring_features
```

**Objectif :** stocker, pour chaque dossier sinistre, l'ensemble des indicateurs calculés nécessaires au moteur de scoring d'attention.

> **Cette table ne doit pas être créée à ce stade.** Sa création interviendra uniquement dans le cadre d'une étape ETL ultérieure, après validation de la spécification et des distributions de features.

### 4.2 Colonnes proposées — Clés et identifiants

| Colonne | Type | Rôle |
|---|---|---|
| `claim_sk` | INTEGER | Clé surrogate du dossier sinistre |
| `claim_business_id` | VARCHAR | Identifiant naturel du dossier (ex. NUMSNT) |
| `client_sk` | INTEGER | Clé surrogate du client |
| `contract_sk` | INTEGER | Clé surrogate du contrat |
| `vehicle_sk` | INTEGER | Clé surrogate du véhicule |
| `agency_sk` | INTEGER | Clé surrogate de l'agence |
| `claim_geo_sk` | INTEGER | Clé surrogate géographique du sinistre |
| `claim_date` | DATE | Date du sinistre |
| `declaration_date` | DATE | Date de déclaration du sinistre |
| `claim_amount` | NUMERIC | Montant du sinistre |
| `scoring_feature_version` | VARCHAR | Version du calcul de features (ex. `V1`) |
| `created_at` | TIMESTAMP | Horodatage de création de la ligne |

### 4.3 Colonnes proposées — Features calculées

Les features calculées seront définies dans les sections suivantes. Elles seront toutes stockées dans cette même table, une colonne par feature, au grain du dossier sinistre.

### 4.4 Tables cibles complémentaires (ultérieures)

Les tables suivantes sont mentionnées pour information. Elles seront spécifiées et créées dans des étapes ultérieures du projet.

| Table | Rôle | Étape |
|---|---|---|
| `mart.fact_claim_attention_score` | Score final par dossier et par version | Étape 6 |
| `mart.fact_claim_attention_signal_detail` | Détail des signaux expliquant le score | Étape 6 |

---

## 5. Principes de conception des features

Les features du score d'attention dossier IRIS doivent respecter les principes suivants.

### 5.1 Explicabilité

Chaque feature doit pouvoir être **expliquée en langage métier** à un gestionnaire non technique. Une feature dont le sens ne peut pas être exprimé simplement doit être reconsidérée.

### 5.2 Libellé métier obligatoire

Chaque feature dispose d'un **libellé métier** distinct de son nom technique. Ce libellé est utilisé dans les explications affichées aux utilisateurs de Power BI et de l'application IRIS.

### 5.3 Traçabilité des sources

Chaque feature doit **identifier explicitement** :
- les tables DWH source utilisées ;
- les clés de jointure nécessaires ;
- la règle de calcul précise.

### 5.4 Gestion des valeurs nulles

Chaque feature doit définir une **règle de null handling** explicite. L'absence de donnée ne doit jamais produire un signal d'attention implicite. Elle doit affecter le niveau de confiance.

### 5.5 Séparation attention / confiance

Chaque feature doit préciser si elle influence :
- le **score d'attention** (intensité des signaux métier), ou
- le **niveau de confiance** (fiabilité de l'analyse au regard de la qualité des données).

Un problème de qualité des données ne peut pas augmenter directement le score d'attention comme s'il s'agissait d'un signal métier.

### 5.6 Auditabilité et reproductibilité

Les features doivent être **calculables de manière reproductible** à partir des mêmes données DWH. Les règles de calcul doivent être suffisamment précises pour permettre leur implémentation sans ambiguïté.

### 5.7 Prudence d'interprétation

Aucune feature ne doit être interprétée isolément comme une conclusion. La valeur d'une feature est un **élément parmi d'autres** dans la construction du score global.

---

## 6. Format standard du catalogue de features

Chaque feature est documentée selon le format tableau suivant.

| Champ | Signification |
|---|---|
| `feature_name` | Nom technique de la feature (snake_case) |
| `business_label` | Libellé métier lisible par un gestionnaire |
| `family` | Famille de signal d'appartenance |
| `business_question` | Question métier à laquelle la feature répond |
| `source_tables` | Tables DWH/mart sources |
| `join_keys` | Clés de jointure nécessaires |
| `calculation_rule` | Règle de calcul précise |
| `output_type` | Type de sortie : `integer` / `numeric` / `boolean` / `category` |
| `null_handling` | Comportement en cas de valeur manquante |
| `attention_impact` | Impact sur le score d'attention |
| `confidence_impact` | Impact sur le niveau de confiance |
| `validation_check` | Vérification à effectuer avant implémentation |

---

## 7. Features de récurrence client

### 7.1 Contexte

Les features de récurrence client mesurent **la fréquence des sinistres déclarés par un même client** sur différentes fenêtres temporelles. Un client présentant plusieurs sinistres récents constitue un **élément à examiner**, sans que cela constitue en soi une preuve ou une conclusion.

> Ces features nécessitent une liaison fiable entre le dossier sinistre et la dimension client via `client_sk`. En cas de liaison défaillante, la confidence doit être abaissée plutôt qu'un signal généré.

---

### Feature : `client_claim_count_total`

| Champ | Valeur |
|---|---|
| **feature_name** | `client_claim_count_total` |
| **business_label** | Récurrence globale des sinistres client |
| **family** | Récurrence client |
| **business_question** | Le client a-t-il déclaré de nombreux sinistres au total dans l'historique disponible ? |
| **source_tables** | `mart.fact_claims`, `mart.dim_client` |
| **join_keys** | `client_sk` |
| **calculation_rule** | `COUNT(DISTINCT claim_sk)` pour tous les sinistres associés au même `client_sk` dans l'historique complet disponible, hors le dossier courant |
| **output_type** | `integer` |
| **null_handling** | Si `client_sk` est NULL ou absent : feature = NULL, confidence abaissée |
| **attention_impact** | Augmente proportionnellement avec le nombre de sinistres (seuils à calibrer) |
| **confidence_impact** | Aucun si `client_sk` est disponible ; faible si `client_sk` est manquant |
| **validation_check** | Vérifier la distribution des valeurs ; identifier les valeurs extrêmes ; vérifier l'absence de doublons dossier |

---

### Feature : `client_claim_count_12m`

| Champ | Valeur |
|---|---|
| **feature_name** | `client_claim_count_12m` |
| **business_label** | Récurrence récente des sinistres client sur 12 mois |
| **family** | Récurrence client |
| **business_question** | Le client a-t-il déclaré plusieurs sinistres au cours des 12 derniers mois précédant le sinistre courant ? |
| **source_tables** | `mart.fact_claims`, `mart.dim_client` |
| **join_keys** | `client_sk`, `claim_date` |
| **calculation_rule** | `COUNT(DISTINCT claim_sk)` pour les sinistres du même `client_sk` dont `claim_date` est dans l'intervalle `[claim_date_courant - 365 jours, claim_date_courant - 1 jour]` |
| **output_type** | `integer` |
| **null_handling** | Si `client_sk` NULL : feature = NULL, confidence abaissée. Si `claim_date` NULL : feature = NULL, message qualité |
| **attention_impact** | Signal à examiner si valeur >= 2 ; attention accrue si valeur >= 3 |
| **confidence_impact** | Aucun si données complètes ; faible si dates manquantes |
| **validation_check** | Vérifier que la fenêtre glissante est correctement calculée par rapport à `claim_date` et non par rapport à la date courante |

---

### Feature : `client_claim_count_24m`

| Champ | Valeur |
|---|---|
| **feature_name** | `client_claim_count_24m` |
| **business_label** | Récurrence étendue des sinistres client sur 24 mois |
| **family** | Récurrence client |
| **business_question** | Le client a-t-il déclaré plusieurs sinistres au cours des 24 derniers mois précédant le sinistre courant ? |
| **source_tables** | `mart.fact_claims`, `mart.dim_client` |
| **join_keys** | `client_sk`, `claim_date` |
| **calculation_rule** | `COUNT(DISTINCT claim_sk)` pour les sinistres du même `client_sk` dont `claim_date` est dans l'intervalle `[claim_date_courant - 730 jours, claim_date_courant - 1 jour]` |
| **output_type** | `integer` |
| **null_handling** | Idem `client_claim_count_12m` |
| **attention_impact** | Signal complémentaire à `client_claim_count_12m` ; contexte plus long |
| **confidence_impact** | Aucun si données complètes ; sensible à l'effet migration 2019 |
| **validation_check** | Vérifier la proportion de dossiers couverts par l'historique 24 mois ; surveiller l'effet migration 2019 |

---

### Feature : `days_since_previous_claim`

| Champ | Valeur |
|---|---|
| **feature_name** | `days_since_previous_claim` |
| **business_label** | Délai depuis le précédent sinistre client |
| **family** | Récurrence client |
| **business_question** | Quel est le délai entre le sinistre courant et le sinistre précédent du même client ? |
| **source_tables** | `mart.fact_claims`, `mart.dim_client` |
| **join_keys** | `client_sk`, `claim_date` |
| **calculation_rule** | `claim_date_courant - MAX(claim_date)` pour les sinistres antérieurs du même `client_sk`. Résultat en nombre de jours. |
| **output_type** | `integer` (jours, NULL si premier sinistre) |
| **null_handling** | Si aucun sinistre antérieur : feature = NULL (premier sinistre du client, pas un signal). Si `client_sk` NULL : feature = NULL, confidence abaissée |
| **attention_impact** | Un délai très court (à calibrer selon distribution) peut constituer un contexte à examiner |
| **confidence_impact** | Aucun si données complètes |
| **validation_check** | Vérifier l'absence de valeurs négatives (erreur de dates) ; vérifier la proportion de clients en premier sinistre |

---

### Feature : `client_claim_frequency_band`

| Champ | Valeur |
|---|---|
| **feature_name** | `client_claim_frequency_band` |
| **business_label** | Bande de fréquence sinistres client |
| **family** | Récurrence client |
| **business_question** | Dans quelle catégorie de fréquence de sinistres se situe ce client ? |
| **source_tables** | Calculée à partir de `client_claim_count_12m` |
| **join_keys** | `client_sk` |
| **calculation_rule** | Catégorie dérivée de `client_claim_count_12m` : `FAIBLE` (0-1), `MODEREE` (2-3), `ELEVEE` (>= 4). Seuils à calibrer selon distribution réelle |
| **output_type** | `category` (`FAIBLE` / `MODEREE` / `ELEVEE` / `INCONNU`) |
| **null_handling** | Si `client_claim_count_12m` NULL : band = `INCONNU` |
| **attention_impact** | `ELEVEE` = signal à examiner dans le contexte global |
| **confidence_impact** | `INCONNU` = confidence dégradée |
| **validation_check** | Vérifier la répartition des bandes sur la population totale ; les seuils doivent être ajustés à la distribution réelle |

---

## 8. Features de récurrence véhicule et VHS

### 8.1 Contexte

Les features de récurrence véhicule mesurent **la fréquence des sinistres impliquant un même véhicule**. Le module VHS fournit un contexte technique supplémentaire sur l'état du véhicule, issu des inspections STAFFIM.

> **Positionnement VHS dans le scoring :** Le VHS est un signal technique contextuel. Il n'est pas un score de fraude. Il ne doit pas dominer le score d'attention dossier. Son poids dans la V1 est volontairement limité à 5 points maximum sur 100.

---

### Feature : `vehicle_claim_count_total`

| Champ | Valeur |
|---|---|
| **feature_name** | `vehicle_claim_count_total` |
| **business_label** | Historique total des sinistres du véhicule |
| **family** | Récurrence véhicule |
| **business_question** | Le même véhicule a-t-il été impliqué dans de nombreux sinistres au total ? |
| **source_tables** | `mart.fact_claims`, `mart.dim_vehicle` |
| **join_keys** | `vehicle_sk` |
| **calculation_rule** | `COUNT(DISTINCT claim_sk)` pour tous les sinistres associés au même `vehicle_sk`, hors le dossier courant |
| **output_type** | `integer` |
| **null_handling** | Si `vehicle_sk` NULL : feature = NULL, confidence abaissée |
| **attention_impact** | Augmente avec le nombre de sinistres (seuils à calibrer) |
| **confidence_impact** | Aucun si `vehicle_sk` disponible |
| **validation_check** | Vérifier la liaison véhicule/dossier ; identifier les véhicules sans `vehicle_sk` |

---

### Feature : `vehicle_claim_count_12m`

| Champ | Valeur |
|---|---|
| **feature_name** | `vehicle_claim_count_12m` |
| **business_label** | Récurrence récente des sinistres véhicule sur 12 mois |
| **family** | Récurrence véhicule |
| **business_question** | Le même véhicule a-t-il été impliqué dans plusieurs sinistres au cours des 12 derniers mois ? |
| **source_tables** | `mart.fact_claims`, `mart.dim_vehicle` |
| **join_keys** | `vehicle_sk`, `claim_date` |
| **calculation_rule** | `COUNT(DISTINCT claim_sk)` pour les sinistres du même `vehicle_sk` dont `claim_date` est dans l'intervalle `[claim_date_courant - 365 jours, claim_date_courant - 1 jour]` |
| **output_type** | `integer` |
| **null_handling** | Idem `vehicle_claim_count_total` |
| **attention_impact** | Signal à examiner si valeur >= 2 dans les 12 mois |
| **confidence_impact** | Aucun si données complètes |
| **validation_check** | Vérifier l'alignement des dates ; surveiller les véhicules multi-dossiers |

---

### Feature : `days_since_previous_vehicle_claim`

| Champ | Valeur |
|---|---|
| **feature_name** | `days_since_previous_vehicle_claim` |
| **business_label** | Délai depuis le précédent sinistre du véhicule |
| **family** | Récurrence véhicule |
| **business_question** | Quel est le délai entre le sinistre courant et le sinistre précédent impliquant le même véhicule ? |
| **source_tables** | `mart.fact_claims`, `mart.dim_vehicle` |
| **join_keys** | `vehicle_sk`, `claim_date` |
| **calculation_rule** | `claim_date_courant - MAX(claim_date)` pour les sinistres antérieurs du même `vehicle_sk`. Résultat en jours. |
| **output_type** | `integer` (jours, NULL si premier sinistre véhicule) |
| **null_handling** | Si aucun sinistre antérieur : NULL (pas un signal). Si `vehicle_sk` NULL : NULL, confidence abaissée |
| **attention_impact** | Un délai très court constitue un contexte à examiner |
| **confidence_impact** | Aucun si données complètes |
| **validation_check** | Vérifier l'absence de valeurs négatives |

---

### Feature : `linked_vhs_score`

| Champ | Valeur |
|---|---|
| **feature_name** | `linked_vhs_score` |
| **business_label** | Score technique VHS du véhicule associé |
| **family** | Récurrence véhicule / VHS |
| **business_question** | Quel est le score d'état technique VHS du véhicule impliqué dans ce dossier ? |
| **source_tables** | `mart.fact_vhs_scores` (ou table équivalente), `mart.dim_vehicle` |
| **join_keys** | `vehicle_sk`, date inspection VHS la plus proche antérieure à `claim_date` |
| **calculation_rule** | Récupérer le score VHS le plus récent avant la date du sinistre pour le même `vehicle_sk` |
| **output_type** | `numeric` (0-100, NULL si non disponible) |
| **null_handling** | Si aucune inspection VHS disponible : feature = NULL. Abaisse `vhs_linkage_flag` = 0 |
| **attention_impact** | Score VHS faible = état technique à prendre en compte dans le contexte global (poids limité) |
| **confidence_impact** | Aucun impact direct sur la confiance ; `vhs_linkage_flag` = 0 réduit la complétude |
| **validation_check** | Vérifier le taux de liaison VHS/véhicule ; vérifier la chronologie inspection/sinistre |

---

### Feature : `linked_vhs_grade`

| Champ | Valeur |
|---|---|
| **feature_name** | `linked_vhs_grade` |
| **business_label** | Grade technique VHS du véhicule associé |
| **family** | Récurrence véhicule / VHS |
| **business_question** | Quelle est la catégorie d'état technique VHS du véhicule ? |
| **source_tables** | `mart.fact_vhs_scores` |
| **join_keys** | `vehicle_sk` |
| **calculation_rule** | Grade catégoriel associé au `linked_vhs_score` (ex. A/B/C/D/E selon barème VHS) |
| **output_type** | `category` |
| **null_handling** | Si `linked_vhs_score` NULL : grade = NULL |
| **attention_impact** | Grade faible = contexte technique à considérer |
| **confidence_impact** | Aucun |
| **validation_check** | Vérifier la cohérence grade/score VHS |

---

### Feature : `linked_vhs_attention_level`

| Champ | Valeur |
|---|---|
| **feature_name** | `linked_vhs_attention_level` |
| **business_label** | Niveau d'attention VHS du véhicule — état technique à considérer |
| **family** | Récurrence véhicule / VHS |
| **business_question** | Le véhicule a-t-il un niveau d'attention technique élevé selon le module VHS ? |
| **source_tables** | `mart.fact_vhs_scores` |
| **join_keys** | `vehicle_sk` |
| **calculation_rule** | Niveau d'attention VHS issu directement du module VHS finalisé (`FAIBLE` / `MODERE` / `ELEVE`) |
| **output_type** | `category` |
| **null_handling** | Si VHS non disponible : NULL |
| **attention_impact** | `ELEVE` = signal technique à considérer dans le contexte (poids plafonné à 5 points dans la V1) |
| **confidence_impact** | Aucun |
| **validation_check** | Vérifier que le niveau VHS est cohérent avec le score VHS |

---

### Feature : `days_between_vhs_and_claim`

| Champ | Valeur |
|---|---|
| **feature_name** | `days_between_vhs_and_claim` |
| **business_label** | Délai entre l'inspection technique et le sinistre |
| **family** | Récurrence véhicule / VHS |
| **business_question** | Quel est l'écart entre la dernière inspection VHS et la date du sinistre ? |
| **source_tables** | `mart.fact_vhs_scores`, `mart.fact_claims` |
| **join_keys** | `vehicle_sk`, `claim_date`, date d'inspection VHS |
| **calculation_rule** | `claim_date - vhs_inspection_date` en jours. Valeur positive = inspection avant sinistre. |
| **output_type** | `integer` (jours, NULL si VHS absent) |
| **null_handling** | Si aucune inspection VHS : NULL |
| **attention_impact** | Un délai très court entre inspection et sinistre constitue un contexte à examiner |
| **confidence_impact** | Aucun |
| **validation_check** | Vérifier l'absence de valeurs négatives (inspection après sinistre) |

---

### Feature : `vhs_linkage_flag`

| Champ | Valeur |
|---|---|
| **feature_name** | `vhs_linkage_flag` |
| **business_label** | Indicateur de liaison dossier/VHS disponible |
| **family** | Récurrence véhicule / VHS |
| **business_question** | Existe-t-il une inspection VHS liée au véhicule de ce dossier ? |
| **source_tables** | `mart.fact_vhs_scores`, `mart.dim_vehicle` |
| **join_keys** | `vehicle_sk` |
| **calculation_rule** | `1` si au moins une inspection VHS existe pour le `vehicle_sk` avant `claim_date`, sinon `0` |
| **output_type** | `boolean` (0 / 1) |
| **null_handling** | `0` si aucune liaison possible |
| **attention_impact** | Aucun impact direct ; indicateur de complétude du contexte VHS |
| **confidence_impact** | `0` = contexte VHS indisponible, signal VHS non utilisable |
| **validation_check** | Vérifier le taux global de liaison VHS sur la population de dossiers |

---

## 9. Features de récurrence tiers et conducteur

### 9.1 Contexte

Ces features mesurent **la répétition de tiers ou de conducteurs** dans différents dossiers sinistres. Elles nécessitent que les données tiers soient disponibles et fiables dans le DWH.

> **Règle de prudence :** Si les données tiers ou conducteur sont incomplètes, l'absence de liaison doit affecter le **niveau de confiance** et non générer automatiquement un signal d'attention. Une information manquante n'est pas un signal de suspicion.

---

### Feature : `third_party_claim_count_total`

| Champ | Valeur |
|---|---|
| **feature_name** | `third_party_claim_count_total` |
| **business_label** | Récurrence globale du tiers dans les dossiers sinistres |
| **family** | Récurrence tiers / conducteur |
| **business_question** | Le même tiers est-il impliqué dans plusieurs dossiers sinistres au total ? |
| **source_tables** | `mart.fact_claims`, `mart.fact_third_party` (ou équivalent) |
| **join_keys** | Identifiant tiers (ex. NUMT, identifiant naturel) |
| **calculation_rule** | `COUNT(DISTINCT claim_sk)` pour tous les dossiers impliquant le même tiers, hors dossier courant |
| **output_type** | `integer` (NULL si tiers non identifiable) |
| **null_handling** | Si identifiant tiers absent : feature = NULL, confidence modérément abaissée |
| **attention_impact** | Augmente proportionnellement avec le nombre d'occurrences du tiers |
| **confidence_impact** | Données tiers incomplètes → confidence abaissée |
| **validation_check** | Vérifier la disponibilité et la qualité des identifiants tiers dans le DWH |

---

### Feature : `third_party_claim_count_24m`

| Champ | Valeur |
|---|---|
| **feature_name** | `third_party_claim_count_24m` |
| **business_label** | Récurrence récente du tiers sur 24 mois |
| **family** | Récurrence tiers / conducteur |
| **business_question** | Le même tiers est-il apparu dans plusieurs dossiers au cours des 24 derniers mois ? |
| **source_tables** | `mart.fact_claims`, `mart.fact_third_party` |
| **join_keys** | Identifiant tiers, `claim_date` |
| **calculation_rule** | `COUNT(DISTINCT claim_sk)` pour les dossiers du même tiers dans l'intervalle `[claim_date_courant - 730 jours, claim_date_courant - 1 jour]` |
| **output_type** | `integer` (NULL si tiers non identifiable) |
| **null_handling** | Si identifiant tiers absent : NULL |
| **attention_impact** | Signal à examiner si valeur >= 2 |
| **confidence_impact** | Données tiers incomplètes → confidence abaissée |
| **validation_check** | Vérifier la complétude des identifiants tiers et des dates |

---

### Feature : `client_third_party_pair_count`

| Champ | Valeur |
|---|---|
| **feature_name** | `client_third_party_pair_count` |
| **business_label** | Répétition du couple client/tiers dans les dossiers |
| **family** | Récurrence tiers / conducteur |
| **business_question** | Le même couple client/tiers apparaît-il dans plusieurs dossiers distincts ? |
| **source_tables** | `mart.fact_claims`, `mart.fact_third_party`, `mart.dim_client` |
| **join_keys** | `client_sk`, identifiant tiers |
| **calculation_rule** | `COUNT(DISTINCT claim_sk)` pour les dossiers impliquant le même `client_sk` ET le même identifiant tiers, hors dossier courant |
| **output_type** | `integer` (NULL si données tiers absentes) |
| **null_handling** | Si `client_sk` ou identifiant tiers NULL : feature = NULL |
| **attention_impact** | Répétition du même couple = contexte à examiner (seuils à calibrer) |
| **confidence_impact** | Données tiers incomplètes → confidence dégradée |
| **validation_check** | Vérifier la disponibilité des deux identifiants ; vérifier la déduplication |

---

### Feature : `same_driver_claim_count_total`

| Champ | Valeur |
|---|---|
| **feature_name** | `same_driver_claim_count_total` |
| **business_label** | Récurrence globale du conducteur dans les dossiers sinistres |
| **family** | Récurrence tiers / conducteur |
| **business_question** | Le même conducteur est-il impliqué dans plusieurs dossiers sinistres au total ? |
| **source_tables** | `mart.fact_claims`, dimension conducteur (si disponible) |
| **join_keys** | Identifiant conducteur |
| **calculation_rule** | `COUNT(DISTINCT claim_sk)` pour tous les dossiers impliquant le même conducteur, hors dossier courant |
| **output_type** | `integer` (NULL si conducteur non identifiable) |
| **null_handling** | Si identifiant conducteur absent : NULL, confidence abaissée |
| **attention_impact** | Signal à examiner si le conducteur apparaît dans plusieurs dossiers |
| **confidence_impact** | Données conducteur incomplètes → confidence dégradée |
| **validation_check** | Vérifier la disponibilité des identifiants conducteurs dans le DWH |

---

### Feature : `driver_client_mismatch_flag`

| Champ | Valeur |
|---|---|
| **feature_name** | `driver_client_mismatch_flag` |
| **business_label** | Discordance conducteur / titulaire du contrat |
| **family** | Récurrence tiers / conducteur |
| **business_question** | Le conducteur déclaré dans le sinistre est-il différent du titulaire du contrat ? |
| **source_tables** | `mart.fact_claims`, `mart.dim_contract`, dimension conducteur |
| **join_keys** | `contract_sk`, identifiant conducteur |
| **calculation_rule** | `1` si l'identifiant du conducteur déclaré est différent du titulaire du contrat, `0` si identique, `NULL` si données insuffisantes |
| **output_type** | `boolean` (0 / 1 / NULL) |
| **null_handling** | Si données conducteur ou contrat absentes : NULL |
| **attention_impact** | `1` = contexte à examiner selon règles métier BNA |
| **confidence_impact** | NULL = données insuffisantes pour évaluer ce signal |
| **validation_check** | À implémenter uniquement si les identifiants conducteurs sont fiables dans le DWH |

---

## 10. Features de chronologie

### 10.1 Contexte

Les features de chronologie analysent **les délais et enchaînements temporels** entre les événements liés au dossier sinistre (début de contrat, changement de garantie, date du sinistre, date de déclaration).

> **Règle de prudence :** Les features chronologiques doivent être interprétées avec soin et validées contre les règles métier BNA. Un délai court peut avoir des explications légitimes. Ces features constituent des **contextes à analyser**, pas des conclusions automatiques.

---

### Feature : `days_contract_start_to_claim`

| Champ | Valeur |
|---|---|
| **feature_name** | `days_contract_start_to_claim` |
| **business_label** | Chronologie contrat/sinistre à examiner |
| **family** | Chronologie |
| **business_question** | Quel est le délai entre le début du contrat et la date du sinistre ? |
| **source_tables** | `mart.fact_claims`, `mart.dim_contract` |
| **join_keys** | `contract_sk`, `claim_date`, date de début contrat |
| **calculation_rule** | `claim_date - contract_start_date` en jours. Valeur positive = sinistre après début contrat. |
| **output_type** | `integer` (jours) |
| **null_handling** | Si `contract_sk` NULL ou `contract_start_date` NULL : feature = NULL, confidence abaissée |
| **attention_impact** | Délai très court (à calibrer) = contexte à examiner ; valeur négative = anomalie à vérifier |
| **confidence_impact** | Aucun si données complètes |
| **validation_check** | Vérifier l'absence de valeurs négatives ; vérifier la distribution des délais |

---

### Feature : `days_claim_to_declaration`

| Champ | Valeur |
|---|---|
| **feature_name** | `days_claim_to_declaration` |
| **business_label** | Délai de déclaration inhabituel |
| **family** | Chronologie |
| **business_question** | Quel est le délai entre la date du sinistre et sa date de déclaration ? |
| **source_tables** | `mart.fact_claims` |
| **join_keys** | `claim_sk`, `claim_date`, `declaration_date` |
| **calculation_rule** | `declaration_date - claim_date` en jours |
| **output_type** | `integer` (jours) |
| **null_handling** | Si `declaration_date` NULL : feature = NULL, confidence abaissée. Valeur négative = erreur qualité à signaler. |
| **attention_impact** | Délai atypique (très court ou très long par rapport à la distribution) = contexte à examiner |
| **confidence_impact** | Valeur négative = qualité données dégradée |
| **validation_check** | Vérifier distribution ; identifier les valeurs négatives ; comparer avec les délais réglementaires BNA |

---

### Feature : `recent_contract_change_flag`

| Champ | Valeur |
|---|---|
| **feature_name** | `recent_contract_change_flag` |
| **business_label** | Changement récent de contrat à noter |
| **family** | Chronologie |
| **business_question** | Le contrat a-t-il subi une modification récente avant le sinistre ? |
| **source_tables** | `mart.dim_contract`, historique des modifications contrat |
| **join_keys** | `contract_sk`, `claim_date`, dates de modification contrat |
| **calculation_rule** | `1` si une modification du contrat a eu lieu dans les N jours précédant `claim_date` (N à calibrer, ex. 30-90 jours) |
| **output_type** | `boolean` (0 / 1 / NULL) |
| **null_handling** | Si historique modifications non disponible : NULL, confidence légèrement abaissée |
| **attention_impact** | `1` = changement récent = contexte à examiner |
| **confidence_impact** | NULL = données insuffisantes |
| **validation_check** | Vérifier la disponibilité de l'historique des modifications contrat dans le DWH |

---

### Feature : `recent_guarantee_change_flag`

| Champ | Valeur |
|---|---|
| **feature_name** | `recent_guarantee_change_flag` |
| **business_label** | Changement récent de garantie à vérifier |
| **family** | Chronologie |
| **business_question** | La garantie associée au sinistre a-t-elle été modifiée ou ajoutée récemment ? |
| **source_tables** | `mart.dim_guarantee`, historique garanties |
| **join_keys** | `contract_sk`, `claim_date`, dates de modification garantie |
| **calculation_rule** | `1` si une modification de garantie a eu lieu dans les N jours précédant `claim_date` (N à calibrer) |
| **output_type** | `boolean` (0 / 1 / NULL) |
| **null_handling** | Si historique garanties non disponible : NULL |
| **attention_impact** | `1` = garantie récemment modifiée = contexte à examiner |
| **confidence_impact** | NULL = données insuffisantes |
| **validation_check** | Vérifier la disponibilité de l'historique des garanties |

---

### Feature : `claim_before_contract_start_flag`

| Champ | Valeur |
|---|---|
| **feature_name** | `claim_before_contract_start_flag` |
| **business_label** | Anomalie chronologique : sinistre antérieur au contrat |
| **family** | Chronologie |
| **business_question** | La date du sinistre est-elle antérieure à la date de début du contrat ? |
| **source_tables** | `mart.fact_claims`, `mart.dim_contract` |
| **join_keys** | `contract_sk`, `claim_date`, `contract_start_date` |
| **calculation_rule** | `1` si `claim_date < contract_start_date`, sinon `0` |
| **output_type** | `boolean` (0 / 1 / NULL) |
| **null_handling** | Si dates manquantes : NULL ; valeur `1` est une anomalie à vérifier manuellement |
| **attention_impact** | `1` = anomalie chronologique à vérifier (peut être erreur de données ou cas métier spécifique) |
| **confidence_impact** | `1` = données à auditer ; confidence abaissée |
| **validation_check** | Identifier la proportion de dossiers concernés ; distinguer erreurs de données et cas légitimes |

---

### Feature : `claim_after_recent_update_flag`

| Champ | Valeur |
|---|---|
| **feature_name** | `claim_after_recent_update_flag` |
| **business_label** | Sinistre survenu après une modification récente du dossier |
| **family** | Chronologie |
| **business_question** | Le sinistre est-il survenu dans une fenêtre proche d'une mise à jour contractuelle récente ? |
| **source_tables** | `mart.fact_claims`, `mart.dim_contract`, historique modifications |
| **join_keys** | `contract_sk`, `claim_date` |
| **calculation_rule** | Combinaison de `recent_contract_change_flag` et `recent_guarantee_change_flag` ; `1` si l'un ou l'autre est actif |
| **output_type** | `boolean` (0 / 1 / NULL) |
| **null_handling** | Si données de modification absentes : NULL |
| **attention_impact** | `1` = contexte à analyser dans son ensemble |
| **confidence_impact** | NULL = données insuffisantes |
| **validation_check** | Dépend de la disponibilité des historiques de modification |

---

## 11. Features d'atypicité du montant

### 11.1 Contexte

Ces features comparent le montant du sinistre courant à des **dossiers comparables**. La comparaison doit être effectuée contre des dossiers de même nature : même garantie, même type de sinistre si disponible, même période si pertinente, même région si GEO est stable.

> **Règle de prudence :** Un montant élevé n'est pas en soi une preuve de problème. Il constitue un **élément à vérifier** dans le contexte global du dossier. La comparaison doit être effectuée uniquement contre des dossiers réellement comparables.

---

### Feature : `claim_amount`

| Champ | Valeur |
|---|---|
| **feature_name** | `claim_amount` |
| **business_label** | Montant déclaré du sinistre |
| **family** | Montant |
| **business_question** | Quel est le montant déclaré pour ce dossier sinistre ? |
| **source_tables** | `mart.fact_claims` |
| **join_keys** | `claim_sk` |
| **calculation_rule** | Montant brut du sinistre tel que présent dans le DWH (colonne à identifier lors de l'audit) |
| **output_type** | `numeric` |
| **null_handling** | Si montant NULL : toutes les features de comparaison de montant = NULL |
| **attention_impact** | Aucun en valeur absolue ; sert de base aux features comparatives |
| **confidence_impact** | Montant NULL = features montant désactivées |
| **validation_check** | Vérifier la proportion de dossiers avec montant ; identifier les valeurs nulles ou négatives |

---

### Feature : `amount_vs_guarantee_median_ratio`

| Champ | Valeur |
|---|---|
| **feature_name** | `amount_vs_guarantee_median_ratio` |
| **business_label** | Montant supérieur aux dossiers comparables par garantie |
| **family** | Montant |
| **business_question** | Le montant de ce dossier est-il significativement supérieur à la médiane des dossiers de même garantie ? |
| **source_tables** | `mart.fact_claims`, `mart.dim_guarantee` |
| **join_keys** | `claim_sk`, identifiant garantie |
| **calculation_rule** | `claim_amount / MEDIAN(claim_amount)` calculé sur la population des dossiers de même garantie (même période si nécessaire). Ratio > 1 = supérieur à la médiane. |
| **output_type** | `numeric` |
| **null_handling** | Si `claim_amount` NULL ou garantie non identifiable : NULL |
| **attention_impact** | Ratio élevé (seuil à calibrer, ex. > 2.0) = montant à examiner |
| **confidence_impact** | Aucun si données complètes |
| **validation_check** | Vérifier que la population de référence est suffisamment large ; vérifier la stabilité de la médiane |

---

### Feature : `amount_percentile_by_guarantee`

| Champ | Valeur |
|---|---|
| **feature_name** | `amount_percentile_by_guarantee` |
| **business_label** | Percentile du montant parmi les dossiers de même garantie |
| **family** | Montant |
| **business_question** | Dans quel percentile de montant se situe ce dossier parmi les dossiers de même garantie ? |
| **source_tables** | `mart.fact_claims`, `mart.dim_guarantee` |
| **join_keys** | `claim_sk`, identifiant garantie |
| **calculation_rule** | `PERCENT_RANK()` ou `NTILE(100)` de `claim_amount` dans la partition de dossiers de même garantie |
| **output_type** | `numeric` (0-100) |
| **null_handling** | Si `claim_amount` NULL ou garantie absente : NULL |
| **attention_impact** | Percentile >= 90 = montant dans le décile supérieur = contexte à examiner |
| **confidence_impact** | Aucun |
| **validation_check** | Vérifier la distribution des percentiles ; s'assurer que les groupes de garanties sont suffisamment peuplés |

---

### Feature : `amount_vs_region_median_ratio`

| Champ | Valeur |
|---|---|
| **feature_name** | `amount_vs_region_median_ratio` |
| **business_label** | Montant comparé à la médiane régionale |
| **family** | Montant |
| **business_question** | Le montant est-il significativement supérieur à la médiane des dossiers de la même région ? |
| **source_tables** | `mart.fact_claims`, `mart.dim_geo` |
| **join_keys** | `claim_sk`, `claim_geo_sk` |
| **calculation_rule** | `claim_amount / MEDIAN(claim_amount)` calculé sur la population des dossiers de même région GEO. Dépend de la stabilité de l'ETL GEO. |
| **output_type** | `numeric` (NULL si GEO indisponible) |
| **null_handling** | Si GEO NULL ou UNKNOWN : NULL, confidence abaissée |
| **attention_impact** | Ratio élevé = comparaison régionale à vérifier (seuils à calibrer) |
| **confidence_impact** | GEO instable ou UNKNOWN = feature non calculable |
| **validation_check** | À activer uniquement après stabilisation de l'ETL GEO |

---

### Feature : `amount_vs_claim_type_median_ratio`

| Champ | Valeur |
|---|---|
| **feature_name** | `amount_vs_claim_type_median_ratio` |
| **business_label** | Montant comparé à la médiane par type de sinistre |
| **family** | Montant |
| **business_question** | Le montant est-il significativement supérieur à la médiane des dossiers de même type ? |
| **source_tables** | `mart.fact_claims`, dimension type sinistre (si disponible) |
| **join_keys** | `claim_sk`, identifiant type sinistre |
| **calculation_rule** | `claim_amount / MEDIAN(claim_amount)` calculé sur la population des dossiers de même type de sinistre |
| **output_type** | `numeric` (NULL si type sinistre non disponible) |
| **null_handling** | Si type sinistre absent : NULL |
| **attention_impact** | Ratio élevé = montant à examiner dans le contexte du type de sinistre |
| **confidence_impact** | Aucun si données complètes |
| **validation_check** | Vérifier la disponibilité du type de sinistre dans le DWH |

---

### Feature : `high_amount_flag`

| Champ | Valeur |
|---|---|
| **feature_name** | `high_amount_flag` |
| **business_label** | Indicateur de montant élevé par rapport aux dossiers comparables |
| **family** | Montant |
| **business_question** | Ce dossier présente-t-il un montant significativement élevé ? |
| **source_tables** | Dérivée de `amount_percentile_by_guarantee` et/ou `amount_vs_guarantee_median_ratio` |
| **join_keys** | `claim_sk` |
| **calculation_rule** | `1` si `amount_percentile_by_guarantee` >= 90 OU `amount_vs_guarantee_median_ratio` >= 2.0 (seuils à calibrer), sinon `0` |
| **output_type** | `boolean` (0 / 1 / NULL) |
| **null_handling** | Si features de base NULL : NULL |
| **attention_impact** | `1` = montant à examiner dans le contexte global |
| **confidence_impact** | Aucun |
| **validation_check** | Vérifier la proportion de dossiers flagués ; ajuster les seuils si la proportion est trop élevée ou trop faible |

---

## 12. Features de cohérence géographique

### 12.1 Contexte

Les features de cohérence géographique vérifient **l'alignement entre les différentes dimensions géographiques** associées au dossier : localisation du sinistre, région du client, région de l'agence.

> **Règle critique :** Les données géographiques ne doivent être utilisées qu'après **stabilisation de l'ETL GEO**. Une géographie manquante ou marquée UNKNOWN est un **problème de qualité des données**, pas un signal de suspicion. Ces features doivent être activées en P2 (priorité secondaire).

---

### Feature : `claim_geo_sk`

| Champ | Valeur |
|---|---|
| **feature_name** | `claim_geo_sk` |
| **business_label** | Clé géographique du lieu du sinistre |
| **family** | Cohérence géographique |
| **business_question** | Le dossier sinistre est-il rattaché à une zone géographique connue ? |
| **source_tables** | `mart.fact_claims`, `mart.dim_geo` |
| **join_keys** | `claim_sk` |
| **calculation_rule** | Clé surrogate `claim_geo_sk` directement issue de `mart.fact_claims` |
| **output_type** | `integer` (NULL si absent) |
| **null_handling** | NULL = géographie sinistre non disponible, confidence abaissée |
| **attention_impact** | Aucun ; clé de jointure pour les autres features GEO |
| **confidence_impact** | NULL = features GEO désactivées, confidence abaissée |
| **validation_check** | Vérifier le taux de renseignement de `claim_geo_sk` |

---

### Feature : `client_geo_sk`

| Champ | Valeur |
|---|---|
| **feature_name** | `client_geo_sk` |
| **business_label** | Clé géographique du client |
| **family** | Cohérence géographique |
| **business_question** | Le client est-il rattaché à une zone géographique connue ? |
| **source_tables** | `mart.dim_client` |
| **join_keys** | `client_sk` |
| **calculation_rule** | Clé surrogate géographique issue de la dimension client |
| **output_type** | `integer` (NULL si absent) |
| **null_handling** | NULL = géographie client indisponible |
| **attention_impact** | Aucun ; base pour la comparaison géographique |
| **confidence_impact** | NULL = comparaison GEO client/sinistre impossible |
| **validation_check** | Vérifier le taux de renseignement de la GEO client |

---

### Feature : `agency_geo_sk`

| Champ | Valeur |
|---|---|
| **feature_name** | `agency_geo_sk` |
| **business_label** | Clé géographique de l'agence |
| **family** | Cohérence géographique |
| **business_question** | L'agence gérant ce dossier est-elle rattachée à une zone géographique connue ? |
| **source_tables** | `mart.dim_agency` |
| **join_keys** | `agency_sk` |
| **calculation_rule** | Clé surrogate géographique issue de la dimension agence |
| **output_type** | `integer` (NULL si absent) |
| **null_handling** | NULL = géographie agence indisponible |
| **attention_impact** | Aucun ; base pour la comparaison agence/sinistre |
| **confidence_impact** | NULL = comparaison GEO agence impossible |
| **validation_check** | Vérifier le taux de renseignement de la GEO agence |

---

### Feature : `geo_mismatch_flag`

| Champ | Valeur |
|---|---|
| **feature_name** | `geo_mismatch_flag` |
| **business_label** | Incohérence géographique client/agence/sinistre à vérifier |
| **family** | Cohérence géographique |
| **business_question** | Les zones géographiques du client, de l'agence et du sinistre sont-elles cohérentes entre elles ? |
| **source_tables** | `mart.fact_claims`, `mart.dim_client`, `mart.dim_agency`, `mart.dim_geo` |
| **join_keys** | `claim_geo_sk`, `client_geo_sk`, `agency_geo_sk` |
| **calculation_rule** | `1` si au moins deux des trois zones géographiques sont disponibles et ne correspondent pas à la même région (règles de correspondance à définir selon le référentiel GEO BNA) |
| **output_type** | `boolean` (0 / 1 / NULL) |
| **null_handling** | Si données GEO insuffisantes pour comparer : NULL, confidence abaissée |
| **attention_impact** | `1` = incohérence géographique = situation à vérifier (à interpréter avec le contexte) |
| **confidence_impact** | NULL = données GEO insuffisantes pour conclure |
| **validation_check** | Vérifier uniquement après stabilisation ETL GEO ; valider le référentiel de correspondance régionale |

---

### Feature : `unknown_geo_flag`

| Champ | Valeur |
|---|---|
| **feature_name** | `unknown_geo_flag` |
| **business_label** | Données géographiques incomplètes |
| **family** | Cohérence géographique |
| **business_question** | Le dossier présente-t-il des données géographiques manquantes ou marquées UNKNOWN ? |
| **source_tables** | `mart.fact_claims`, `mart.dim_geo` |
| **join_keys** | `claim_sk` |
| **calculation_rule** | `1` si `claim_geo_sk` est NULL ou correspond à une valeur UNKNOWN dans `dim_geo` |
| **output_type** | `boolean` (0 / 1) |
| **null_handling** | Ne peut pas être NULL ; toujours calculable |
| **attention_impact** | Aucun impact direct sur l'attention (problème qualité, pas signal métier) |
| **confidence_impact** | `1` = confidence abaissée |
| **validation_check** | Distinguer les UNKNOWN liés à l'ETL GEO des UNKNOWN structurels |

---

### Feature : `same_location_claim_count`

| Champ | Valeur |
|---|---|
| **feature_name** | `same_location_claim_count` |
| **business_label** | Récurrence de sinistres au même lieu |
| **family** | Cohérence géographique |
| **business_question** | D'autres dossiers sinistres sont-ils localisés au même endroit géographique ? |
| **source_tables** | `mart.fact_claims`, `mart.dim_geo` |
| **join_keys** | `claim_geo_sk` |
| **calculation_rule** | `COUNT(DISTINCT claim_sk)` pour les dossiers partageant le même `claim_geo_sk`, hors dossier courant |
| **output_type** | `integer` (NULL si GEO absent) |
| **null_handling** | Si GEO absent : NULL |
| **attention_impact** | Récurrence sur un même lieu = contexte à examiner (seuils à calibrer) |
| **confidence_impact** | Aucun si GEO disponible |
| **validation_check** | Dépend de la granularité du référentiel GEO |

---

### Feature : `agency_region_mismatch_flag`

| Champ | Valeur |
|---|---|
| **feature_name** | `agency_region_mismatch_flag` |
| **business_label** | Incohérence région agence / région sinistre |
| **family** | Cohérence géographique |
| **business_question** | L'agence gérant le dossier est-elle dans une région différente de celle du sinistre ? |
| **source_tables** | `mart.dim_agency`, `mart.fact_claims`, `mart.dim_geo` |
| **join_keys** | `agency_sk`, `claim_geo_sk` |
| **calculation_rule** | `1` si la région de l'agence et la région du sinistre sont disponibles et différentes |
| **output_type** | `boolean` (0 / 1 / NULL) |
| **null_handling** | Si l'une des deux GEO est absente : NULL |
| **attention_impact** | `1` = contexte à examiner (peut avoir des explications légitimes) |
| **confidence_impact** | NULL = données GEO insuffisantes |
| **validation_check** | Vérifier après stabilisation ETL GEO |

---

## 13. Features de qualité des données et de confiance

### 13.1 Contexte

Ces features mesurent **la fiabilité de l'analyse** au regard de la complétude et de la qualité des données disponibles. Elles n'influencent pas le score d'attention directement. Elles déterminent le **niveau de confiance** associé au score.

> **Principe fondamental :** un problème de qualité des données est une limitation d'analyse, pas un signal de suspicion. Ces features protègent contre des conclusions hâtives lorsque les données sont incomplètes.

---

### Feature : `missing_keys_count`

| Champ | Valeur |
|---|---|
| **feature_name** | `missing_keys_count` |
| **business_label** | Nombre de clés techniques manquantes |
| **family** | Qualité des données |
| **business_question** | Combien de clés techniques importantes sont manquantes pour ce dossier ? |
| **source_tables** | `mart.fact_claims` |
| **join_keys** | `claim_sk` |
| **calculation_rule** | Somme des indicateurs : `(client_sk IS NULL)::int + (vehicle_sk IS NULL)::int + (contract_sk IS NULL)::int + (agency_sk IS NULL)::int` |
| **output_type** | `integer` (0-4) |
| **null_handling** | Toujours calculable ; valeur 0 si toutes les clés sont présentes |
| **attention_impact** | Aucun impact direct sur l'attention |
| **confidence_impact** | Augmente avec le nombre de clés manquantes |
| **validation_check** | Vérifier la distribution sur la population totale |

---

### Feature : `unknown_dimensions_count`

| Champ | Valeur |
|---|---|
| **feature_name** | `unknown_dimensions_count` |
| **business_label** | Nombre de dimensions UNKNOWN ou non résolues |
| **family** | Qualité des données |
| **business_question** | Combien de dimensions sont marquées UNKNOWN ou non résolues dans ce dossier ? |
| **source_tables** | `mart.fact_claims`, tables dimensions |
| **join_keys** | `claim_sk` |
| **calculation_rule** | Somme des dimensions dont la valeur est UNKNOWN, DEFAULT ou équivalent dans les tables de dimensions |
| **output_type** | `integer` |
| **null_handling** | Toujours calculable |
| **attention_impact** | Aucun |
| **confidence_impact** | Augmente avec le nombre de dimensions UNKNOWN |
| **validation_check** | Inventorier les valeurs UNKNOWN dans chaque table de dimension |

---

### Feature : `weak_join_flag`

| Champ | Valeur |
|---|---|
| **feature_name** | `weak_join_flag` |
| **business_label** | Indicateur de jointure faible ou incertaine |
| **family** | Qualité des données |
| **business_question** | Ce dossier présente-t-il des jointures critiques incomplètes ou incertaines ? |
| **source_tables** | `mart.fact_claims` |
| **join_keys** | `claim_sk` |
| **calculation_rule** | `1` si `missing_keys_count` >= 2 OU si `client_sk` ET `vehicle_sk` sont tous les deux NULL |
| **output_type** | `boolean` (0 / 1) |
| **null_handling** | Toujours calculable |
| **attention_impact** | Aucun |
| **confidence_impact** | `1` = jointures critiques défaillantes, confidence fortement abaissée |
| **validation_check** | Vérifier la proportion de dossiers avec jointure faible |

---

### Feature : `migration_2019_flag`

| Champ | Valeur |
|---|---|
| **feature_name** | `migration_2019_flag` |
| **business_label** | Dossier potentiellement affecté par la migration 2019 |
| **family** | Qualité des données |
| **business_question** | Ce dossier fait-il partie des données potentiellement affectées par la migration de 2019 ? |
| **source_tables** | `mart.fact_claims` |
| **join_keys** | `claim_sk`, `claim_date` |
| **calculation_rule** | `1` si `claim_date < 2019-01-01` (ou seuil à ajuster selon la date réelle de migration identifiée lors de l'audit) |
| **output_type** | `boolean` (0 / 1) |
| **null_handling** | `0` si `claim_date` disponible et postérieure à la migration ; NULL si `claim_date` absente |
| **attention_impact** | Aucun |
| **confidence_impact** | `1` = dossier antérieur à la migration = interprétation avec prudence accrue |
| **validation_check** | Confirmer la date exacte de migration lors de l'audit des données |

---

### Feature : `missing_client_flag`

| Champ | Valeur |
|---|---|
| **feature_name** | `missing_client_flag` |
| **business_label** | Client non relié au dossier |
| **family** | Qualité des données |
| **business_question** | Le dossier est-il dépourvu de liaison client fiable ? |
| **source_tables** | `mart.fact_claims` |
| **join_keys** | `claim_sk` |
| **calculation_rule** | `1` si `client_sk` IS NULL, sinon `0` |
| **output_type** | `boolean` (0 / 1) |
| **null_handling** | Toujours calculable |
| **attention_impact** | Aucun |
| **confidence_impact** | `1` = features client désactivées, confidence abaissée |
| **validation_check** | Vérifier le taux de dossiers sans `client_sk` |

---

### Feature : `missing_vehicle_flag`

| Champ | Valeur |
|---|---|
| **feature_name** | `missing_vehicle_flag` |
| **business_label** | Véhicule non relié au dossier |
| **family** | Qualité des données |
| **business_question** | Le dossier est-il dépourvu de liaison véhicule fiable ? |
| **source_tables** | `mart.fact_claims` |
| **join_keys** | `claim_sk` |
| **calculation_rule** | `1` si `vehicle_sk` IS NULL, sinon `0` |
| **output_type** | `boolean` (0 / 1) |
| **null_handling** | Toujours calculable |
| **attention_impact** | Aucun |
| **confidence_impact** | `1` = features véhicule et VHS désactivées, confidence abaissée |
| **validation_check** | Vérifier le taux de dossiers sans `vehicle_sk` |

---

### Feature : `missing_geo_flag`

| Champ | Valeur |
|---|---|
| **feature_name** | `missing_geo_flag` |
| **business_label** | Géographie manquante ou indisponible |
| **family** | Qualité des données |
| **business_question** | Le dossier est-il dépourvu de données géographiques fiables ? |
| **source_tables** | `mart.fact_claims`, `mart.dim_geo` |
| **join_keys** | `claim_sk` |
| **calculation_rule** | `1` si `claim_geo_sk` IS NULL OU si `claim_geo_sk` correspond à UNKNOWN dans `dim_geo` |
| **output_type** | `boolean` (0 / 1) |
| **null_handling** | Toujours calculable |
| **attention_impact** | Aucun |
| **confidence_impact** | `1` = features GEO désactivées, confidence abaissée |
| **validation_check** | Vérifier le taux de dossiers sans GEO après ETL GEO stabilisé |

---

### Feature : `confidence_level`

| Champ | Valeur |
|---|---|
| **feature_name** | `confidence_level` |
| **business_label** | Niveau de confiance de l'analyse |
| **family** | Qualité des données |
| **business_question** | Quel est le niveau de fiabilité global de l'analyse pour ce dossier ? |
| **source_tables** | Dérivée de `missing_keys_count`, `unknown_dimensions_count`, `weak_join_flag`, `migration_2019_flag`, `missing_geo_flag` |
| **join_keys** | `claim_sk` |
| **calculation_rule** | Règle à définir précisément (exemple candidat) : `ELEVE` si `missing_keys_count` = 0 ET `unknown_dimensions_count` <= 1 ET `weak_join_flag` = 0 ; `MOYEN` si `missing_keys_count` <= 1 OU `unknown_dimensions_count` <= 3 ; `FAIBLE` sinon |
| **output_type** | `category` (`ELEVE` / `MOYEN` / `FAIBLE`) |
| **null_handling** | Toujours calculable ; valeur par défaut `FAIBLE` si données insuffisantes pour évaluer |
| **attention_impact** | Aucun impact direct sur le score d'attention |
| **confidence_impact** | C'est la feature de confiance principale |
| **validation_check** | Vérifier la distribution des niveaux sur la population totale ; calibrer les seuils |

**Définition des niveaux de confiance :**

| Niveau | Interprétation |
|---|---|
| `ELEVE` | Les jointures principales sont complètes et les dimensions sont fiables. L'analyse peut être exploitée avec confiance. |
| `MOYEN` | Certaines données sont partielles mais l'analyse reste exploitable. Les conclusions doivent être nuancées. |
| `FAIBLE` | Des clés, dimensions ou informations importantes sont manquantes ou incertaines. L'analyse doit être interprétée avec prudence accrue. |

---

## 14. Matrice de disponibilité des features

Le tableau suivant synthétise la disponibilité estimée des features et leur priorité d'implémentation. Les statuts doivent être validés par l'audit de préparation des données.

| Feature | Requise V1 | Disponible maintenant | Dépend GEO | Dépend VHS | Dépend données tiers | Priorité |
|---|---|---|---|---|---|---|
| `client_claim_count_total` | YES | TO_AUDIT | NO | NO | NO | P1 |
| `client_claim_count_12m` | YES | TO_AUDIT | NO | NO | NO | P1 |
| `client_claim_count_24m` | YES | TO_AUDIT | NO | NO | NO | P1 |
| `days_since_previous_claim` | YES | TO_AUDIT | NO | NO | NO | P1 |
| `client_claim_frequency_band` | YES | TO_AUDIT | NO | NO | NO | P1 |
| `vehicle_claim_count_total` | YES | TO_AUDIT | NO | NO | NO | P1 |
| `vehicle_claim_count_12m` | YES | TO_AUDIT | NO | NO | NO | P1 |
| `days_since_previous_vehicle_claim` | YES | TO_AUDIT | NO | NO | NO | P1 |
| `linked_vhs_score` | PARTIAL | TO_AUDIT | NO | YES | NO | P2 |
| `linked_vhs_grade` | PARTIAL | TO_AUDIT | NO | YES | NO | P2 |
| `linked_vhs_attention_level` | PARTIAL | TO_AUDIT | NO | YES | NO | P2 |
| `days_between_vhs_and_claim` | PARTIAL | TO_AUDIT | NO | YES | NO | P2 |
| `vhs_linkage_flag` | YES | TO_AUDIT | NO | YES | NO | P2 |
| `third_party_claim_count_total` | PARTIAL | TO_AUDIT | NO | NO | YES | P3 |
| `third_party_claim_count_24m` | PARTIAL | TO_AUDIT | NO | NO | YES | P3 |
| `client_third_party_pair_count` | PARTIAL | TO_AUDIT | NO | NO | YES | P3 |
| `same_driver_claim_count_total` | PARTIAL | TO_AUDIT | NO | NO | YES | P3 |
| `driver_client_mismatch_flag` | NO | TO_AUDIT | NO | NO | YES | P3 |
| `days_contract_start_to_claim` | YES | TO_AUDIT | NO | NO | NO | P1 |
| `days_claim_to_declaration` | YES | TO_AUDIT | NO | NO | NO | P1 |
| `recent_contract_change_flag` | PARTIAL | TO_AUDIT | NO | NO | NO | P1 |
| `recent_guarantee_change_flag` | PARTIAL | TO_AUDIT | NO | NO | NO | P1 |
| `claim_before_contract_start_flag` | YES | TO_AUDIT | NO | NO | NO | P1 |
| `claim_after_recent_update_flag` | PARTIAL | TO_AUDIT | NO | NO | NO | P1 |
| `claim_amount` | YES | TO_AUDIT | NO | NO | NO | P1 |
| `amount_vs_guarantee_median_ratio` | YES | TO_AUDIT | NO | NO | NO | P1 |
| `amount_percentile_by_guarantee` | YES | TO_AUDIT | NO | NO | NO | P1 |
| `amount_vs_region_median_ratio` | PARTIAL | TO_AUDIT | YES | NO | NO | P2 |
| `amount_vs_claim_type_median_ratio` | PARTIAL | TO_AUDIT | NO | NO | NO | P1 |
| `high_amount_flag` | YES | TO_AUDIT | NO | NO | NO | P1 |
| `claim_geo_sk` | YES | TO_AUDIT | YES | NO | NO | P2 |
| `client_geo_sk` | PARTIAL | TO_AUDIT | YES | NO | NO | P2 |
| `agency_geo_sk` | PARTIAL | TO_AUDIT | YES | NO | NO | P2 |
| `geo_mismatch_flag` | PARTIAL | TO_AUDIT | YES | NO | NO | P2 |
| `unknown_geo_flag` | YES | TO_AUDIT | YES | NO | NO | P2 |
| `same_location_claim_count` | PARTIAL | TO_AUDIT | YES | NO | NO | P2 |
| `agency_region_mismatch_flag` | PARTIAL | TO_AUDIT | YES | NO | NO | P2 |
| `missing_keys_count` | YES | YES | NO | NO | NO | P1 |
| `unknown_dimensions_count` | YES | YES | NO | NO | NO | P1 |
| `weak_join_flag` | YES | YES | NO | NO | NO | P1 |
| `migration_2019_flag` | YES | YES | NO | NO | NO | P1 |
| `missing_client_flag` | YES | YES | NO | NO | NO | P1 |
| `missing_vehicle_flag` | YES | YES | NO | NO | NO | P1 |
| `missing_geo_flag` | YES | YES | YES | NO | NO | P1 |
| `confidence_level` | YES | PARTIAL | NO | NO | NO | P1 |

**Légende des priorités :**

| Priorité | Contenu | Condition d'activation |
|---|---|---|
| **P1** | Récurrence client, récurrence véhicule (sans VHS), chronologie, montant, qualité/confiance | Données DWH de base disponibles |
| **P2** | Cohérence géographique, liaison VHS | ETL GEO stabilisé ET module VHS accessible |
| **P3** | Récurrence tiers / conducteur | Données tiers/conducteur suffisamment complètes dans le DWH |

---

## 15. Règles de gestion des valeurs nulles et UNKNOWN

Les règles suivantes s'appliquent uniformément à toutes les features.

### 15.1 Clés techniques manquantes

| Situation | Effet |
|---|---|
| `client_sk` manquant | Features récurrence client = NULL ; `missing_client_flag` = 1 ; confidence abaissée |
| `vehicle_sk` manquant | Features récurrence véhicule + VHS = NULL ; `missing_vehicle_flag` = 1 ; confidence abaissée |
| `contract_sk` manquant | Features chronologie contrat = NULL ; confidence abaissée |
| `agency_sk` manquant | Features agence et comparaisons agence = NULL |

### 15.2 Données géographiques

| Situation | Effet |
|---|---|
| `claim_geo_sk` NULL ou UNKNOWN | Features GEO = NULL ; `missing_geo_flag` = 1 ; `unknown_geo_flag` = 1 ; confidence abaissée |
| GEO client manquante | Comparaison client/sinistre impossible |
| GEO agence manquante | Comparaison agence/sinistre impossible |

> **Rappel :** une géographie UNKNOWN est un problème de qualité des données, **pas un signal de suspicion**.

### 15.3 Montants

| Situation | Effet |
|---|---|
| `claim_amount` NULL | Toutes les features de comparaison de montant = NULL ; `high_amount_flag` = NULL |
| `claim_amount` négatif | Anomalie qualité à signaler ; features montant non calculables |

### 15.4 Dates

| Situation | Effet |
|---|---|
| `claim_date` NULL | Features de récurrence temporelle = NULL ; `migration_2019_flag` = NULL |
| `declaration_date` NULL | `days_claim_to_declaration` = NULL ; confidence légèrement abaissée |
| Dates incohérentes (négatives) | Anomalie qualité à signaler ; feature = NULL |

### 15.5 Données tiers et conducteur

| Situation | Effet |
|---|---|
| Identifiant tiers absent | Features récurrence tiers = NULL ; confidence modérément abaissée |
| Données tiers partielles | `third_party_claim_count_total` = NULL ; P3 reporté |

> **Règle essentielle :** L'absence de données tiers ne doit **pas automatiquement augmenter** le score d'attention. Elle doit uniquement réduire la confiance et désactiver les features concernées.

### 15.6 Données VHS

| Situation | Effet |
|---|---|
| Aucune inspection VHS disponible | `linked_vhs_score` = NULL ; `vhs_linkage_flag` = 0 ; features VHS = NULL |
| Inspection VHS postérieure au sinistre | `days_between_vhs_and_claim` potentiellement négatif = à exclure |

### 15.7 Affichage des limitations

Toute limitation liée à la qualité des données doit être **visible dans la sortie** du score, au travers du `confidence_level` et des flags de qualité. Un utilisateur Power BI doit pouvoir distinguer immédiatement un dossier scoré avec confiance élevée d'un dossier scoré avec confiance faible.

---

## 16. Mapping explication métier des features

Le tableau suivant définit le libellé métier à utiliser dans Power BI et dans les explications du score, pour chaque famille de features.

| Feature | Libellé métier affiché | Famille |
|---|---|---|
| `client_claim_count_12m` | Récurrence de sinistres client sur 12 mois | Récurrence client |
| `client_claim_count_24m` | Récurrence de sinistres client sur 24 mois | Récurrence client |
| `client_claim_count_total` | Historique global des sinistres client | Récurrence client |
| `days_since_previous_claim` | Délai depuis le précédent sinistre client | Récurrence client |
| `client_claim_frequency_band` | Niveau de fréquence sinistres client | Récurrence client |
| `vehicle_claim_count_12m` | Récurrence récente de sinistres sur le véhicule | Récurrence véhicule |
| `vehicle_claim_count_total` | Historique total des sinistres du véhicule | Récurrence véhicule |
| `days_since_previous_vehicle_claim` | Délai depuis le précédent sinistre du véhicule | Récurrence véhicule |
| `linked_vhs_score` | Score d'état technique du véhicule | VHS |
| `linked_vhs_attention_level` | État technique du véhicule à considérer | VHS |
| `days_between_vhs_and_claim` | Proximité temporelle inspection/sinistre | VHS |
| `vhs_linkage_flag` | Inspection technique disponible pour ce véhicule | VHS |
| `third_party_claim_count_total` | Récurrence globale du tiers dans les dossiers | Récurrence tiers |
| `third_party_claim_count_24m` | Récurrence récente du tiers sur 24 mois | Récurrence tiers |
| `client_third_party_pair_count` | Répétition du couple client/tiers | Récurrence tiers |
| `same_driver_claim_count_total` | Récurrence du conducteur dans les dossiers | Récurrence conducteur |
| `driver_client_mismatch_flag` | Discordance conducteur/titulaire contrat | Récurrence conducteur |
| `days_contract_start_to_claim` | Chronologie contrat/sinistre à examiner | Chronologie |
| `days_claim_to_declaration` | Délai de déclaration inhabituel | Chronologie |
| `recent_contract_change_flag` | Changement récent de contrat | Chronologie |
| `recent_guarantee_change_flag` | Changement récent de garantie | Chronologie |
| `claim_before_contract_start_flag` | Sinistre antérieur au début du contrat | Chronologie |
| `claim_after_recent_update_flag` | Sinistre après modification récente du dossier | Chronologie |
| `claim_amount` | Montant déclaré du sinistre | Montant |
| `amount_vs_guarantee_median_ratio` | Montant supérieur aux dossiers comparables | Montant |
| `amount_percentile_by_guarantee` | Dossier dans les montants les plus élevés | Montant |
| `amount_vs_region_median_ratio` | Montant comparé à la médiane régionale | Montant |
| `high_amount_flag` | Indicateur de montant élevé par rapport aux dossiers similaires | Montant |
| `geo_mismatch_flag` | Incohérence géographique client/agence/sinistre | Géographie |
| `unknown_geo_flag` | Données géographiques incomplètes | Géographie |
| `same_location_claim_count` | Récurrence de sinistres au même lieu | Géographie |
| `agency_region_mismatch_flag` | Incohérence région agence/sinistre | Géographie |
| `missing_keys_count` | Clés techniques manquantes | Qualité données |
| `unknown_dimensions_count` | Dimensions non résolues | Qualité données |
| `weak_join_flag` | Jointures critiques défaillantes | Qualité données |
| `migration_2019_flag` | Dossier potentiellement affecté par la migration 2019 | Qualité données |
| `missing_client_flag` | Client non relié au dossier | Qualité données |
| `missing_vehicle_flag` | Véhicule non relié au dossier | Qualité données |
| `missing_geo_flag` | Géographie manquante ou indisponible | Qualité données |
| `confidence_level` | Niveau de confiance de l'analyse | Qualité données |

**Règle d'affichage :** afficher le libellé métier (colonne `business_label`), **jamais** le nom technique (colonne `feature_name`), dans les interfaces utilisateur, Power BI et rapports destinés aux gestionnaires.

---

## 17. Contrôles de validation avant implémentation

Avant de passer à l'implémentation des features, les vérifications suivantes doivent être effectuées en mode lecture seule (notebook exploratoire).

### 17.1 Contrôles de liaisons clés

| Contrôle | Objectif | Seuil d'alerte |
|---|---|---|
| Nombre de dossiers avec `client_sk` valide | Vérifier la couverture client | < 80 % → audit requis |
| Nombre de dossiers avec `vehicle_sk` valide | Vérifier la couverture véhicule | < 80 % → audit requis |
| Nombre de dossiers avec `contract_sk` valide | Vérifier la couverture contrat | < 80 % → audit requis |
| Nombre de dossiers avec `agency_sk` valide | Vérifier la couverture agence | < 70 % → audit requis |

### 17.2 Contrôles de dates

| Contrôle | Objectif | Seuil d'alerte |
|---|---|---|
| % de dossiers avec `claim_date` valide | Vérifier la disponibilité des dates sinistre | < 90 % → alerte critique |
| % de dossiers avec `declaration_date` valide | Vérifier la disponibilité des dates de déclaration | < 80 % → alerte |
| Nombre de dossiers avec `claim_date < contract_start_date` | Identifier les anomalies chronologiques | > 1 % → audit |
| Nombre de valeurs `days_claim_to_declaration` négatives | Identifier les inversions de dates | > 0 → audit qualité |
| Nombre de valeurs `days_contract_start_to_claim` négatives | Identifier les anomalies contrat | > 0 → audit qualité |

### 17.3 Contrôles de montants

| Contrôle | Objectif | Seuil d'alerte |
|---|---|---|
| % de dossiers avec `claim_amount` disponible | Vérifier la couverture des montants | < 70 % → features montant partielles |
| Présence de montants négatifs | Identifier les anomalies | Tout négatif → audit |
| Distribution globale des montants | Vérifier la cohérence | Audit si max >> percentile 99 |

### 17.4 Contrôles géographiques

| Contrôle | Objectif | Seuil d'alerte |
|---|---|---|
| % de dossiers avec `claim_geo_sk` valide | Vérifier la couverture GEO après stabilisation ETL | < 60 % → features GEO P2 non activables |
| Proportion de valeurs UNKNOWN dans `dim_geo` | Évaluer la qualité de l'ETL GEO | > 20 % → activation GEO reportée |

### 17.5 Contrôles VHS

| Contrôle | Objectif | Seuil d'alerte |
|---|---|---|
| % de dossiers liables à une inspection VHS | Vérifier la couverture VHS | < 30 % → features VHS partielles en V1 |
| Cohérence chronologique inspection VHS / `claim_date` | Vérifier que l'inspection précède le sinistre | Tout cas négatif → audit |

### 17.6 Contrôles de déduplication et intégrité

| Contrôle | Objectif | Seuil d'alerte |
|---|---|---|
| Doublons sur `claim_sk` | Vérifier l'unicité du grain | Tout doublon → critique |
| Doublons sur `claim_business_id` (`NUMSNT`) | Vérifier l'identifiant naturel | Tout doublon → audit |
| Dossiers sans identifiant naturel | Vérifier la complétude | > 1 % → audit |
| Dossiers avant et après la migration 2019 | Mesurer l'impact migration | Documenter la proportion |

---

## 18. Feuille de route d'implémentation

La construction des features suit un processus progressif et contrôlé.

| Étape | Action | Livrable | Statut |
|---|---|---|---|
| **1** | Validation de la présente spécification par l'équipe projet | Ce document approuvé | En cours |
| **2** | Notebook exploratoire read-only — test des jointures et distributions candidates | `notebooks/validation_scoring/01_claim_scoring_data_readiness.ipynb` | À créer |
| **3** | Construction des requêtes d'extraction de features (SQL read-only) | Requêtes de validation documentées | À créer |
| **4** | Validation des distributions de chaque feature (volumes, nulls, outliers) | Rapport de distribution | À créer |
| **5** | Implémentation du script de feature mart via ETL contrôlé | `etl/mart/compute_claim_scoring_features_v1.py` | À créer |
| **6** | Rédaction du document de règles du score V1 | `docs/scoring/claim_attention_score_rules_v1.md` | À créer |
| **7** | Implémentation du moteur de score d'attention V1 | `etl/mart/compute_claim_attention_score_v1_candidate.py` | À créer |
| **8** | Validation de la distribution du score (notebook dédié) | `notebooks/validation_scoring/02_validate_claim_attention_score_v1.ipynb` | À créer |
| **9** | Documentation des résultats de validation | `docs/scoring/claim_attention_validation_summary.md` | À créer |
| **10** | Préparation des tables mart pour Power BI | Tables `mart.fact_claim_attention_score` et `mart.fact_claim_attention_signal_detail` | À créer |

> **Règle de séquençage :** aucune étape ne doit démarrer avant validation complète de l'étape précédente. En particulier, l'étape 5 (feature mart) ne doit démarrer qu'après approbation des résultats de l'étape 4.

---

## 19. Risques et mitigations

| Risque | Impact potentiel | Mitigation |
|---|---|---|
| Jointures faibles (`client_sk`, `vehicle_sk` manquants sur une proportion élevée de dossiers) | Features de récurrence non calculables ; score partiel ou peu fiable | Documenter le taux de liaison ; activer `confidence_level = FAIBLE` ; ne pas forcer le score si jointures critiques absentes |
| Données tiers incomplètes | Features tiers non disponibles en V1 | Traiter les features tiers en P3 ; ne pas interpréter l'absence de données tiers comme un signal |
| ETL GEO instable ou non finalisé | Features géographiques non fiables | Placer les features GEO en P2 ; activer uniquement après validation de l'ETL GEO |
| Faible taux de liaison VHS | Contexte technique VHS disponible pour peu de dossiers | Documenter le taux ; limiter le poids VHS à 5 points ; `vhs_linkage_flag` = 0 désactive le signal VHS |
| Sur-pondération d'une famille de signaux | Score dominé par une seule famille, réduisant l'équilibre | Respecter les plafonds de pondération définis dans la méthodologie ; valider la distribution des contributions par famille |
| Traitement des problèmes de qualité comme des signaux de suspicion | Dossiers à données incomplètes présentent un score d'attention artificiel | Séparer strictement les features de confiance et les features d'attention ; appliquer les règles null handling |
| Utilisation d'informations post-sinistre (biais temporel) | Features calculées avec des données postérieures à la date du sinistre | Appliquer systématiquement des filtres temporels `< claim_date` pour les calculs d'historique |
| Effet migration 2019 sur les données historiques | Ruptures dans les séries temporelles ; récurrences sous-estimées avant 2019 | Appliquer `migration_2019_flag` ; analyser séparément les distributions avant/après 2019 ; documenter les limites |
| Calibration des seuils sans retour métier | Seuils arbitraires produisant trop ou trop peu de signaux | Analyser les distributions réelles avant de fixer les seuils ; valider avec les experts BNA |
| Absence de labels fraude pour calibration | Impossibilité d'évaluer la précision du score par rapport à des cas réels | Documenter clairement la limite ; maintenir le score comme aide à la priorisation uniquement ; préparer une gouvernance human-in-the-loop |

---

## 20. Conclusion

Ce document de spécification des features constitue le **pont opérationnel** entre la méthodologie du score d'attention dossier IRIS et sa future implémentation dans le DWH.

Il traduit chaque famille de signaux définie dans la méthodologie en features concrètes, calculables, sourcées et documentées, selon un format standardisé qui garantit :

- **l'explicabilité** : chaque feature a un libellé métier et une question métier claire ;
- **la traçabilité** : chaque feature identifie ses sources et ses règles de calcul ;
- **la prudence d'interprétation** : aucune feature ne constitue seule un signal de suspicion ;
- **la séparation attention / confiance** : les problèmes de qualité des données sont isolés des signaux métier ;
- **la progressivité** : les features sont priorisées en P1, P2, P3 selon la disponibilité des données.

> **Les features du score d'attention doivent rester explicables, traçables et séparées des problèmes de qualité des données.**

Ce document ne contient aucune implémentation. Aucun script Python n'a été créé. Aucune table n'a été créée en base de données. Aucun fichier ETL n'a été modifié. Aucun modèle Machine Learning n'a été conçu. La prochaine étape est la validation de ce document, suivie de la création d'un notebook exploratoire en lecture seule.

---

## Contrôles qualité du document

| Contrôle | Statut |
|---|---|
| Grain dossier sinistre défini | OK |
| Source de vérité DWH PostgreSQL | OK |
| Table feature mart cible décrite (conceptuelle) | OK |
| Features récurrence client définies | OK |
| Features récurrence véhicule définies | OK |
| Features VHS définies | OK |
| Features récurrence tiers / conducteur définies | OK |
| Features chronologie définies | OK |
| Features montant définies | OK |
| Features géographiques définies | OK |
| Features qualité des données / confiance définies | OK |
| Matrice de disponibilité incluse | OK |
| Règles null handling définies | OK |
| Mapping explications métier inclus | OK |
| Contrôles de validation avant implémentation définis | OK |
| Feuille de route d'implémentation incluse | OK |
| Pas d'implémentation ML | OK |
| Pas d'écriture en base de données | OK |
| Pas de modification de code de production | OK |
| Vocabulaire prudent (signal à examiner, situation à vérifier) | OK |
| VHS positionné comme signal technique limité | OK |
| GEO conditionnée à stabilisation ETL | OK |
| Données tiers en P3 si incomplètes | OK |

---

_Document créé dans le cadre du projet IRIS Auto Fraud Decision Platform — PFE BNA Assurances._
_Ce document est de nature documentaire uniquement. Aucune modification de code de production, aucune écriture en base de données et aucune implémentation de scoring n'ont été réalisées._

---

## Mise a jour implementation V1

Une implementation candidate du feature mart a ete ajoutee dans `etl/mart/compute_claim_scoring_features_v1.py`.

La V1 applique les choix suivants :

- une ligne par dossier sinistre dans `mart.fact_claim_scoring_features` ;
- `fact_sinistre_sk` comme `claim_sk` et `sinistre_garantie_key` comme identifiant metier ;
- cles techniques `0` traitees comme manquantes ;
- recurrence client calculee uniquement sur des sinistres strictement anterieurs au dossier courant ;
- montant compare par `code_garantie` sur les montants positifs ;
- date DWH `YYYYMMDD` convertie avant les calculs de delai ;
- familles GEO, VHS, recurrence vehicule et tiers/conducteur conservees en flags readiness sans points d'attention V1.

