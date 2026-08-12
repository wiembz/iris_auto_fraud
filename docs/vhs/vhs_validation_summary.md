# Synthèse de validation — Vehicle Health Score V4

> Document de référence pour la version candidate **VHS_BALANCED_V4_CANDIDATE**
> À destination de BNA Assurances et de l'encadrement académique.

---

## Version retenue

| Paramètre | Valeur |
|---|---|
| Nom de version | VHS_BALANCED_V4_CANDIDATE |
| Script actif | `etl/mart/compute_vhs_v4_candidate.py` |
| Run de référence | VHS_BALANCED_V4_CANDIDATE_20260807_115527 |
| Date de validation | 2026-08-07 |

---

## Pourquoi V4 : correction d'une saturation d'échelle incohérente

V3 pouvait cumuler sans plafond les pénalités de plusieurs points de contrôle
appartenant au **même système fonctionnel** (ex. les 4 points de contrôle du
système de freinage). Un véhicule pouvait ainsi atteindre un score de 0/100
non pas parce qu'il était globalement hors d'usage, mais parce qu'un seul
système sur-pénalisait le score par double comptage.

Comparaison sur le même jeu de données (284 inspections, run du 2026-07-13) :

| Indicateur | V3 | V4 |
|---|---:|---:|
| Véhicules à score 0/100 | 21 | 4 |
| ...dont décision CRITIQUE | 14 | 3 |
| ...dont décision IMMOBILISE | 2 | 1 |
| ...dont décision **DEGRADE** (incohérent : score plancher mais libellé "roulable") | **5** | **0** |
| Score moyen | 56,4 | 66,0 |

**L'incohérence corrigée** : en V3, 5 véhicules sur les 21 à score 0 affichaient
la décision « DEGRADE » (dégradation notable, mais implicitement roulable) —
un score au plancher absolu ne peut pas cohabiter avec un libellé métier qui
sous-entend un usage encore possible. En V4, plafonner les pénalités par
système élimine cette saturation artificielle : les 4 véhicules qui atteignent
encore 0/100 le font pour des raisons réellement globales, et sont
systématiquement classés CRITIQUE ou IMMOBILISE — jamais DEGRADE.

**Correction technique** : plafond de pénalité par système fonctionnel
(freinage, suspension, transmission, moteur, carrosserie...), pondération
WORN_STRONG revue (`penalty_worn x 0.6` au lieu du midpoint worn/broken), et
score plancher de 5 points pour tout véhicule encore roulable (`is_drivable`).
Le grade de sécurité et la logique de décision (OK/DEGRADE/IMMOBILISE/CRITIQUE)
restent inchangés par rapport à V3 — seul le calcul du score continu change.

---

## Distribution finale des niveaux d'attention (run du 2026-08-07)

| Code technique | Libellé métier | Nombre | Signification |
|---|---|---:|---|
| OK | État satisfaisant | 93 | Aucun signal technique majeur |
| DEGRADE | État à surveiller | 116 | Dégradation notable ou points à vérifier |
| IMMOBILISE | Usage déconseillé | 25 | Point technique sensible, usage déconseillé sans vérification |
| CRITIQUE | Examen prioritaire suggéré | 50 | Plusieurs signaux techniques importants |
| **Total** |  | **284** |  |

## Distribution finale des niveaux d'état technique

| Niveau | Libellé métier | Nombre |
|---|---|---:|
| A | Aucun signal technique majeur | 96 |
| B | Quelques points à surveiller | 11 |
| C | Dégradation technique notable | 127 |
| D | Situation technique sensible | 50 |

---

## Résultats des audits qualité

| Contrôle de qualité | Résultat |
|---|---|
| Valeurs PROPOSITION FAITE -> Défaut confirmé | 0 cas |
| Valeurs NON -> Défaut confirmé | 0 cas |
| Valeurs ambiguës non mappées comme défauts | Aucune |
| Anomalies de mapping détectées | 0 |
| Cohérence score 0 / décision (score plancher ⇒ jamais DEGRADE) | 4/4 (100 %) |

---

## Explicabilité métier

Le VHS est explicable par contributions de points de contrôle. Aucun SHAP n'est utilisé, car le VHS est déterministe et ne correspond pas à un modèle machine learning.

Chaque niveau d'attention peut être retracé vers des points de contrôle STAFFIM observés : observation initiale, lecture métier, sensibilité du point et impact sur l'état du véhicule.

Les codes techniques sont traduits en libellés métier pour les utilisateurs non techniques. Le libellé recommandé pour `IMMOBILISE` est **Usage déconseillé**.

Le score VHS est donc explicable sans recourir à une méthode d'explicabilité de modèle de type SHAP.

---

## Historique : correction du référentiel des points sensibles (V2 → V3)

Avant la correction de saturation V3 → V4 ci-dessus, une première itération avait
déjà corrigé un défaut de gouvernance des points sensibles. Suite à l'audit des
25 cas initiaux classés Usage déconseillé (V2), il a été constaté que plusieurs
points sous-capot déclenchaient trop fortement le niveau d'attention. La
décision métier retenue a limité ce niveau au cas où le niveau d'huile moteur
présente un défaut confirmé.

| Indicateur | Avant correction (V2) | Après correction (V3) | Variation |
|---|---:|---:|---:|
| Usage déconseillé | 25 | 13 | -12 |
| État à surveiller | 121 | 133 | +12 |

- 12 cas ont évolué de Usage déconseillé vers État à surveiller.
- Aucun cas n'a évolué vers État satisfaisant à cause de cette correction.

*(Les comptages IMMOBILISE ont ensuite évolué au fil des runs à mesure que de
nouvelles inspections STAFFIM sont arrivées dans le DWH — les chiffres du run
V4 du 2026-08-07 ci-dessus, incluant 25 IMMOBILISE, reflètent le périmètre
actuel de 284 inspections, pas une régression de la correction V2→V3.)*

---

## Conclusion

**La version VHS_BALANCED_V4_CANDIDATE est retenue comme version candidate finale techniquement validée, sous réserve de validation métier par BNA Assurances.** Elle succède à V3 (elle-même retenue candidate finale le 2026-07-03) en corrigeant une saturation d'échelle démontrée par comparaison directe sur le même jeu de données.

Les règles de calcul, les seuils et les impacts peuvent être ajustés après revue avec les équipes métier de BNA Assurances.

**Les éléments présentés constituent une aide à l'analyse. La décision finale reste sous la responsabilité du gestionnaire.**

---

*Document généré dans le cadre du projet IRIS Auto Fraud Decision Platform — PFE 2026.*
