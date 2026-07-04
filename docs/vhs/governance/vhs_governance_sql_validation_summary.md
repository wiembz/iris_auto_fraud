# Synthèse de validation SQL — Gouvernance VHS

> **Statut :** PASS  
> **Date :** 2026-07-04  
> **Périmètre :** Validation DDL en base de test — aucun impact sur la base principale  
> **Destinataires :** Jury académique, équipes techniques BNA Assurances, future équipe de production

---

## 1. Objectif de la validation

L'objectif de cette validation était de vérifier la syntaxe et la structure du DDL proposé pour la couche de gouvernance VHS dans un environnement PostgreSQL de test.

Le script DDL (`docs/vhs/governance/sql/001_create_vhs_governance_tables.sql`) reste un **artefact de conception**. La validation en base de test confirme sa faisabilité technique sans constituer un déploiement en production.

Points importants :

- La validation a été réalisée manuellement via pgAdmin sur la base de test `iris_auto_fraud_TEST`.
- Elle confirme que le DDL est accepté par PostgreSQL et que les structures peuvent être créées.
- Elle ne constitue pas une mise en production des tables de gouvernance.
- Aucun chargement de données n'a été effectué.
- Le moteur VHS (`etl/mart/compute_vhs_v3_candidate.py`) n'a pas été modifié.

> **Cette validation confirme la faisabilité technique du DDL, sans constituer une mise en production.**

---

## 2. Environnement de test

| Élément | Valeur |
|---------|--------|
| Base de test | `iris_auto_fraud_TEST` |
| Schéma | `mart` |
| Script testé | `docs/vhs/governance/sql/001_create_vhs_governance_tables.sql` |
| Outil | pgAdmin |
| Type de validation | Validation DDL — création de structures uniquement |
| Impact base principale | **Aucun** |
| Données chargées | **Aucune** |

---

## 3. Tables validées

Les 5 tables de gouvernance proposées ont été créées avec succès dans le schéma `mart` de la base de test :

| Schéma | Table | Rôle |
|--------|-------|------|
| `mart` | `dim_vhs_rule_version` | Versionnement des règles VHS |
| `mart` | `fact_vhs_score_history` | Historisation des scores VHS (append-only) |
| `mart` | `fact_vhs_penalty_detail_history` | Historisation des explications checkpoint |
| `mart` | `vhs_human_review` | Revue humaine — human-in-the-loop |
| `mart` | `vhs_stability_metrics` | Métriques de stabilité métier |

**5/5 tables de gouvernance proposées créées avec succès dans le schéma de test.**

---

## 4. Requête de vérification utilisée

La requête suivante a été exécutée dans pgAdmin sur `iris_auto_fraud_TEST` pour confirmer la présence des tables :

```sql
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_schema = 'mart'
  AND table_name IN (
    'dim_vhs_rule_version',
    'fact_vhs_score_history',
    'fact_vhs_penalty_detail_history',
    'vhs_human_review',
    'vhs_stability_metrics'
  )
ORDER BY table_name;
```

### Résultat observé

| `table_schema` | `table_name` |
|----------------|-------------|
| `mart` | `dim_vhs_rule_version` |
| `mart` | `fact_vhs_penalty_detail_history` |
| `mart` | `fact_vhs_score_history` |
| `mart` | `vhs_human_review` |
| `mart` | `vhs_stability_metrics` |

5 lignes retournées — toutes les tables attendues sont présentes.

---

## 5. Résultat de validation

| Vérification | Résultat |
|---|---|
| Syntaxe SQL acceptée par PostgreSQL | ✓ PASS |
| Schéma `mart` créé ou réutilisé sans erreur | ✓ PASS |
| 5/5 tables créées | ✓ PASS |
| Contraintes `CHECK` et `UNIQUE` acceptées | ✓ PASS |
| Index simples et index uniques partiels acceptés | ✓ PASS |
| Commentaires `COMMENT ON TABLE / COLUMN` acceptés | ✓ PASS |
| Aucun `INSERT` actif exécuté (seed commenté) | ✓ PASS |
| Requêtes DQ restent commentées | ✓ PASS |
| Base principale non impactée | ✓ PASS |

### Statut global : **PASS**

---

## 6. Ce que cette validation ne couvre pas

Cette validation DDL en base de test est limitée à la vérification structurelle. Elle **ne couvre pas** :

| Domaine | Raison de l'exclusion |
|---------|----------------------|
| Chargement de données | Aucun loader ETL n'existe encore pour ces tables |
| Intégration ETL | Les scripts de chargement seront créés lors de la Phase 2 |
| Performance sous volume | La base de test ne contient aucune donnée |
| Workflow de revue humaine (IRIS) | Interface non encore implémentée |
| Validation métier BNA | Requiert l'approbation formelle de BNA Assurances |
| Déploiement en production | Soumis à révision technique et validation projet |
| Modèle ML / XGBoost | Hors périmètre de la Phase 2 |
| Explicabilité SHAP | Applicable uniquement à un futur modèle ML, non au VHS actuel |
| Agents IA | Hors périmètre |

Cette validation confirme uniquement que le DDL proposé peut être créé dans un environnement PostgreSQL de test.

---

## 7. Positionnement dans la feuille de route

### Étapes complétées

| Étape | Livrable | Statut |
|-------|---------|--------|
| Étape 1 | Document d'architecture de gouvernance | ✓ Complété |
| Étape 2 | Design technique des tables | ✓ Complété |
| Étape 3 | Proposition SQL DDL | ✓ Complété |
| Étape 4 | Validation DDL en base de test | ✓ Complété |
| Étape 5 | Synthèse de validation (ce document) | ✓ En cours |

### Prochaines étapes

| Étape | Livrable |
|-------|---------|
| Étape 6 | Conception des loaders ETL (dry-run) |
| Étape 7 | Implémentation des loaders — uniquement après approbation |
| Étape 8 | Alimentation de la file de revue humaine (`seed_vhs_human_review_queue`) |
| Étape 9 | Calcul des métriques de stabilité (`compute_vhs_stability_metrics`) |

> **La mise en production des tables de gouvernance dans la base principale est conditionnée à la validation formelle par BNA Assurances et à la révision technique du projet.**

---

## 8. Conclusion

Le DDL de gouvernance VHS a été validé avec succès dans un environnement PostgreSQL de test. Cette validation confirme que la structure proposée est techniquement faisable et que les contraintes, index et commentaires définis dans le design sont acceptés par PostgreSQL.

Les points fondamentaux sont préservés :

- **Aucun code de production n'a été modifié.** Le moteur VHS (`etl/mart/compute_vhs_v3_candidate.py`) et les scripts ETL existants restent inchangés.
- **La base de données principale n'a pas été impactée.** Toute la validation a été réalisée sur `iris_auto_fraud_TEST` uniquement.
- **Le moteur VHS déterministe reste actif et validé.** La couche de gouvernance vient en complément, sans interférer avec le calcul du score.

La prochaine étape consistera à concevoir les loaders ETL en mode dry-run avant toute écriture en base principale.

---

*Document créé dans le cadre du projet IRIS Auto Fraud Decision Platform — PFE 2026.*  
*Aucun code de production n'a été modifié. Aucun SQL n'a été exécuté par l'assistant.*
