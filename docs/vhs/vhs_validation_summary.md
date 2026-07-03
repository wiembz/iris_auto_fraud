# Synthèse de validation — Vehicle Health Score V3

> Document de référence pour la version candidate **VHS_BALANCED_V3_CANDIDATE**
> À destination de BNA Assurances et de l'encadrement académique.

---

## Version retenue

| Paramètre              | Valeur                                          |
|------------------------|-------------------------------------------------|
| Nom de version         | VHS_BALANCED_V3_CANDIDATE                       |
| Script actif           | `etl/mart/compute_vhs_v3_candidate.py`          |
| Run final validé       | VHS_BALANCED_V3_CANDIDATE_20260703_181257       |
| Date de validation     | 2026-07-03                                      |

---

## Distribution finale des décisions

| Décision   | Nombre | Signification                         |
|------------|--------|---------------------------------------|
| OK         | 89     | Aucun problème significatif           |
| DEGRADE    | 133    | Dégradation notable                   |
| IMMOBILISE | 13     | Usage déconseillé (huile moteur BROKEN)|
| CRITIQUE   | 51     | Score très bas                        |
| **Total**  | **286**|                                       |

## Distribution finale des grades de sécurité

| Grade | Nombre |
|-------|--------|
| A     | 95     |
| B     | 11     |
| C     | 129    |
| D     | 51     |

---

## Résultats des audits qualité

| Contrôle de qualité                     | Résultat   |
|-----------------------------------------|------------|
| Valeurs PROPOSITION FAITE → BROKEN      | 0 cas      |
| Valeurs NON → BROKEN                    | 0 cas      |
| Valeurs ambiguës non mappées comme défauts | Aucune  |
| Anomalies de mapping détectées          | 0          |

---

## Correction du référentiel is_immobilizing

Suite à l'audit des 25 cas IMMOBILISE initiaux de la V3, il a été constaté que
5 checkpoints sous-capot (courroies, liquide de refroidissement, étanchéité,
batterie, huile moteur) déclenchaient IMMOBILISE via `is_immobilizing = TRUE`.

**Décision métier :** seul le niveau d'huile moteur justifie l'IMMOBILISE.
Les 4 autres checkpoints ont été mis à jour : `is_immobilizing = FALSE`,
`is_critical_functional = TRUE`. Ils déclenchent désormais DEGRADE via le
plafond CRITICAL_FUNCTIONAL (seuil 65).

| Indicateur   | Avant correction | Après correction | Variation |
|--------------|-----------------|-----------------|-----------|
| IMMOBILISE   | 25              | 13              | -12       |
| DEGRADE      | 121             | 133             | +12       |
| CRITIQUE     | 51              | 51              | stable    |
| Grade D      | 51              | 51              | stable    |

- **12 cas** ont évolué de IMMOBILISE vers DEGRADE (comportement attendu).
- **0 cas** n'ont évolué de IMMOBILISE vers OK (aucune correction excessive).
- Les 4 checkpoints corrigés restent détectés via le plafond CRITIQUE (score ≤ 65
  avec composant critique BROKEN).

---

## Conclusion

**La version VHS_BALANCED_V3_CANDIDATE est retenue comme version candidate finale
techniquement validée, sous réserve de validation métier par BNA Assurances.**

Les règles de calcul, les seuils et les pénalités peuvent être ajustés sur demande
après revue avec les équipes métier de BNA Assurances.

---

*Document généré dans le cadre du projet IRIS Auto Fraud Decision Platform — PFE 2026.*
