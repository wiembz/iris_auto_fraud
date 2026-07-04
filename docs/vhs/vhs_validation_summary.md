# Synthèse de validation — Vehicle Health Score V3

> Document de référence pour la version candidate **VHS_BALANCED_V3_CANDIDATE**  
> À destination de BNA Assurances et de l'encadrement académique.

---

## Version retenue

| Paramètre | Valeur |
|---|---|
| Nom de version | VHS_BALANCED_V3_CANDIDATE |
| Script actif | `etl/mart/compute_vhs_v3_candidate.py` |
| Run final validé | VHS_BALANCED_V3_CANDIDATE_20260703_181257 |
| Date de validation | 2026-07-03 |

---

## Distribution finale des niveaux d'attention

| Code technique | Libellé métier | Nombre | Signification |
|---|---|---:|---|
| OK | État satisfaisant | 89 | Aucun signal technique majeur |
| DEGRADE | État à surveiller | 133 | Dégradation notable ou points à vérifier |
| IMMOBILISE | Usage déconseillé | 13 | Point technique sensible, usage déconseillé sans vérification |
| CRITIQUE | Examen prioritaire suggéré | 51 | Plusieurs signaux techniques importants |
| **Total** |  | **286** |  |

## Distribution finale des niveaux d'état technique

| Niveau | Libellé métier | Nombre |
|---|---|---:|
| A | Aucun signal technique majeur | 95 |
| B | Quelques points à surveiller | 11 |
| C | Dégradation technique notable | 129 |
| D | Situation technique sensible | 51 |

---

## Résultats des audits qualité

| Contrôle de qualité | Résultat |
|---|---|
| Valeurs PROPOSITION FAITE -> Défaut confirmé | 0 cas |
| Valeurs NON -> Défaut confirmé | 0 cas |
| Valeurs ambiguës non mappées comme défauts | Aucune |
| Anomalies de mapping détectées | 0 |

---

## Explicabilité métier

Le VHS est explicable par contributions de points de contrôle. Aucun SHAP n'est utilisé, car le VHS est déterministe et ne correspond pas à un modèle machine learning.

Chaque niveau d'attention peut être retracé vers des points de contrôle STAFFIM observés : observation initiale, lecture métier, sensibilité du point et impact sur l'état du véhicule.

Les codes techniques sont traduits en libellés métier pour les utilisateurs non techniques. Le libellé recommandé pour `IMMOBILISE` est **Usage déconseillé**.

Le score VHS est donc explicable sans recourir à une méthode d'explicabilité de modèle de type SHAP.

---

## Correction du référentiel des points sensibles

Suite à l'audit des 25 cas initiaux classés Usage déconseillé, il a été constaté que plusieurs points sous-capot déclenchaient trop fortement le niveau d'attention. La décision métier retenue limite ce niveau au cas où le niveau d'huile moteur présente un défaut confirmé.

| Indicateur | Avant correction | Après correction | Variation |
|---|---:|---:|---:|
| Usage déconseillé | 25 | 13 | -12 |
| État à surveiller | 121 | 133 | +12 |
| Examen prioritaire suggéré | 51 | 51 | stable |
| Niveau D | 51 | 51 | stable |

- 12 cas ont évolué de Usage déconseillé vers État à surveiller.
- Aucun cas n'a évolué vers État satisfaisant à cause de cette correction.
- Les points corrigés restent visibles comme signaux techniques importants.

---

## Conclusion

**La version VHS_BALANCED_V3_CANDIDATE est retenue comme version candidate finale techniquement validée, sous réserve de validation métier par BNA Assurances.**

Les règles de calcul, les seuils et les impacts peuvent être ajustés après revue avec les équipes métier de BNA Assurances.

**Les éléments présentés constituent une aide à l'analyse. La décision finale reste sous la responsabilité du gestionnaire.**

---

*Document généré dans le cadre du projet IRIS Auto Fraud Decision Platform — PFE 2026.*

