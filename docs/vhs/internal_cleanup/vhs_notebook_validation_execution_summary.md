# VHS Validation Notebook — Résumé d'exécution

> **Date de génération :** 2026-07-04 08:58 UTC
> **Notebook :** `notebooks/validation_vhs/01_validate_vhs_balanced_v3_candidate.ipynb`
> **Script actif :** `etl/mart/compute_vhs_v3_candidate.py`
> **Statut global :** PASS

---

## Identification du run

| Paramètre | Valeur |
|---|---|
| Profil | `VHS_BALANCED_V3_CANDIDATE` |
| Run de référence | `VHS_BALANCED_V3_CANDIDATE_20260703_181530` |
| Inspections scorées | 286 |
| Détails de points de contrôle | 9 724 |

---

## Distributions validées

| Code technique | Libellé métier | Nombre |
|---|---|---:|
| OK | État satisfaisant | 89 |
| DEGRADE | État à surveiller | 133 |
| IMMOBILISE | Usage déconseillé | 13 |
| CRITIQUE | Examen prioritaire suggéré | 51 |

---

## Explicabilité non technique

| Élément | Résultat |
|---|---|
| SHAP utilisé | Non |
| Raison | VHS est déterministe, pas un modèle machine learning |
| Méthode d'explication | Contribution de points de contrôle STAFFIM et mapping de libellés métier |
| Libellés prêts pour interface | Oui |
| Exemples multiples explicables | PASS |

Le VHS est expliqué par des éléments observables de la fiche STAFFIM, ce qui le rend plus compréhensible pour un utilisateur métier qu'une explication de type modèle opaque.

---

## Validation par exemples multiples

| Catégorie | Vérification | Statut |
|---|---|---|
| État satisfaisant | Exemples affichés ou documentés | PASS |
| État à surveiller | Exemples affichés ou documentés | PASS |
| Usage déconseillé | Exemples affichés ou documentés | PASS |
| Examen prioritaire suggéré | Exemples affichés ou documentés | PASS |
| Intervention conseillée | Exemples affichés ou documentés | PASS |
| Défaut confirmé | Exemples affichés ou documentés | PASS |
| Ambiguïtés -> Défaut confirmé = 0 | Règle V3 confirmée | PASS |

---

## Conclusion

La version `VHS_BALANCED_V3_CANDIDATE` est techniquement validée comme version candidate finale du module Vehicle Health Score.

Le score VHS est donc explicable sans recourir à une méthode d'explicabilité de modèle de type SHAP.

Les éléments présentés constituent une aide à l'analyse. La décision finale reste sous la responsabilité du gestionnaire.

---

> **Aucune opération d'écriture en base de données n'a été effectuée.**
> **Ce notebook est un artefact de validation et ne remplace pas le moteur VHS de production.**

*Généré par `notebooks/validation_vhs/01_validate_vhs_balanced_v3_candidate.ipynb`*