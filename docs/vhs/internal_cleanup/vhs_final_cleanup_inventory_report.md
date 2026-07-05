# Rapport d'inventaire et recommandations de nettoyage final — Module VHS

> **Type :** Audit uniquement — aucune suppression, aucun déplacement effectué
> **Date :** 2026-07-05
> **Périmètre :** Ensemble des fichiers VHS du projet IRIS_AUTO_FRAUD
> **Destinataires :** Responsable technique, équipe BNA Assurances, jury académique

---

## 1. Objectif de l'audit

Le module VHS (Vehicle Health Score) est maintenant **fonctionnellement complet** :

- Moteur déterministe V3 validé (`VHS_BALANCED_V3_CANDIDATE`)
- Notebooks de validation technique et statistique créés
- Documentation métier, méthode de calcul et explication BNA rédigées
- Architecture de gouvernance human-in-the-loop documentée
- DDL de gouvernance proposé et testé en base de test PostgreSQL

Avant de passer au module suivant de la plateforme IRIS, cet audit vise à :

1. **Inventorier** l'ensemble des fichiers VHS présents dans le projet
2. **Classer** chaque fichier selon son rôle (actif, documentation, rapport, bruit)
3. **Recommander** les actions de nettoyage nécessaires
4. **Proposer** une structure finale propre et professionnelle

> **Règles strictes de cet audit :**
> - Aucun fichier n'a été supprimé, déplacé ou renommé
> - Aucun code de production n'a été modifié
> - Aucune écriture en base de données n'a été effectuée
> - Ce document est le seul livrable de cette étape

**Constat important identifié :** Le fichier `.gitignore` contient une entrée `notebooks/` qui exclut l'intégralité du dossier `notebooks/` du suivi Git. Cette règle mérite une révision explicite (voir section 8).

---

## 2. Inventaire complet des fichiers VHS identifiés

71 fichiers détectés par les patterns : `vhs`, `VHS`, `vehicle_health`, `staffim`, `STAFFIM`, `checkpoint`, `immobilise`, `immobilizing`, `health_score`.

### 2.1 Fichiers actifs et documentation finale

