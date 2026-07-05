# Synthèse d'exécution — Validation statistique VHS

> **Statut global :** WARNING
> **Date d'exécution :** 2026-07-05 00:05 UTC
> **Profil analysé :** VHS_BALANCED_V3_CANDIDATE

---

## 1. Sources de données

| Paramètre | Valeur |
|-----------|--------|
| Source principale | `database` |
| Run ID analysé | `VHS_BALANCED_V3_CANDIDATE_20260703_181257` |
| Inspections analysées | 286 |
| Lignes checkpoint analysées | 9724 |
| Données individuelles disponibles | Oui |

---

## 2. Résultats par analyse

| Analyse | Statut |
|---------|--------|
| Validation de base | PASS |
| Corrélation | PASS |
| Bootstrap de stabilité | PASS |
| Analyse de sensibilité | WARNING |
| Audit arbre de décision | PASS |
| Clustering exploratoire | PASS |
| PCA (optionnelle) | OPTIONAL/RUN |

**Verdict global : WARNING**

---

## 3. Constats principaux

- Le score VHS est distribué entre 0 et 100, avec une moyenne de 56.46.
- 286 inspections ont été scorées avec 0 anomalie de mapping confirmée.
- Le correctif V3 a réduit les cas Usage déconseillé de 25 à 13 (correction `is_immobilizing AND BROKEN`).
- Les analyses statistiques ont testé la cohérence, la stabilité et la robustesse du score déterministe.

---

## 4. Limites

- Jeu de données de validation : 286 inspections (prototype fonctionnel, non représentatif de la production).
- Usage déconseillé : seulement 13 cas — intervalles bootstrap naturellement plus larges.
- Sensibilité : simulation d'audit uniquement, non recalcul officiel VHS.
- Arbre de décision, clustering et PCA : outils d'audit exploratoires, non modèles de production.
- Validation métier BNA Assurances non encore réalisée.
- XGBoost et SHAP hors périmètre — applicable uniquement après accumulation de labels humains.

---

## 5. Garanties de sécurité

| Garantie | Statut |
|---|---|
| Mode lecture seule activé | ✓ Oui |
| Aucun SQL DML/DDL exécuté | ✓ Oui |
| Moteur VHS non modifié | ✓ Oui |
| Tables production non impactées | ✓ Oui |
| SHAP non utilisé | ✓ Oui |
| XGBoost non entraîné | ✓ Oui |

---

*Document généré automatiquement par le notebook `03_vhs_statistical_robustness_analysis.ipynb`.*
*Aucun code de production n'a été modifié. Aucune écriture en base de données.*
