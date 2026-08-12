# Human-in-the-loop : de la philosophie à l'infrastructure

> Vérifié le 07/08/2026 directement dans le code et la config Airflow —
> détail technique complet dans `airflow/README.md`.

## Le fait en une phrase

« L'IA éclaire, l'humain décide » n'est pas qu'un slogan de slide : c'est
câblé jusque dans l'infrastructure d'orchestration, à 4 niveaux vérifiés
indépendants.

## Les 4 garde-fous vérifiés (`airflow/dags/iris_full_pipeline.py`, `airflow/docker-compose.yml`)

1. **Le pipeline complet est créé en pause, pas activé** —
   `AIRFLOW__CORE__PAUSE_DAGS_AT_CREATION: "true"` (`airflow/docker-compose.yml:14`).
   Même planifié quotidiennement à 02h00, le DAG ne s'exécute jamais tant
   qu'un humain ne l'a pas explicitement activé dans l'UI.

2. **La base cible doit être confirmée explicitement à chaque déclenchement**
   — paramètre `confirm_db` sans valeur par défaut opérante : le préflight
   Airflow *et* `etl/orchestrate_full_recompute.py` refusent tout run si le
   nom ne correspond pas exactement à `DB_NAME` du `.env`. Impossible de
   lancer « par erreur » un recalcul contre la mauvaise base.

3. **Base de test par défaut au premier démarrage** — `airflow/.env` pointe
   par défaut vers `iris_auto_fraud_test_20260724`, pas vers la base de
   production. Basculer vers la production est un acte délibéré, jamais un
   défaut hérité.

4. **La fenêtre de maintenance est imposée, pas suggérée** — le paramètre
   `allow_active_connections=false` par défaut fait **échouer** le run si
   une session (FastAPI, Power BI, pgAdmin) reste ouverte sur la base au
   moment du déclenchement, plutôt que de risquer une lecture partielle
   pendant un rechargement en mode replace.

Le même principe redescend au niveau du score lui-même : voir
`docs/soutenance/POSITIONNEMENT_CLAIM_ATTENTION_V1_V2.md` — V2 est
techniquement prêt mais architecturalement incapable d'atteindre la
production sans validation métier explicite. C'est le même garde-fou
philosophique, appliqué à deux couches différentes du système (infra
d'orchestration, gouvernance de version de score).

## Phrase jury

> « La pause par défaut du pipeline Airflow n'est pas une case cochée au
> hasard : c'est la même philosophie que celle qui empêche V2 d'atteindre
> la production sans validation métier. Le système peut faire plus que ce
> qu'il fait — et à chaque palier, il attend une décision humaine
> explicite avant d'agir. »

## Limite honnête à mentionner si le jury creuse

Aucune alerte email/Slack n'est configurée sur échec de tâche (documenté
dans `iris_full_pipeline.py`, pas caché) : un échec n'est visible que dans
l'UI Airflow tant qu'aucun canal n'est branché. C'est un choix assumé de
projet de démonstration, pas une omission — bonne réponse si le jury
demande « et en cas d'échec silencieux la nuit ? ».