| Catégorie | Fichier | Taille | Statut |
|-----------|---------|-------:|--------|
| **Moteur actif** | `etl/mart/compute_vhs_v3_candidate.py` | 53,5 KB | `KEEP_ACTIVE` |
| **Moteur actif** | `etl/mart/load_dim_checkpoint.py` | 21,5 KB | `KEEP_ACTIVE` |
| **Notebook validation** | `notebooks/validation_vhs/01_validate_vhs_balanced_v3_candidate.ipynb` | 367 KB | `KEEP_ACTIVE` |
| **Notebook robustesse** | `notebooks/validation_vhs/03_vhs_statistical_robustness_analysis.ipynb` | 400 KB | `KEEP_ACTIVE` |
| **Notebook STAFFIM** | `notebooks/04_staffim_comment_analysis_for_vhs.ipynb` | 307 KB | `REVIEW` |
| **Documentation principale** | `docs/vhs/vhs_final_module_summary.md` | 16,2 KB | `KEEP_DOCUMENTATION` |
| **Documentation principale** | `docs/vhs/vhs_calculation_method.md` | 17,4 KB | `KEEP_DOCUMENTATION` |
| **Documentation principale** | `docs/vhs/vhs_business_explanation.md` | 3,9 KB | `KEEP_DOCUMENTATION` |
| **Documentation principale** | `docs/vhs/vhs_business_label_mapping.md` | 1,6 KB | `KEEP_DOCUMENTATION` |
| **Documentation principale** | `docs/vhs/vhs_validation_summary.md` | 3,5 KB | `KEEP_DOCUMENTATION` |
| **Robustesse statistique** | `docs/vhs/vhs_statistical_robustness_plan.md` | 27,3 KB | `KEEP_DOCUMENTATION` |
| **Robustesse statistique** | `docs/vhs/vhs_statistical_robustness_execution_summary.md` | 2,3 KB | `KEEP_DOCUMENTATION` |
| **Gouvernance** | `docs/vhs/governance/vhs_human_in_the_loop_and_history_architecture.md` | 25,1 KB | `KEEP_DOCUMENTATION` |
| **Gouvernance** | `docs/vhs/governance/vhs_governance_table_design.md` | 30,1 KB | `KEEP_DOCUMENTATION` |
| **Gouvernance** | `docs/vhs/governance/vhs_governance_sql_validation_summary.md` | 6,7 KB | `KEEP_DOCUMENTATION` |
| **SQL design** | `docs/vhs/governance/sql/001_create_vhs_governance_tables.sql` | 31,8 KB | `KEEP_DOCUMENTATION` |
| **Rapport qualité** | `data/quality_reports/vhs/final/vhs_v3_audit_summary.md` | 3,2 KB | `KEEP_REPORT` |
| **Rapport qualité** | `data/quality_reports/vhs/final/vhs_v2_vs_v3_comparison_summary.md` | 2,9 KB | `KEEP_REPORT` |
| **Rapport qualité** | `data/quality_reports/vhs/final/v3_immobilise_fix_summary.md` | 3,5 KB | `KEEP_REPORT` |
| **Rapport qualité** | `data/quality_reports/vhs/final/dim_checkpoint_immobilizing_update_summary.md` | 2,2 KB | `KEEP_REPORT` |
| **Diagramme** | `docs/diagrams/vhs_calculation_flow.mmd` | 4,3 KB | `KEEP_DIAGRAM` |
| **Diagramme** | `docs/diagrams/vhs_mapping_rules.mmd` | 0,9 KB | `KEEP_DIAGRAM` |

### 2.2 Fichiers de nettoyage interne (déjà cloisonnés)

| Fichier | Taille | Statut |
|---------|-------:|--------|
| `docs/vhs/internal_cleanup/vhs_cleanup_plan.md` | 13,8 KB | `KEEP_INTERNAL` |
| `docs/vhs/internal_cleanup/vhs_file_decision_matrix.md` | 20,9 KB | `KEEP_INTERNAL` |
| `docs/vhs/internal_cleanup/vhs_cleanup_copy_report.md` | 6,3 KB | `KEEP_INTERNAL` |
| `docs/vhs/internal_cleanup/vhs_cleanup_remove_report.md` | 5,6 KB | `KEEP_INTERNAL` |
| `docs/vhs/internal_cleanup/vhs_externalization_report.md` | 5,2 KB | `KEEP_INTERNAL` |
| `docs/vhs/internal_cleanup/vhs_final_project_polish_report.md` | 2,9 KB | `KEEP_INTERNAL` |
| `docs/vhs/internal_cleanup/vhs_notebook_validation_execution_summary.md` | 2,6 KB | `KEEP_INTERNAL` |
| `docs/vhs/internal_cleanup/vhs_orphan_csv_cleanup_report.md` | 2,1 KB | `KEEP_INTERNAL` |

### 2.3 Exports CSV STAFFIM exploratoires

