# Orchestration Apache Airflow pour IRIS

Cette intégration ajoute une couche d'orchestration sans déplacer la logique
métier hors des scripts existants.

## DAG livré

`iris_full_pipeline` est planifié quotidiennement à **02:00 UTC** (fenêtre de
faible activité) et limité à une exécution simultanée. Le déclenchement manuel
(`Trigger DAG`) reste disponible en plus du planning — il ne le remplace pas.
Le recalcul complet remplace des tables du DWH ; le planning choisi vise donc
une fenêtre de maintenance, mais `allow_active_connections=false` par défaut
fera échouer l'exécution planifiée si une session (Flask, Power BI, pgAdmin)
reste ouverte sur la base à ce moment — c'est un garde-fou volontaire, pas un
bug.

**Important** : le DAG est créé **en pause** par Airflow
(`AIRFLOW__CORE__PAUSE_DAGS_AT_CREATION=true`). Le planning ne s'exécute donc
pas tant qu'il n'est pas activé explicitement (bascule "Pause/Unpause" dans
l'UI, sur la ligne `iris_full_pipeline`).

Ordre des tâches :

1. `validate_configuration`
2. `load_staging` (optionnelle)
3. `guarded_dwh_and_scoring_recompute`
4. `compute_vhs_v4`
5. `refresh_powerbi_views`

Le cœur du recalcul reste `etl/orchestrate_full_recompute.py`. Il conserve :

- la confirmation obligatoire de la base cible ;
- le contrôle des connexions actives ;
- la sauvegarde et la restauration best-effort des vues Power BI ;
- le comportement fail-fast ;
- les contrôles métier finaux ;
- les identifiants de run et les journaux IRIS.

Airflow ajoute l'interface, les états de tâches, l'historique des exécutions et
la possibilité de reprendre une tâche explicitement.

## Prérequis

- Docker Desktop avec les conteneurs Linux ;
- PostgreSQL IRIS accessible depuis Docker ;
- le fichier `../.env` contenant `DB_PORT`, `DB_NAME`, `DB_USER` et
  `DB_PASSWORD` ;
- les données sources et préparées attendues par les scripts IRIS.

Sous Windows, Docker Desktop doit être installé avant de poursuivre. Le poste
inspecté ne dispose pas encore de Docker ni de WSL.

## Base de test obligatoire au premier démarrage

Le fichier `airflow/.env` fixe par défaut :

```text
IRIS_TARGET_DB=iris_auto_fraud_test_20260724
```

La valeur doit correspondre exactement à `DB_NAME` dans le fichier `.env` du
projet. Le préflight Airflow et l'orchestrateur IRIS refusent l'exécution en cas
de différence. Ne remplacer cette valeur par une base de production qu'après
validation complète du DAG sur la base de test.

## Démarrage local

Depuis le dossier `IRIS_AUTO_FRAUD/airflow` :

```powershell
docker compose build
docker compose up -d
docker compose logs -f airflow
```

Le premier démarrage affiche dans les journaux les identifiants administrateur
générés par `airflow standalone`.

Interface :

```text
http://localhost:8080
```

Le DAG est créé en pause. Ouvrir `iris_full_pipeline`, puis utiliser
`Trigger DAG`.

## Paramètres de déclenchement

| Paramètre | Défaut | Rôle |
|---|---:|---|
| `confirm_db` | `IRIS_TARGET_DB` | Confirmation obligatoire de la base cible |
| `reload_staging` | `false` | Recharge les quatre tables staging |
| `allow_active_connections` | `false` | Force malgré des connexions actives |
| `skip_exact_checks` | `false` | Ignore uniquement les valeurs historiques exactes |

Pour le premier essai, conserver :

```text
reload_staging=false
allow_active_connections=false
skip_exact_checks=false
```

Ne jamais activer `allow_active_connections` tant que Flask, Power BI, pgAdmin
ou une autre session utilise la base.

## Arrêt

```powershell
docker compose down
```

Les métadonnées Airflow restent dans le volume `airflow_home`.

Une réinitialisation volontaire des seules métadonnées Airflow se fait avec :

```powershell
docker compose down --volumes
```

Cette commande ne supprime ni le projet IRIS ni la base PostgreSQL métier.

## Portée

Cette configuration utilise `airflow standalone` pour une démonstration locale
et un PFE. Elle ne doit pas être présentée comme un déploiement Airflow de
production. Une industrialisation nécessite notamment une base de métadonnées
externe, une stratégie d'authentification, des sauvegardes, des alertes et une
supervision du scheduler.
