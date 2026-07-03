# VHS — Vehicle Health Score : Méthode de calcul

> **Version candidate :** `VHS_BALANCED_V3_CANDIDATE`
>
> Cette version est la recommandation finale issue des audits STAFFIM.
> Elle doit être validée métier par BNA Assurances avant d'être promue en version officielle.
>
> **Statut :** Exploratoire / candidat — ne modifie pas `VHS_BALANCED_V2`.

---

## 1. Objectif du VHS

Le **VHS — Vehicle Health Score** synthétise l'état technique d'un véhicule à partir de la fiche d'inspection STAFFIM.

Il ne mesure pas directement la fraude.
Il ne remplace pas le gestionnaire.
Il sert à donner une lecture claire de l'état du véhicule dans le cadre de l'analyse d'un dossier sinistre automobile.

Questions auxquelles le VHS répond :

```
Le véhicule est-il globalement en bon état ?
Présente-t-il des anomalies techniques ?
Ces anomalies touchent-elles des organes de sécurité ?
L'état du véhicule nécessite-t-il une vérification renforcée ?
L'état technique peut-il influencer l'analyse du dossier sinistre ?
```

Le VHS doit rester :

```
explicable
auditable
versionné
compréhensible métier
non basé sur une boîte noire
```

---

## 2. Tables utilisées

### 2.1 `dwh.fact_inspection_vehicule`

Une ligne par inspection véhicule.

| Champ | Description |
|---|---|
| `inspection_key` | Clé unique de l'inspection |
| `immatriculation_norm` | Immatriculation normalisée |
| `vehicule_sk` | Clé dimension véhicule |
| `date_inspection_sk` | Clé dimension date |
| `kilometrage` | Kilométrage déclaré |
| `nb_anomalies_total` | Nombre total d'anomalies |
| `nb_anomalies_critiques` | Nombre d'anomalies critiques |

### 2.2 `dwh.fact_inspection_checkpoint`

Une ligne par checkpoint contrôlé.

| Champ | Description |
|---|---|
| `inspection_key` | Clé de l'inspection |
| `checkpoint_code` | Code du point de contrôle |
| `checkpoint_libelle` | Libellé du point de contrôle |
| `zone_controle` | Zone de contrôle (ex. ENTRETIEN) |
| `valeur_controle` | Valeur observée par l'inspecteur |
| `commentaire_zone` | Commentaire libre de l'inspecteur |
| `est_anomalie` | Anomalie détectée (bool) |
| `est_anomalie_critique` | Anomalie critique (bool) |
| `est_controle_renseigne` | Contrôle effectivement renseigné (bool) |

### 2.3 `mart.dim_checkpoint`

Classification métier des checkpoints.

| Champ | Description |
|---|---|
| `checkpoint_code` | Code du point de contrôle |
| `checkpoint_libelle` | Libellé |
| `zone_controle` | Zone |
| `tier` | Famille de criticité |
| `is_vhs_scored` | Inclus dans le score VHS |
| `is_vital` | Organe vital |
| `is_important` | Organe important |
| `is_critical_functional` | Fonctionnel critique |
| `is_immobilizing` | Peut immobiliser le véhicule |
| `penalty_worn` | Pénalité état WORN |
| `penalty_broken` | Pénalité état BROKEN |

### Tables de sortie

```
mart.fact_vhs_score
mart.fact_vhs_penalty_detail
```

---

## 3. Principe général du calcul

Le score commence à **100 points**, puis des pénalités sont déduites selon :

- l'état observé de chaque checkpoint
- la criticité métier du checkpoint
- le kilométrage
- les règles de sécurité
- les hard caps métier

```
vhs_raw_score   = 100 - total_penalty_checkpoints
vhs_before_cap  = vhs_raw_score - kilometrage_penalty
vhs_final_score = application éventuelle d'un hard cap
```

---

## 4. Statuts VHS

| Statut | Sens métier | Effet |
|---|---|---|
| `OK` | Contrôle conforme | Pas de pénalité |
| `WORN` | Anomalie simple / usure | Pénalité légère |
| `WORN_STRONG` | Anomalie forte, pas défaut cassé confirmé | Pénalité intermédiaire |
| `BROKEN` | Défaut confirmé | Pénalité forte |
| `REPAIRED` | Réparation effectuée | Pas de pénalité, conservé pour traçabilité |
| `UNKNOWN` | Non renseigné ou non interprétable | Pas de pénalité |

---

## 5. Interprétation finale des valeurs STAFFIM

### 5.1 Valeurs conformes → `OK`

