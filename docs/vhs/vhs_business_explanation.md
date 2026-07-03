# Explication métier du Vehicle Health Score (VHS)

> Document à destination de BNA Assurances et de l'encadrement académique.
> Version : VHS_BALANCED_V3_CANDIDATE — Juillet 2026

---

## Objectif

Le **Vehicle Health Score (VHS)** est un indicateur d'aide à la décision
qui reflète l'état technique d'un véhicule à partir des données d'inspection STAFIM.

Il ne constitue **pas une accusation de fraude**. Il permet aux gestionnaires de
dossiers et aux équipes de prévention de la fraude de :

- prioriser les dossiers nécessitant une attention particulière ;
- comprendre l'état mécanique déclaré du véhicule au moment de l'inspection ;
- détecter des incohérences potentielles entre l'état du véhicule et la nature du
  sinistre déclaré.

---

## Source de données

Les données proviennent des rapports d'inspection **STAFIM**, intégrés dans le
Data Warehouse via la table `dwh.fact_inspection_checkpoint`.

Chaque inspection produit un ensemble de **points de contrôle** (checkpoints),
avec pour chacun une valeur observée (`valeur_controle`) et un commentaire
technicien (`staffim_comment`).

---

## Fonctionnement

### 1. Normalisation des statuts

Chaque valeur d'inspection est traduite en statut observé :

| Valeur STAFIM            | Statut observé  | Signification                        |
|--------------------------|-----------------|--------------------------------------|
| Défectueux               | BROKEN          | Défaut confirmé                      |
| Contrôle non OK          | BROKEN          | Défaut confirmé                      |
| Usé                      | WORN            | Usure normale                        |
| Intervention conseillée  | WORN            | Usure avec recommandation            |
| Usage déconseillé        | WORN_STRONG     | Usure importante — vigilance requise |
| Bon état / OK            | OK              | État satisfaisant                    |
| Remplacé / Réparé        | REPAIRED        | Intervention effectuée               |
| NON                      | non mappé       | Valeur ambiguë — voir note           |
| Proposition faite        | non mappé       | Valeur ambiguë — voir note           |

> **Note sur les valeurs ambiguës :** Les valeurs **NON** et **Proposition faite**
> ne sont pas automatiquement interprétées comme des défauts confirmés. Elles peuvent
> représenter une absence de contrôle, une recommandation préventive, ou un refus
> d'inspection. Les traiter comme des défauts (`BROKEN`) entraînerait une surestimation
> systématique de la dégradation et des décisions IMMOBILISE injustifiées.

---

### 2. Calcul du score

Chaque checkpoint est pondéré selon sa **criticité** définie dans le référentiel
`mart.dim_checkpoint` :

| Tier        | Composants concernés                               | Niveau de pénalité |
|-------------|----------------------------------------------------|--------------------|
| T1_CRITICAL | Freins, direction, éclairage, pneumatiques         | Élevé              |
| T2_CRITICAL | Moteur, refroidissement, batterie, étanchéité      | Moyen              |
| T3_IMPORTANT| Carrosserie, accessoires secondaires               | Faible             |

Le score final (0–100) est obtenu par soustraction de pénalités depuis 100.
Des **plafonds métier automatiques** s'appliquent :

| Condition                                   | Effet                  |
|---------------------------------------------|------------------------|
| Score ≤ 40                                  | Grade D automatique    |
| Checkpoint immobilisant BROKEN              | Décision IMMOBILISE    |
| Score ≤ 65 avec composant critique BROKEN   | Décision CRITIQUE      |

---

### 3. Grade de sécurité

| Grade | Plage de score | Signification                              |
|-------|----------------|--------------------------------------------|
| A     | > 85           | Bon état général                           |
| B     | 66 – 85        | État acceptable — surveillance recommandée |
| C     | 41 – 65        | État dégradé — intervention conseillée     |
| D     | ≤ 40           | État critique — attention requise          |

---

### 4. Décision proposée

| Décision   | Affichage métier     | Signification                                          |
|------------|----------------------|--------------------------------------------------------|
| OK         | OK                   | Aucun problème significatif détecté                    |
| DEGRADE    | Dégradé              | Dégradation notable — dossier à examiner               |
| IMMOBILISE | Usage déconseillé    | Point de contrôle critique BROKEN (ex. huile moteur)  |
| CRITIQUE   | Critique             | Score très bas — véhicule en mauvais état général      |

La décision **IMMOBILISE** (affichée *« Usage déconseillé »*) n'est déclenchée
que lorsqu'un checkpoint explicitement marqué `is_immobilizing = TRUE` dans le
référentiel présente un défaut confirmé (`BROKEN`). Dans la version actuelle,
seul le **niveau d'huile moteur** remplit cette condition.

---

## Gouvernance et limites

Le VHS est un **indicateur d'aide à la décision**, non un verdict automatique.

- La **décision finale** appartient au gestionnaire ou à l'expert métier.
- Les résultats doivent être interprétés dans le **contexte du sinistre déclaré**.
- Un véhicule en mauvais état (Grade D) n'implique pas automatiquement une fraude.
- Le VHS peut néanmoins signaler des **incohérences méritant une investigation**.
- La qualité des résultats dépend de la **complétude des rapports STAFIM**.
- Les seuils et pénalités peuvent être ajustés après validation par BNA Assurances.

---

*Document généré dans le cadre du projet IRIS Auto Fraud Decision Platform — PFE 2026.*
