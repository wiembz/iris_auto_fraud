# Synthèse finale du module Vehicle Health Score

> **Document de référence transversal — Module VHS**  
> **Version :** 1.0 — 2026-07-04  
> **Profil validé :** `VHS_BALANCED_V3_CANDIDATE`  
> **Destinataires :** BNA Assurances, encadrement académique, jury technique

---

## 1. Pourquoi le VHS existe

Le projet IRIS Auto Fraud Decision Platform vise à doter BNA Assurances d'outils d'aide à la décision fondés sur des données techniques objectives. Dans ce cadre, le module **Vehicle Health Score (VHS)** répond à une question métier précise :

> *« À partir des résultats d'une inspection STAFFIM, dans quel état technique se trouve ce véhicule, et quelle est la priorité d'attention qu'il requiert ? »*

Avant l'existence du VHS, cette synthèse reposait entièrement sur la lecture manuelle des rapports d'inspection par les gestionnaires, sans harmonisation ni indicateur agrégé. Le VHS introduit :

- un **score numérique** [0, 100] permettant de comparer objectivement les véhicules,
- un **niveau d'attention** métier lisible par des non-experts,
- une **explicabilité** directe par les points de contrôle observés,
- une **traçabilité** reproductible liée à une version de règles identifiée.

Le VHS est un **indicateur d'aide à la décision**, pas un verdict automatique. La décision finale reste sous la responsabilité du gestionnaire ou de l'expert BNA Assurances.

---

## 2. Données utilisées : inspections STAFFIM

### 2.1 Source des données

Les données d'entrée du module VHS proviennent exclusivement des **inspections techniques réalisées via le protocole STAFFIM** (Système de Traitement Automatisé des Fiches d'Inspection des Mobiles).

Chaque inspection STAFFIM fournit :

| Élément | Description |
|---------|-------------|
| Identifiant d'inspection | Clé unique de traçabilité |
| Points de contrôle (checkpoints) | Liste des éléments techniques inspectés |
| Valeur observée par checkpoint | Résultat brut de l'inspection |
| Indicateurs annexes | `est_anomalie_critique`, `is_immobilizing`, niveaux de sévérité (`tier`) |

### 2.2 Transformation préalable

Avant calcul du score, les valeurs brutes STAFFIM subissent une normalisation en **statut technique standardisé** selon les règles V3 :

| Valeur brute observée | Statut normalisé | Libellé métier |
|----------------------|-----------------|----------------|
| Conforme, Bon état | `OK` | Élément conforme |
| Usure normale | `WORN` | Usure observée |
| Intervention conseillée + `est_anomalie_critique=TRUE` | `WORN_STRONG` | Intervention conseillée |
| Défectueux, Contrôle non OK | `BROKEN` | Défaut confirmé |
| Réparé | `REPAIRED` | Élément réparé |
| Valeur non reconnue | `UNKNOWN` | Information non exploitable |

Les valeurs **PROPOSITION FAITE** et **NON** ne sont jamais normalisées en `BROKEN`. Elles produisent au maximum `WORN_STRONG`, conformément à la règle métier V3 visant à éviter les faux positifs d'immobilisation.

### 2.3 Périmètre de validation

Le run de référence validé couvre **286 inspections STAFFIM** du profil `VHS_BALANCED_V3_CANDIDATE`, avec **9 724 lignes de détail checkpoint**, et **0 anomalie de mapping** détectée.

---

## 3. Méthode retenue : score déterministe, pas ML

### 3.1 Choix de conception

Le VHS est un **moteur de scoring déterministe à base de règles**. Pour un même ensemble de points de contrôle et une même version de règles, il produit toujours le même résultat. Ce choix délibère répond à quatre exigences :

| Exigence | Justification |
|----------|--------------|
| **Explicabilité immédiate** | Chaque score est justifiable par la contribution de ses checkpoints, sans modèle boîte noire |
| **Auditabilité** | Les règles sont lisibles, versionnées et modifiables sous contrôle |
| **Indépendance vis-à-vis du volume de données historiques** | Un modèle supervisé nécessite des labels humains validés en quantité suffisante — non disponibles à ce stade |
| **Conformité métier** | BNA Assurances peut valider chaque règle individuellement avant approbation |

### 3.2 Architecture du moteur

Le moteur actif est implémenté dans `etl/mart/compute_vhs_v3_candidate.py`. Il suit la séquence suivante :