```
Bon
Contrôle OK
OUI
```

```
pénalité = 0
state_value = 1.0
```

### 5.2 Défauts confirmés → `BROKEN`

```
Défectueux
Contrôle non OK
```

Ces valeurs indiquent explicitement un défaut ou un contrôle échoué.

```
pénalité = penalty_broken
state_value = 0.0
```

### 5.3 Valeurs de recommandation ou d'action

```
Intervention conseillée
PROPOSITION FAITE
Proposition faite
```

Ces valeurs ne doivent **pas** devenir `BROKEN` automatiquement. Elles indiquent une intervention recommandée ou une proposition d'action.

```
est_anomalie = true  AND  est_anomalie_critique = false  →  WORN
est_anomalie_critique = true                             →  WORN_STRONG
```

### 5.4 Valeur `NON`

La valeur `NON` a été auditée séparément (notebook `04_staffim_comment_analysis_for_vhs.ipynb`).

**Résultats de l'audit (run `VHS_BALANCED_V2_20260630_133318`) :**

- 149 lignes, 73 inspections, uniquement dans la zone `ENTRETIEN`
- 0 cas avec `est_anomalie_critique = true`
- 0 hard-cap triggers
- Apparaît dans certaines inspections `CRITIQUE` / `IMMOBILISE`, mais n'en est pas la cause directe (`is_hard_cap_trigger = false` systématiquement)

**Règle finale :**

```
NON + est_anomalie = true  AND  est_anomalie_critique = false  →  WORN
NON + est_anomalie_critique = true                             →  WORN_STRONG  (règle future prudente)
NON  ≠  BROKEN automatiquement
```

> Bien qu'aucun cas `NON + est_anomalie_critique=true` ne soit observé dans les données actuelles,
> cette combinaison est incluse pour couvrir les données futures. Elle doit être interprétée
> comme `WORN_STRONG` plutôt que `BROKEN`, car `NON` exprime une réponse négative ou une
> non-conformité, mais ne confirme pas explicitement qu'un composant est cassé.

### 5.5 Réparation effectuée → `REPAIRED`

```
Réparation effectuée suite à l'accord client
```

```
pénalité = 0
conservé pour traçabilité
```

### 5.6 Contrôle non renseigné → `UNKNOWN`

Si `est_controle_renseigne = false` ou si la valeur est absente / non exploitable :

```
pénalité = 0
exclu des sous-scores
```

---

## 6. Table finale des mappings

| `valeur_controle` | `est_anomalie` | `est_anomalie_critique` | Statut recommandé | Justification |
|---|:---:|:---:|---|---|
| `Bon` | false | false | `OK` | Conformité confirmée |
| `Contrôle OK` | false | false | `OK` | Contrôle validé |
| `OUI` | false | false | `OK` | Réponse positive / conforme |
| `Défectueux` | true | true/false | `BROKEN` | Défaut explicite |
| `Contrôle non OK` | true | true/false | `BROKEN` | Contrôle explicitement échoué |
| `Intervention conseillée` | true | false | `WORN` | Intervention recommandée non critique |
| `Intervention conseillée` | true | true | `WORN_STRONG` | Recommandation forte, pas forcément cassé |
| `PROPOSITION FAITE` | true | false | `WORN` | Proposition d'action non critique |
| `PROPOSITION FAITE` | true | true | `WORN_STRONG` | Proposition forte, pas défaut confirmé |
| `Proposition faite` | true | false | `WORN` | Proposition d'action non critique |
| `Proposition faite` | true | true | `WORN_STRONG` | Proposition forte, pas défaut confirmé |
| `NON` | true | false | `WORN` | Réponse négative / anomalie simple |
| `NON` | true | true | `WORN_STRONG` | Règle future prudente |
| `NON` | false | false | `UNKNOWN` | Réponse négative sans anomalie confirmée |
| Réparation effectuée | any | any | `REPAIRED` | Réparation réalisée, traçabilité |
| Non renseigné | false | false | `UNKNOWN` | Information insuffisante |

---

## 7. Familles de criticité des checkpoints (`tier`)

| Tier | Rôle |
|---|---|
| `T1_VITAL` | Sécurité majeure : freins, liquide de frein, direction |
| `T1_IMPORTANT` | Sécurité importante : pneus, amortisseurs |
| `T2_CRITICAL` | Fonctionnel critique : huile, refroidissement, batterie, courroies |
| `T2_NORMAL` | Fonctionnel normal : visibilité, éclairage, échappement, sous caisse |
| `T3_COSMETIC` | Confort / faible impact |
| `UNKNOWN_REVIEW` | Non scoré / audit seulement |