| Fichier | Taille | Statut |
|---------|-------:|--------|
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/non_by_checkpoint.csv` | 0,8 KB | `REVIEW` |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/non_critical_cases.csv` | 0,4 KB | `REVIEW` |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/non_hard_cap_triggers.csv` | 0,4 KB | `REVIEW` |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/non_in_severe_cases.csv` | 7,3 KB | `REVIEW` |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/non_no_anomaly_cases.csv` | 37,4 KB | `REVIEW` |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/non_profile_summary.csv` | 0,5 KB | `REVIEW` |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/non_simple_cases.csv` | 37,4 KB | `REVIEW` |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/non_simulation_if_not_broken.csv` | 39,5 KB | `REVIEW` |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/non_with_advisory_or_unclear_comments.csv` | 11,4 KB | `REVIEW` |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/non_with_strong_comments.csv` | 14 KB | `REVIEW` |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/staffim_comment_analysis_summary.md` | 1,1 KB | `REVIEW` |

### 2.4 Logs de run VHS

| Fichier | Taille | Statut |
|---------|-------:|--------|
| `logs/load_dwh_compute_vhs_v3_candidate.log` | 7,7 KB | `KEEP_LOCAL_ONLY` |
| `logs/load_dwh_compute_vhs.log` | 13,9 KB | `KEEP_LOCAL_ONLY` |
| `logs/load_dwh_compute_vhs_v2.log` | 3,8 KB | `KEEP_LOCAL_ONLY` |
| `logs/load_dwh_audit_vhs_v1.log` | 4,1 KB | `KEEP_LOCAL_ONLY` |
| `logs/load_dwh_audit_vhs_v2_severe.log` | 3,6 KB | `KEEP_LOCAL_ONLY` |
| `logs/load_dwh_audit_vhs_v3_immobilise_cases.log` | 4 KB | `KEEP_LOCAL_ONLY` |
| `logs/load_dwh_load_dim_checkpoint.log` | 10,3 KB | `KEEP_LOCAL_ONLY` |
| `logs/audit_vhs_v3_immobilise_driver_labels_...log` | 1,5 KB | `KEEP_LOCAL_ONLY` |
| `logs/compare_vhs_v3_candidate_before_after_...log` | 1,6 KB | `KEEP_LOCAL_ONLY` |
| `logs/update_dim_checkpoint_v3_immobilizing_flags_...log` | 3,8 KB | `KEEP_LOCAL_ONLY` |
| `logs/load_fact_inspection_checkpoint_20260629_*.log` (× 6) | ~52 KB | `KEEP_LOCAL_ONLY` |

### 2.5 Fichiers compilés Python (__pycache__)

| Fichier | Taille | Statut |
|---------|-------:|--------|
| `etl/mart/__pycache__/compute_vhs_v3_candidate.cpython-312.pyc` | 60,5 KB | `IGNORE_IN_GIT` |
| `etl/mart/__pycache__/compute_vhs_v2.cpython-312.pyc` | 47,3 KB | `IGNORE_IN_GIT` |
| `etl/mart/__pycache__/audit_vhs_v3_immobilise_cases.cpython-312.pyc` | 32 KB | `IGNORE_IN_GIT` |
| `etl/mart/__pycache__/audit_vhs_v2_severe_cases.cpython-312.pyc` | 31,9 KB | `IGNORE_IN_GIT` |
| `etl/mart/__pycache__/compute_vhs.cpython-312.pyc` | 31,6 KB | `IGNORE_IN_GIT` |
| `etl/mart/__pycache__/audit_vhs_v1.cpython-312.pyc` | 27,5 KB | `IGNORE_IN_GIT` |
| `etl/mart/__pycache__/audit_vhs_t1_criticality.cpython-312.pyc` | 24,3 KB | `IGNORE_IN_GIT` |
| `etl/mart/__pycache__/load_dim_checkpoint.cpython-312.pyc` | 16,2 KB | `IGNORE_IN_GIT` |

> **Note :** Les `.pyc` révèlent l'existence passée de scripts `compute_vhs.py`, `compute_vhs_v2.py`, `audit_vhs_v1.py`, `audit_vhs_v2_severe_cases.py`, `audit_vhs_t1_criticality.py` — tous des scripts de développement intermédiaires. Ces scripts ne sont plus présents dans `etl/mart/` (les `.py` correspondants sont absents) et ne sont donc plus actifs. Seuls leurs caches compilés subsistent.

### 2.6 Rapports CSV fact_inspection_checkpoint (périmètre DWH, pas spécifiquement VHS)

| Fichier | Taille | Statut |
|---------|-------:|--------|
| `data/quality_reports/fact_inspection_checkpoint/fact_inspection_checkpoint_mapping_report.csv` | 10 KB | `KEEP_LOCAL_ONLY` |
| `data/quality_reports/fact_inspection_checkpoint/fact_inspection_checkpoint_value_distribution.csv` | 11,8 KB | `KEEP_LOCAL_ONLY` |
| `data/quality_reports/fact_inspection_checkpoint/fact_inspection_checkpoint_load_summary.csv` | 0,3 KB | `KEEP_LOCAL_ONLY` |
| `data/quality_reports/fact_inspection_checkpoint/fact_inspection_checkpoint_duplicate_grain.csv` | 0,1 KB | `KEEP_LOCAL_ONLY` |
| `data/quality_reports/fact_inspection_checkpoint/fact_inspection_checkpoint_unmatched_inspections.csv` | 0,1 KB | `KEEP_LOCAL_ONLY` |

---

## 3. Fichiers qui doivent rester dans le projet actif (Git)

Ces fichiers constituent le **cœur traçable du module VHS** et doivent être versionnés.

### 3.1 Moteur de calcul

| Fichier | Justification |
|---------|---------------|
| `etl/mart/compute_vhs_v3_candidate.py` | Moteur actif — toute modification passe par ce fichier |
| `etl/mart/load_dim_checkpoint.py` | Chargeur de la dimension checkpoint — prérequis du moteur V3 |

### 3.2 Notebooks de validation

| Fichier | Justification |
|---------|---------------|
| `notebooks/validation_vhs/01_validate_vhs_balanced_v3_candidate.ipynb` | Validation technique complète — artefact académique de référence |
| `notebooks/validation_vhs/03_vhs_statistical_robustness_analysis.ipynb` | Validation statistique — plan méthodologique exécutable |

> **Action requise :** Le `.gitignore` actuel contient `notebooks/` qui exclut ces fichiers du suivi Git. Cette règle doit être révisée (voir section 8).

### 3.3 Documentation principale

Tous les fichiers `docs/vhs/*.md` (hors `internal_cleanup/`) sont des livrables finaux destinés au jury académique et à BNA Assurances. Ils doivent rester versionnés.

### 3.4 Documentation de gouvernance

Les 4 fichiers de `docs/vhs/governance/` sont des propositions architecturales et de conception qui constituent la feuille de route de la Phase 2. Ils restent versionnés.

### 3.5 Rapports qualité finaux

Les 4 fichiers de `data/quality_reports/vhs/final/*.md` documentent les décisions de conception V3 (correctif IMMOBILISE, comparaison V2/V3). Ils restent versionnés grâce à la règle `!data/quality_reports/**/*.md` déjà présente dans le `.gitignore`.

### 3.6 Diagrammes Mermaid

`docs/diagrams/vhs_calculation_flow.mmd` et `vhs_mapping_rules.mmd` sont des artefacts visuels réutilisables. Ils restent versionnés.

---

## 4. Fichiers à déplacer vers le nettoyage interne ou l'archive

Ces fichiers ne sont pas nuisibles mais alourdissent la couche documentaire visible.

| Fichier | Raison | Action recommandée |
|---------|--------|--------------------|
| `notebooks/04_staffim_comment_analysis_for_vhs.ipynb` | Notebook exploratoire hors du dossier `validation_vhs/` — son emplacement dans la racine `notebooks/` est ambigu | `REVIEW_MANUALLY` — envisager déplacement vers `notebooks/validation_vhs/` ou archivage |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/*.csv` (× 10) | Exports CSV exploratoires produits par le notebook STAFFIM — ne sont pas des livrables finaux | `MOVE_TO_ARCHIVE_OUTSIDE_GIT` — déjà ignorés par `.gitignore (*.csv)` |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/staffim_comment_analysis_summary.md` | Rapport de synthèse intermédiaire — utile si le notebook STAFFIM est conservé actif | `KEEP_IF_REFERENCED` par le notebook |
| `docs/vhs/internal_cleanup/vhs_cleanup_plan.md` | Plan de nettoyage de session précédente — trace d'historique | `KEEP_INTERNAL` — déjà correctement placé |
| `docs/vhs/internal_cleanup/vhs_file_decision_matrix.md` | Matrice de décision intermédiaire | `KEEP_INTERNAL` — déjà correctement placé |
| `docs/vhs/internal_cleanup/vhs_cleanup_copy_report.md` | Rapport de copie de session précédente | `KEEP_INTERNAL` — déjà correctement placé |
| `docs/vhs/internal_cleanup/vhs_cleanup_remove_report.md` | Rapport de suppression de session précédente | `KEEP_INTERNAL` — déjà correctement placé |
| `docs/vhs/internal_cleanup/vhs_externalization_report.md` | Rapport d'externalisation | `KEEP_INTERNAL` — déjà correctement placé |
| `docs/vhs/internal_cleanup/vhs_final_project_polish_report.md` | Rapport de polish intermédiaire | `KEEP_INTERNAL` — déjà correctement placé |
| `docs/vhs/internal_cleanup/vhs_notebook_validation_execution_summary.md` | Synthèse d'exécution notebook V1 — remplacée par les synthèses actuelles | `KEEP_INTERNAL` — conserver pour traçabilité |
| `docs/vhs/internal_cleanup/vhs_orphan_csv_cleanup_report.md` | Rapport CSV orphelins | `KEEP_INTERNAL` — déjà correctement placé |

> **Constat positif :** tous les fichiers de nettoyage interne sont déjà cloisonnés dans `docs/vhs/internal_cleanup/` — aucune action de déplacement nécessaire pour cette catégorie.

---

## 5. Fichiers à ignorer ou supprimer localement

Ces fichiers sont générés automatiquement et ne doivent pas être versionnés.

| Pattern / Fichier | Raison | Action recommandée |
|-------------------|--------|--------------------|
| `etl/mart/__pycache__/*.pyc` (× 8) | Fichiers compilés Python — générés automatiquement à l'import | `IGNORE_IN_GIT` — déjà couvert par `__pycache__/` et `*.py[cod]` dans `.gitignore` |
| `logs/*.log` (× 20+) | Logs d'exécution — non nécessaires pour la traçabilité académique | `IGNORE_IN_GIT` — déjà couvert par `logs/` et `*.log` dans `.gitignore` |
| `notebooks/data/quality_reports/vhs/staffim_comment_analysis/non_*.csv` (× 10) | Exports exploratoires de grande taille (jusqu'à 39 KB) — non reproductibles en production | `IGNORE_IN_GIT` — déjà couvert par `*.csv` dans `.gitignore` |
| `data/quality_reports/fact_inspection_checkpoint/*.csv` (× 5) | Rapports CSV de la couche DWH — périmètre data engineering, non VHS spécifique | `IGNORE_IN_GIT` — déjà couvert par `*.csv`. Envisager conservation du `.md` correspondant |
| `data/processed/*.xlsx` | Enrichissements intermédiaires — générés par les notebooks | `IGNORE_IN_GIT` — déjà couvert par `*.xlsx` dans `.gitignore` |
| `data/processed/reports/*.xlsx` | Rapports de qualité Excel intermédiaires | `IGNORE_IN_GIT` — déjà couvert par `*.xlsx` dans `.gitignore` |
| `.ipynb_checkpoints/` | Points de contrôle Jupyter — générés automatiquement | `IGNORE_IN_GIT` — déjà couvert par `.ipynb_checkpoints/` dans `.gitignore` |

> **Constat :** le `.gitignore` existant couvre déjà correctement la majorité de ces patterns. Les fichiers listés ci-dessus sont déjà hors du suivi Git — aucune modification du `.gitignore` n'est strictement nécessaire sur ces points.

---

## 6. Structure finale VHS proposée

La structure ci-dessous représente l'état propre cible du module VHS après nettoyage.

```
IRIS_AUTO_FRAUD/
│
├── etl/
│   └── mart/
│       ├── compute_vhs_v3_candidate.py          ← moteur actif
│       └── load_dim_checkpoint.py               ← dimension prérequis
│
├── notebooks/
│   └── validation_vhs/
│       ├── 01_validate_vhs_balanced_v3_candidate.ipynb    ← validation technique
│       ├── 03_vhs_statistical_robustness_analysis.ipynb   ← validation statistique
│       └── (04_staffim_comment_analysis_for_vhs.ipynb)    ← à déplacer ici ou archiver
│
├── docs/
│   ├── diagrams/
│   │   ├── vhs_calculation_flow.mmd
│   │   └── vhs_mapping_rules.mmd
│   └── vhs/
│       ├── vhs_final_module_summary.md          ← synthèse de référence
│       ├── vhs_calculation_method.md
│       ├── vhs_business_explanation.md
│       ├── vhs_business_label_mapping.md
│       ├── vhs_validation_summary.md
│       ├── vhs_statistical_robustness_plan.md
│       ├── vhs_statistical_robustness_execution_summary.md
│       ├── governance/
│       │   ├── vhs_human_in_the_loop_and_history_architecture.md
│       │   ├── vhs_governance_table_design.md
│       │   ├── vhs_governance_sql_validation_summary.md
│       │   └── sql/
│       │       └── 001_create_vhs_governance_tables.sql
│       └── internal_cleanup/                    ← traçabilité de session, non exposée
│           ├── vhs_cleanup_plan.md
│           ├── vhs_file_decision_matrix.md
│           ├── vhs_cleanup_copy_report.md
│           ├── vhs_cleanup_remove_report.md
│           ├── vhs_externalization_report.md
│           ├── vhs_final_project_polish_report.md
│           ├── vhs_notebook_validation_execution_summary.md
│           ├── vhs_orphan_csv_cleanup_report.md
│           └── vhs_final_cleanup_inventory_report.md  ← ce document
│
└── data/
    └── quality_reports/
        └── vhs/
            └── final/
                ├── vhs_v3_audit_summary.md
                ├── vhs_v2_vs_v3_comparison_summary.md
                ├── v3_immobilise_fix_summary.md
                └── dim_checkpoint_immobilizing_update_summary.md
```

**Ce qui n'apparaît pas dans cette structure :**
- `logs/` — ignoré par Git
- `__pycache__/` — ignoré par Git
- `*.csv` — ignorés par Git
- `*.xlsx` — ignorés par Git
- `data/processed/` — ignoré par Git

---

## 7. Recommandation de mise à jour du README

> **Aucune modification du README n'est effectuée dans cette étape.**

La section suivante est proposée pour intégration dans le README principal du projet :

---

```markdown
## Module VHS — Vehicle Health Score

### Statut
✓ **VHS_BALANCED_V3_CANDIDATE — Validé**  
Moteur déterministe à base de règles — non ML, non probabilité de fraude.

### Moteur actif
- `etl/mart/compute_vhs_v3_candidate.py`
- `etl/mart/load_dim_checkpoint.py`

### Notebooks de validation
- `notebooks/validation_vhs/01_validate_vhs_balanced_v3_candidate.ipynb` — Validation technique (286 inspections, 0 anomalie)
- `notebooks/validation_vhs/03_vhs_statistical_robustness_analysis.ipynb` — Validation statistique complémentaire

### Documentation
| Document | Rôle |
|---|---|
| `docs/vhs/vhs_final_module_summary.md` | Synthèse finale du module |
| `docs/vhs/vhs_calculation_method.md` | Méthode de calcul |
| `docs/vhs/vhs_business_explanation.md` | Explication métier (BNA-ready) |
| `docs/vhs/vhs_validation_summary.md` | Synthèse de validation |
| `docs/vhs/vhs_statistical_robustness_plan.md` | Plan de validation statistique |

### Gouvernance (Phase 2)
| Document | Rôle |
|---|---|
| `docs/vhs/governance/vhs_human_in_the_loop_and_history_architecture.md` | Architecture human-in-the-loop |
| `docs/vhs/governance/vhs_governance_table_design.md` | Design des 5 tables de gouvernance |
| `docs/vhs/governance/sql/001_create_vhs_governance_tables.sql` | DDL proposé — validé en base de test |

### Rapports qualité
- `data/quality_reports/vhs/final/` — Audit V3, comparaison V2/V3, correctif IMMOBILISE

### Avertissements
> **Le VHS est un indicateur d'aide à la décision, pas un verdict automatique.**
> Il n'est pas un modèle ML, pas une probabilité de fraude.
> La décision finale reste sous la responsabilité du gestionnaire BNA.
> La mise en production est conditionnée à la validation formelle de BNA Assurances.
```

---

## 8. Recommandation .gitignore

> **Aucune modification du `.gitignore` n'est effectuée dans cette étape.**

### 8.1 Ce qui est déjà correctement configuré

Le `.gitignore` actuel couvre déjà :

| Pattern | Couverture |
|---------|-----------|
| `__pycache__/` et `*.py[cod]` | Fichiers compilés Python — ✓ |
| `logs/` et `*.log` | Tous les logs de run — ✓ |
| `*.csv`, `*.xlsx`, `*.parquet` | Exports de données — ✓ |
| `data/raw/`, `data/processed/` | Données brutes et transformées — ✓ |
| `.ipynb_checkpoints/` | Points de contrôle Jupyter — ✓ |
| `!data/quality_reports/**/*.md` | Conservation des rapports Markdown — ✓ |
| `!docs/vhs/governance/sql/*.sql` | Conservation du DDL de gouvernance — ✓ |
| `.env`, `config/database.yaml` | Secrets et config locale — ✓ |

### 8.2 Point critique identifié : entrée `notebooks/`

Le `.gitignore` contient la ligne suivante, probablement involontaire ou à réviser :

```
notebooks/
```

**Impact :** Cette règle exclut du suivi Git l'intégralité du dossier `notebooks/`, y compris :
- `notebooks/validation_vhs/01_validate_vhs_balanced_v3_candidate.ipynb`
- `notebooks/validation_vhs/03_vhs_statistical_robustness_analysis.ipynb`

Ces deux notebooks sont des **livrables académiques de premier plan**. Leur exclusion de Git est problématique pour la traçabilité et la présentation du projet.

**Recommandation :** Remplacer `notebooks/` par une règle plus sélective :

```gitignore
# Notebooks — exclure les checkpoints, conserver les notebooks finaux
.ipynb_checkpoints/
notebooks/data/
# Si on veut ignorer les notebooks exploratoires uniquement :
# notebooks/0[1-3]_*.ipynb
# Si on veut versionner tous les notebooks finaux :
# (supprimer la ligne notebooks/)
```

### 8.3 Aucune autre modification nécessaire

Le `.gitignore` actuel est bien structuré. Seule la règle `notebooks/` mérite révision.

---

## 9. Évaluation des risques avant nettoyage

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| **Suppression accidentelle d'un rapport final** | Faible si l'inventaire est respecté | Élevé | Procéder fichier par fichier, jamais en bloc — vérifier que chaque fichier est dans la liste `KEEP` avant de toucher aux autres |
| **Déplacement d'un notebook référencé dans la documentation** | Faible | Moyen | Vérifier les liens croisés dans les `.md` avant tout déplacement |
| **Perte de traçabilité des audits** | Faible | Moyen | Conserver `docs/vhs/internal_cleanup/` en intégralité — ne pas le supprimer |
| **Mélange entre VHS actif et expérimentations archivées** | Moyen | Moyen | Maintenir le dossier `validation_vhs/` dédié pour les notebooks finaux |
| **Commit accidentel de données confidentielles** | Faible | Élevé | Le `.gitignore` couvre déjà `data/raw/`, `*.csv`, `*.xlsx` — vérifier `git status` avant chaque commit |
| **Suppression de la règle `notebooks/` sans conséquences mesurées** | Moyen | Moyen | Tester avec `git status` après modification du `.gitignore` avant de committer |
| **Liens brisés dans les documents de gouvernance** | Faible | Faible | Les documents de gouvernance utilisent des chemins relatifs — les vérifier si des fichiers sont déplacés |

---

## 10. Plan d'exécution du nettoyage

| Étape | Action | Priorité |
|-------|--------|----------|
| **A** | Relire ce rapport d'inventaire et valider les recommandations | Obligatoire |
| **B** | Confirmer explicitement la liste des fichiers `KEEP_ACTIVE` et `KEEP_DOCUMENTATION` | Obligatoire |
| **C** | Réviser `.gitignore` : retirer ou ajuster la ligne `notebooks/` | Haute |
| **D** | Déplacer `notebooks/04_staffim_comment_analysis_for_vhs.ipynb` vers `notebooks/validation_vhs/` si conservé, ou vers ArchiveVHS | Moyenne |
| **E** | Supprimer localement les fichiers générés après confirmation : `__pycache__`, exports CSV exploratoires | Basse — `rm -rf etl/mart/__pycache__/` après confirmation |
| **F** | Mettre à jour le `README.md` avec la section VHS proposée en section 7 | Haute |
| **G** | Exécuter `git status` pour vérifier l'état du dépôt avant commit | Obligatoire |
| **H** | Créer un commit de nettoyage avec le message : `Organize final VHS module files — cleanup and README update` | Finale |

---

## 11. Recommandation finale

Le module VHS est dans un **état documentaire solide**. La structure actuelle est déjà largement organisée. Les actions réellement nécessaires se limitent à trois points :

1. **Corriger la règle `notebooks/` dans le `.gitignore`** pour que les notebooks de validation soient versionnés — c'est le point le plus urgent et le plus impactant.

2. **Clarifier le statut du notebook STAFFIM** (`04_staffim_comment_analysis_for_vhs.ipynb`) : le déplacer dans `validation_vhs/` s'il est un livrable final, ou le documenter comme exploratoire.

3. **Ajouter la section VHS au README** pour rendre le module immédiatement lisible par un jury ou un réviseur externe.

**Ce qu'il ne faut pas sur-nettoyer :**

- Ne pas supprimer `docs/vhs/internal_cleanup/` — il constitue la traçabilité de l'évolution du projet, précieuse pour un jury académique.
- Ne pas supprimer les logs locaux avant d'avoir commité les livrables finaux.
- Ne pas déplacer les fichiers de gouvernance — leur emplacement actuel est logique et référencé dans plusieurs documents.

> *Le VHS reste un module d'aide à la décision. Sa documentation doit refléter ce positionnement : propre, explicite, et traçable sans être surchargée.*

---

| Document lié | Contenu |
|---|---|
| `docs/vhs/vhs_final_module_summary.md` | Synthèse complète du module VHS |
| `docs/vhs/internal_cleanup/vhs_file_decision_matrix.md` | Matrice de décision des sessions précédentes |
| `docs/vhs/vhs_statistical_robustness_plan.md` | Plan de validation statistique |
| `docs/vhs/governance/vhs_human_in_the_loop_and_history_architecture.md` | Architecture de gouvernance |

---

*Document créé dans le cadre du projet IRIS Auto Fraud Decision Platform — PFE 2026.*
*Audit uniquement — aucun fichier n'a été supprimé, déplacé ou modifié.*