```
Checkpoints STAFFIM
    → Normalisation du statut observé (10 règles prioritaires)
    → Calcul de la pénalité par checkpoint
    → Agrégation du score final (somme pondérée des pénalités)
    → Application des caps (IMMOBILISE si checkpoint immobilisant BROKEN)
    → Attribution de la note (A / B / C / D) et du niveau d'attention
    → Traduction en libellés métier
```

### 3.3 Pourquoi pas SHAP, pas XGBoost

- **SHAP** est une méthode d'explicabilité pour les modèles ML non-linéaires (arbres, réseaux). Il est sans objet pour un score déterministe dont la contribution de chaque variable est déjà calculable directement.
- **XGBoost** et tout modèle supervisé nécessitent des labels d'entraînement fiables. Ces labels (décisions d'experts validées) n'existent pas encore — ils seront construits progressivement via le workflow human-in-the-loop décrit en section 6.

---

## 4. Résultats de validation

### 4.1 Run de référence

| Paramètre | Valeur |
|-----------|--------|
| Profil | `VHS_BALANCED_V3_CANDIDATE` |
| Run ID | `VHS_BALANCED_V3_CANDIDATE_20260703_181257` |
| Script actif | `etl/mart/compute_vhs_v3_candidate.py` |
| Inspections scorées | 286 |
| Lignes de pénalité | 9 724 |
| Anomalies de mapping | **0** |
| Statut de validation | **PASS** |

### 4.2 Distribution des niveaux d'attention

| Niveau d'attention | Code technique | Nombre | % |
|-------------------|----------------|-------:|---|
| État satisfaisant | `OK` | 89 | 31,1 % |
| État à surveiller | `DEGRADE` | 133 | 46,5 % |
| Usage déconseillé | `IMMOBILISE` | 13 | 4,5 % |
| Examen prioritaire suggéré | `CRITIQUE` | 51 | 17,8 % |
| **Total** | | **286** | **100 %** |

### 4.3 Distribution des niveaux d'état technique

| Note | Libellé | Nombre |
|------|---------|-------:|
| A | Aucun signal technique majeur | 95 |
| B | Quelques points à surveiller | 11 |
| C | Dégradation technique notable | 129 |
| D | Situation technique sensible | 51 |

### 4.4 Distribution des statuts checkpoint

| Statut normalisé | Libellé métier | Occurrences |
|-----------------|----------------|------------:|
| `OK` | Élément conforme | 8 538 |
| `WORN` | Usure observée | 389 |
| `WORN_STRONG` | Intervention conseillée | 283 |
| `BROKEN` | Défaut confirmé | 502 |
| `REPAIRED` | Élément réparé | 12 |
| `UNKNOWN` | Information non exploitable | 0 |

### 4.5 Vérifications critiques

| Vérification | Attendu | Observé | Statut |
|---|---:|---:|---|
| PROPOSITION FAITE → BROKEN | 0 | 0 | PASS |
| NON → BROKEN | 0 | 0 | PASS |
| UNKNOWN = 0 (mapping complet) | 0 | 0 | PASS |
| Score dans [0, 100] | True | True | PASS |
| Cas Usage déconseillé après correctif V3 | 13 | 13 | PASS |

### 4.6 Statistiques de score

| Métrique | Valeur |
|----------|--------|
| Score moyen | 56,46 / 100 |
| Score minimum | 0,00 |
| Score maximum | 100,00 |

### 4.7 Correctif V3 — réduction Usage déconseillé

Le passage de V2 à V3 a corrigé une sur-activation du niveau **Usage déconseillé** :

| Niveau | Avant correctif (V2) | Après correctif (V3) | Variation |
|--------|--------------------:|--------------------:|----------|
| Usage déconseillé | 25 | 13 | −12 |
| État à surveiller | 121 | 133 | +12 |

**Cause racine V2 :** le flag `is_immobilizing` n'était pas conditionné à `observed_status = BROKEN`. Des checkpoints en statut *Intervention conseillée* déclenchaient à tort le niveau Usage déconseillé.

**Correctif V3 :** Usage déconseillé requiert désormais `is_immobilizing = TRUE` **ET** `observed_status = BROKEN` simultanément.

---

## 5. Explicabilité métier : checkpoints et libellés

### 5.1 Principe