---

## 8. Grille finale des pénalités

| Tier | WORN | WORN_STRONG | BROKEN |
|---|---:|---:|---:|
| `T1_VITAL` | 10 | 17.5 | 25 |
| `T1_IMPORTANT` | 6 | 10.5 | 15 |
| `T2_CRITICAL` | 5 | 8.5 | 12 |
| `T2_NORMAL` | 3 | 5.5 | 8 |
| `T3_COSMETIC` | 1 | 2.5 | 4 |
| `UNKNOWN_REVIEW` | 0 | 0 | 0 |

```
WORN_STRONG = (penalty_worn + penalty_broken) / 2
```

---

## 9. Liste finale recommandée des checkpoints

### 9.1 Tour du véhicule

| Checkpoint | Tier | WORN | WORN_STRONG | BROKEN |
|---|---|---:|---:|---:|
| Plaques de police | `T3_COSMETIC` | 1 | 2.5 | 4 |
| Vitres et pare-brise | `T2_NORMAL` | 3 | 5.5 | 8 |
| Balais essuie-glace | `T2_NORMAL` | 3 | 5.5 | 8 |
| Éclairage avant | `T2_NORMAL` | 3 | 5.5 | 8 |
| Éclairage arrière | `T2_NORMAL` | 3 | 5.5 | 8 |
| Rétroviseur droit | `T2_NORMAL` | 3 | 5.5 | 8 |
| Rétroviseur gauche | `T2_NORMAL` | 3 | 5.5 | 8 |
| Pneus avant | `T1_IMPORTANT` | 6 | 10.5 | 15 |
| Pneus arrière | `T1_IMPORTANT` | 6 | 10.5 | 15 |

### 9.2 Dans le véhicule

| Checkpoint | Tier | WORN | WORN_STRONG | BROKEN |
|---|---|---:|---:|---:|
| Contrôle état balais essuie-vitres AV | `T2_NORMAL` | 3 | 5.5 | 8 |
| Contrôle état balais essuie-vitres AR | `T2_NORMAL` | 3 | 5.5 | 8 |
| Contrôle lève-vitre AV | `T3_COSMETIC` | 1 | 2.5 | 4 |
| Contrôle lève-vitre AR | `T3_COSMETIC` | 1 | 2.5 | 4 |
| Contrôle feux éclairages AV | `T2_NORMAL` | 3 | 5.5 | 8 |
| Contrôle feux éclairages AR | `T2_NORMAL` | 3 | 5.5 | 8 |
| Contrôle feux de signalisation AV | `T2_CRITICAL` | 5 | 8.5 | 12 |
| Contrôle feux de signalisation AR | `T2_CRITICAL` | 5 | 8.5 | 12 |
| Contrôle avertisseur sonore | `T2_NORMAL` | 3 | 5.5 | 8 |

### 9.3 Sous le capot

| Checkpoint | Tier | WORN | WORN_STRONG | BROKEN |
|---|---|---:|---:|---:|
| Contrôle batterie | `T2_CRITICAL` | 5 | 8.5 | 12 |
| Contrôle niveau huile moteur | `T2_CRITICAL` | 5 | 8.5 | 12 |
| Contrôle niveau liquide refroidissement | `T2_CRITICAL` | 5 | 8.5 | 12 |
| Contrôle niveau liquide de frein | `T1_VITAL` | 10 | 17.5 | 25 |
| Contrôle durits de radiateur | `T2_CRITICAL` | 5 | 8.5 | 12 |
| Contrôle état des courroies d'accessoires | `T2_CRITICAL` | 5 | 8.5 | 12 |

### 9.4 Sous le véhicule

| Checkpoint | Tier | WORN | WORN_STRONG | BROKEN |
|---|---|---:|---:|---:|
| Contrôle plaquettes freins AV | `T1_VITAL` | 10 | 17.5 | 25 |
| Contrôle disques AV | `T1_VITAL` | 10 | 17.5 | 25 |
| Contrôle étriers | `T1_VITAL` | 10 | 17.5 | 25 |
| Contrôle plaquettes freins AR | `T1_VITAL` | 10 | 17.5 | 25 |
| Contrôle disques AR | `T1_VITAL` | 10 | 17.5 | 25 |
| Contrôle étanchéité amortisseurs AV | `T1_IMPORTANT` | 6 | 10.5 | 15 |
| Contrôle étanchéité amortisseurs AR | `T1_IMPORTANT` | 6 | 10.5 | 15 |
| Contrôle gaine transmissions / rotules / crémaillère | `T1_VITAL` | 10 | 17.5 | 25 |
| Contrôle état pneumatiques AV et AR | `UNKNOWN_REVIEW` | 0 | 0 | 0 |
| Contrôle roue de secours | `UNKNOWN_REVIEW` | 0 | 0 | 0 |
| Contrôle étanchéité tous fluides | `T2_CRITICAL` | 5 | 8.5 | 12 |
| Contrôle état sous caisse | `T2_NORMAL` | 3 | 5.5 | 8 |
| Contrôle ligne d'échappement | `T2_NORMAL` | 3 | 5.5 | 8 |

