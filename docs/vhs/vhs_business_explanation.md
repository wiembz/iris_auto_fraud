# Explication métier du Vehicle Health Score (VHS)

> Document à destination de BNA Assurances et de l'encadrement académique.  
> Version : VHS_BALANCED_V3_CANDIDATE — Juillet 2026

---

## Objectif

Le **Vehicle Health Score (VHS)** est un indicateur d'aide à la décision qui reflète l'état technique d'un véhicule à partir des données d'inspection STAFFIM.

Il ne constitue **pas une accusation de fraude** et ne remplace pas le gestionnaire. Il aide à prioriser les dossiers, comprendre les points techniques relevés et situer l'état du véhicule dans le contexte d'un sinistre automobile.

---

## Pourquoi SHAP n'est pas utilisé

SHAP est utile pour expliquer des modèles prédictifs de machine learning. Le VHS n'est pas un modèle prédictif : il ne calcule pas une probabilité de fraude et ne repose pas sur une logique opaque.

Le VHS est transparent et déterministe. Il applique des règles explicites à des points de contrôle STAFFIM observables : observation initiale, lecture standardisée, sensibilité du point de contrôle, impact sur l'état du véhicule et limitation métier éventuelle du niveau final.

L'explication vient donc directement des points de contrôle observés. Cette méthode est plus adaptée à un usage métier assurantiel, car chaque résultat peut être relié à une observation concrète de la fiche véhicule.

---

## Traduction des codes techniques en langage métier

| Code technique | Libellé métier |
|---|---|
| OK | État satisfaisant |
| DEGRADE | État à surveiller |
| IMMOBILISE | Usage déconseillé |
| CRITIQUE | Examen prioritaire suggéré |
| WORN_STRONG | Intervention conseillée |
| BROKEN | Défaut confirmé |
| REPAIRED | Élément réparé |
| UNKNOWN | Information non exploitable |

Le backend conserve les codes techniques pour l'auditabilité. L'interface IRIS doit afficher les libellés métier aux utilisateurs non techniques.

---

## Fonctionnement métier

Chaque inspection produit des points de contrôle. Le VHS lit ces observations et calcule un indicateur d'état technique sur 100.

| Étape | Lecture métier |
|---|---|
| Observation STAFFIM | Valeur relevée sur un point de contrôle |
| Lecture standardisée | Élément conforme, usure observée, intervention conseillée ou défaut confirmé |
| Impact | Aucun, faible, moyen ou fort selon la sensibilité du point |
| Résultat | Niveau d'état technique et niveau d'attention proposé |

---

## Exemple de lecture métier

Le véhicule présente un indicateur d'état de 56/100. Les principaux points relevés concernent le freinage et la suspension. Ces observations justifient un état à surveiller, sans constituer une décision automatique. Le gestionnaire conserve la décision finale.

---

## Lecture recommandée dans IRIS

| Niveau d'attention proposé | Message utilisateur recommandé |
|---|---|
| État satisfaisant | Le véhicule ne présente pas de signal technique majeur dans les points analysés. |
| État à surveiller | Le véhicule présente plusieurs points techniques à surveiller. Une vérification complémentaire peut être utile. |
| Usage déconseillé | IRIS a relevé un point technique sensible. L'usage du véhicule est déconseillé sans vérification complémentaire. |
| Examen prioritaire suggéré | IRIS a relevé plusieurs signaux techniques importants. Un examen prioritaire du dossier est suggéré. |

---

## Gouvernance et limites

- Le VHS est un indicateur d'aide à l'analyse, non un verdict automatique.
- Un véhicule en mauvais état n'implique pas automatiquement une fraude.
- Les résultats doivent être interprétés dans le contexte du sinistre déclaré.
- Les seuils et impacts peuvent être ajustés après validation métier par BNA Assurances.

**Les éléments présentés constituent une aide à l'analyse. La décision finale reste sous la responsabilité du gestionnaire.**

---

*Document généré dans le cadre du projet IRIS Auto Fraud Decision Platform — PFE 2026.*