L'explicabilité du VHS est **directe et déterministe**. Chaque composante du score est traçable vers un ou plusieurs points de contrôle STAFFIM observés. Il n'est pas nécessaire de recourir à une méthode d'explicabilité externe.

Pour chaque inspection, il est possible de répondre aux questions suivantes :

- *Pourquoi ce score ?* → Somme des pénalités par checkpoint.
- *Quel checkpoint a le plus impacté le score ?* → Classement par `penalty_abs` décroissant.
- *Pourquoi ce niveau d'attention ?* → Règles de cap appliquées (BROKEN sur checkpoint immobilisant → Usage déconseillé).

### 5.2 Correspondances officielles

| Statut normalisé | Libellé métier affiché | Exposition aux non-experts |
|-----------------|----------------------|--------------------------|
| `OK` | Élément conforme | ✓ Oui |
| `WORN` | Usure observée | ✓ Oui |
| `WORN_STRONG` | Intervention conseillée | ✓ Oui |
| `BROKEN` | Défaut confirmé | ✓ Oui |
| `REPAIRED` | Élément réparé | ✓ Oui |
| `UNKNOWN` | Information non exploitable | ✓ Oui |

Les termes techniques internes (`normalized_status`, `hard_cap`, `penalty_abs`, `is_immobilizing`) ne sont jamais exposés dans les interfaces utilisateurs de BNA Assurances.

### 5.3 Exemple d'explication type

Pour un véhicule classé **Examen prioritaire suggéré** (score 24/100) :

```
Points de contrôle principaux :
  • Freins avant     → Défaut confirmé      (−18,0 pts)
  • Pneumatiques     → Défaut confirmé      (−12,5 pts)
  • Direction        → Intervention conseillée (−6,0 pts)
  • Amortisseurs     → Usure observée        (−3,0 pts)

Score final : 24 / 100
Niveau : Examen prioritaire suggéré
Note   : D — Situation technique sensible
```

Cette explication est lisible par un gestionnaire non technique sans formation en data science.

---

## 6. Gouvernance future : human-in-the-loop et historisation

La validation technique du VHS constitue une première étape. La maturité opérationnelle du module implique une couche de gouvernance complémentaire, documentée dans :

- `docs/vhs/governance/vhs_human_in_the_loop_and_history_architecture.md`
- `docs/vhs/governance/vhs_governance_table_design.md`
- `docs/vhs/governance/sql/001_create_vhs_governance_tables.sql` *(DDL validé en base de test)*

### 6.1 Principes structurants

**Human-in-the-loop :** chaque proposition VHS peut être confirmée, corrigée ou rejetée par un gestionnaire ou expert BNA via l'interface IRIS. La revue humaine ne modifie jamais le score calculé — elle l'accompagne.

**Historisation :** chaque score produit est conservé avec sa version de règles, son explication checkpoint et son éventuelle revue humaine. L'historique est immuable et auditable.

**Métriques de stabilité :** les taux de confirmation et de correction par niveau d'attention permettent de mesurer la confiance métier dans les propositions VHS et d'identifier les règles à recalibrer.

### 6.2 Tables de gouvernance proposées

| Table | Rôle |
|-------|------|
| `mart.dim_vhs_rule_version` | Versionnement des règles |
| `mart.fact_vhs_score_history` | Historique des scores (append-only) |
| `mart.fact_vhs_penalty_detail_history` | Historique des explications checkpoint |
| `mart.vhs_human_review` | Décisions des experts (CONFIRMED / CORRECTED / REJECTED) |
| `mart.vhs_stability_metrics` | Taux de confirmation et de correction agrégés |

Ces tables ont été validées syntaxiquement dans la base de test `iris_auto_fraud_TEST`. Leur déploiement en production est conditionné à la validation formelle de BNA Assurances.

### 6.3 Vers un futur modèle supervisé

Une fois les revues humaines accumulées en volume suffisant, il sera possible de construire un dataset supervisé à partir des décisions d'experts et d'entraîner un modèle ML complémentaire (ex. XGBoost) pour la priorisation des dossiers. Ce modèle sera un **complément** au VHS déterministe, non un remplacement. SHAP sera alors pertinent pour expliquer ses prédictions.

---

## 7. Limites

### 7.1 Volume de validation

La validation technique repose sur **286 inspections** issues d'un run unique du profil `VHS_BALANCED_V3_CANDIDATE`. Ce volume est suffisant pour une validation académique et un prototype fonctionnel, mais insuffisant pour :