### 9.5 Autres prestations / entretien

| Checkpoint | Tier | WORN | WORN_STRONG | BROKEN |
|---|---|---:|---:|---:|
| Opération d'entretien | `UNKNOWN_REVIEW` | 0 | 0 | 0 |
| Contrôle filtre à air | `T3_COSMETIC` | 1 | 2.5 | 4 |
| Contrôle filtre d'habitacle | `T3_COSMETIC` | 1 | 2.5 | 4 |
| Contrôle bougies d'allumage | `T2_NORMAL` | 3 | 5.5 | 8 |
| Courroie de distribution | `T2_CRITICAL` | 5 | 8.5 | 12 |
| Fonctionnement climatisation | `T3_COSMETIC` | 1 | 2.5 | 4 |

---

## 10. Résumé des familles

| Tier | Nombre | Rôle |
|---|---:|---|
| `T1_VITAL` | 7 | Sécurité majeure : freins, liquide de frein, direction |
| `T1_IMPORTANT` | 4 | Sécurité importante : pneus, amortisseurs |
| `T2_CRITICAL` | 9 | Fonctionnel critique : huile, refroidissement, batterie, courroies |
| `T2_NORMAL` | 11 | Fonctionnel normal : visibilité, éclairage, échappement, sous caisse |
| `T3_COSMETIC` | 6 | Confort / faible impact |
| `UNKNOWN_REVIEW` | 3 | Non scoré / audit seulement |

**Total : 7 + 4 + 9 + 11 + 6 + 3 = 40 checkpoints**

> Selon l'extraction STAFFIM exacte, le total peut être 40 ou 43 selon que certains libellés sont séparés ou regroupés. La table `mart.dim_checkpoint` reste la référence finale.

---

## 11. Calcul de la pénalité checkpoint

```
OK           → pénalité = 0
WORN         → pénalité = penalty_worn
WORN_STRONG  → pénalité = (penalty_worn + penalty_broken) / 2
BROKEN       → pénalité = penalty_broken
REPAIRED     → pénalité = 0
UNKNOWN      → pénalité = 0

total_penalty_checkpoints = somme des pénalités de tous les checkpoints scorés
```

---

## 12. Calcul du score brut

```
vhs_raw_score = max(0, 100 - total_penalty_checkpoints)
```

Exemple :

```
total_penalty_checkpoints = 32
vhs_raw_score = 100 - 32 = 68
```

---

## 13. Pénalité kilométrage

Le kilométrage est un signal d'usure, mais ne rend pas un véhicule critique seul.

| Kilométrage | Pénalité |
|---:|---:|
| Absent / invalide | 1 |
| < 120 000 km | 0 |
| ≥ 120 000 km | 1 |
| ≥ 180 000 km | 2.5 |
| ≥ 250 000 km | 4 |
| ≥ 350 000 km | 6 |

```
vhs_before_cap = max(0, vhs_raw_score - kilometrage_penalty)
```

Exemple :

```
vhs_raw_score    = 68
kilometrage      = 259 000 km
km_penalty       = 4
vhs_before_cap   = 68 - 4 = 64
```

---

## 14. Calcul du grade sécurité

Le grade sécurité repose sur les checkpoints `T1`.

### Grade A

```
Aucune anomalie T1 (aucun T1 WORN, WORN_STRONG ou BROKEN)
→ état sécurité satisfaisant
```

### Grade B

```
Au moins 1 T1 WORN ou WORN_STRONG (sans condition Grade C ou D)
→ élément de sécurité à surveiller
```

### Grade C

```
Au moins 1 T1_VITAL WORN_STRONG
OU au moins 1 T1_IMPORTANT BROKEN
OU au moins 4 anomalies T1 de type WORN ou WORN_STRONG
→ dégradation significative, vérification conseillée
```

### Grade D