- mesurer la stabilité du score sur des données saisonnières,
- évaluer la robustesse sur des typologies de véhicules rares,
- calibrer les seuils de décision sur une base statistiquement représentative.

### 7.2 Validation métier BNA non encore réalisée

La validation présentée est **technique**. Elle confirme que les règles produisent des résultats cohérents avec leur définition. Elle ne constitue pas une validation **métier** par BNA Assurances, qui demeure une condition préalable à toute mise en production.

BNA Assurances devra notamment statuer sur :

- l'adéquation des seuils de scores aux niveaux d'attention,
- la liste des checkpoints immobilisants (`is_immobilizing = TRUE`),
- la formulation des libellés métier exposés aux gestionnaires,
- les règles de priorisation de la file de revue humaine.

### 7.3 Pas de déploiement en production autonome

Le VHS ne peut pas être déployé en production de manière autonome sans :

- approbation formelle de BNA Assurances,
- mise en place du workflow human-in-the-loop,
- déploiement des tables de gouvernance dans la base principale,
- formation des gestionnaires à l'utilisation des niveaux d'attention.

### 7.4 Limites intrinsèques du score

| Limite | Description |
|--------|-------------|
| Score non probabiliste | Le VHS ne fournit pas une probabilité de sinistre ou de fraude |
| Dépendance à la qualité STAFFIM | Des inspections incomplètes ou mal renseignées produisent des statuts `UNKNOWN` |
| Règles figées à un instant donné | L'évolution de la nomenclature STAFFIM exige une révision de version |
| Pas de prise en compte du contexte | Le VHS ne considère pas l'historique des sinistres, le profil du conducteur ou la valeur du véhicule |

---

## 8. Conclusion : une brique d'aide à la décision, pas un verdict

Le Vehicle Health Score est une **brique d'aide à la décision** conçue pour transformer les données techniques brutes des inspections STAFFIM en un signal lisible, explicable et auditable à destination des équipes de BNA Assurances.

Il ne constitue pas un verdict automatique sur la conformité ou la régularité d'un dossier. Il ne formule pas d'accusation et n'écarte pas de dossier de manière autonome.

**Ce que le VHS fait :**

- Synthétise objectivement l'état technique d'un véhicule à partir de ses points de contrôle.
- Propose un niveau d'attention hiérarchisé, accompagné d'une explication accessible.
- Fournit une base reproductible et versionnée pour la revue des dossiers.
- Prépare le terrain pour une gouvernance structurée avec validation humaine.

**Ce que le VHS ne fait pas :**

- Il ne remplace pas le jugement du gestionnaire ou de l'expert.
- Il ne détecte pas la fraude — il signale un état technique préoccupant.
- Il ne prend pas de décision contractuelle ou réglementaire.

> *IRIS propose un niveau d'attention. Le gestionnaire ou l'expert métier conserve la décision finale.*

La version `VHS_BALANCED_V3_CANDIDATE` est techniquement validée comme version candidate finale. Sa mise en production dans le cadre de la plateforme IRIS reste conditionnée à la **validation métier par BNA Assurances** et à la mise en place de la couche de gouvernance décrite dans ce document.

---

| Document lié | Contenu |
|---|---|
| `docs/vhs/vhs_business_explanation.md` | Explication métier détaillée (BNA-ready) |
| `docs/vhs/vhs_validation_summary.md` | Synthèse de validation technique |
| `docs/vhs/vhs_calculation_method.md` | Méthode de calcul |
| `docs/vhs/governance/vhs_human_in_the_loop_and_history_architecture.md` | Architecture de gouvernance |
| `docs/vhs/governance/vhs_governance_table_design.md` | Design des tables |
| `docs/vhs/governance/sql/001_create_vhs_governance_tables.sql` | DDL proposé |
| `docs/vhs/governance/vhs_governance_sql_validation_summary.md` | Synthèse validation DDL |
| `data/quality_reports/vhs/final/vhs_v3_audit_summary.md` | Rapport d'audit V3 |
| `notebooks/validation_vhs/01_validate_vhs_balanced_v3_candidate.ipynb` | Notebook de validation |

---

*Document créé dans le cadre du projet IRIS Auto Fraud Decision Platform — PFE 2026.*  
*Moteur VHS non modifié. Aucune écriture en base de données.*