```
Au moins 1 T1_VITAL BROKEN
OU au moins 3 T1_IMPORTANT BROKEN
→ défaut de sécurité majeur, examen prioritaire suggéré
```

---

## 15. Drivabilité / usage déconseillé

```
si un checkpoint is_immobilizing = true est BROKEN
→ is_drivable = false
→ Affichage recommandé : "Usage déconseillé"
```

> "Véhicule immobilisé" est évité car un véhicule peut rouler jusqu'au centre STAFFIM tout en présentant un défaut justifiant une vérification urgente.

---

## 16. Décision métier finale

| Priorité | Condition | Décision |
|---:|---|---|
| 1 | `safety_grade = D` | `CRITIQUE` |
| 2 | `is_drivable = false` | `IMMOBILISE` *(affichage : Usage déconseillé)* |
| 3 | `safety_grade = C` | `DEGRADE` |
| 4 | `has_critical_functional = true` | `DEGRADE` |
| 5 | `vhs_before_cap < 70` | `DEGRADE` |
| 6 | sinon | `OK` |

---

## 17. Hard caps

| Condition | Hard cap | Score maximum |
|---|---|---:|
| Grade D | `GRADE_D` | 40 |
| Usage déconseillé / non drivable | `IMMOBILIZED` | 50 |
| Grade C | `GRADE_C` | 65 |
| Défaut fonctionnel critique | `CRITICAL_FUNCTIONAL` | 65 |

```
si hard_cap existe :
    vhs_final_score = min(vhs_before_cap, cap_value)
sinon :
    vhs_final_score = vhs_before_cap
```

---

## 18. Sous-scores

Les `state_value` utilisées :

```
OK           = 1.0
WORN         = 0.5
WORN_STRONG  = 0.25
BROKEN       = 0.0
```

`REPAIRED` et `UNKNOWN` sont exclus des moyennes.

### Safety score

```
Basé sur : T1_VITAL + T1_IMPORTANT
safety_score = moyenne(state_value des checkpoints T1) × 100
```

### Functional score

```
Basé sur : T2_CRITICAL + T2_NORMAL
functional_score = moyenne(state_value des checkpoints T2) × 100
```

### Cosmetic score

```
Basé sur : T3_COSMETIC
cosmetic_score = moyenne(state_value des checkpoints T3) × 100
```

---

## 19. Rôle des commentaires STAFFIM

Les commentaires ne modifient **pas** automatiquement le score.

**Utiles pour :**

```
audit
explication
preuve complémentaire
revue humaine
analyse future
```

**Ils ne doivent pas :**

```
remplacer valeur_controle
remplacer est_anomalie
déclencher BROKEN seuls
déclencher CRITIQUE seuls
modifier le score sans validation métier
```

Dans une évolution future, un module NLP peut aider à interpréter les commentaires, mais uniquement comme aide à l'analyse — pas comme décideur automatique.

---

## 20. Diagrammes Mermaid

Les diagrammes sont disponibles dans :

- [docs/diagrams/vhs_calculation_flow.mmd](../diagrams/vhs_calculation_flow.mmd) — flux complet de calcul
- [docs/diagrams/vhs_mapping_rules.mmd](../diagrams/vhs_mapping_rules.mmd) — règles de mapping résumées

---

## 21. Phrase de synthèse

> Le VHS final recommandé repose sur une logique métier explicable. Chaque checkpoint STAFFIM est classé dans une famille de criticité, puis une pénalité est appliquée selon l'état observé : WORN, WORN_STRONG ou BROKEN. Les défauts confirmés, comme "Défectueux" ou "Contrôle non OK", sont traités comme BROKEN. Les valeurs ambiguës ou de recommandation, comme "Intervention conseillée", "PROPOSITION FAITE" et "NON", sont traitées avec prudence afin d'éviter un surclassement automatique. Elles deviennent WORN lorsqu'il s'agit d'une anomalie simple et WORN_STRONG lorsqu'une anomalie critique est signalée. Le score est ensuite ajusté légèrement par le kilométrage, puis encadré par des règles de grade sécurité, de décision métier et de hard caps. Cette approche permet de conserver un score clair, traçable et justifiable, adapté à une plateforme d'aide à la décision.

---

*Document généré dans le cadre du projet IRIS Auto Fraud Decision Platform.*
*Notebook d'analyse : `notebooks/04_staffim_comment_analysis_for_vhs.ipynb`*
*Run de référence : `VHS_BALANCED_V2_20260630_133318`*
*Date : 2026-07-02*
