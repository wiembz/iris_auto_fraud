# Limites de scalabilité connues et pistes d'amélioration

> Écrit le 08/08/2026, à partir d'observations directes faites en exécutant
> le pipeline complet la nuit précédente (task 3.3 du plan de soutenance) —
> pas des suppositions. Objectif : montrer une conscience mature des limites
> de l'architecture actuelle, sans les corriger à 15 jours de la soutenance
> (risque de régression non justifié à ce stade — voir section 5 du plan).

## Pourquoi documenter plutôt que corriger maintenant

Le projet fonctionne correctement au volume actuel (~382 000 sinistres,
~586 000 contrats, 284 inspections). Les limites ci-dessous sont des
questions de **passage à l'échelle** (10x, 100x le volume), pas des bugs
qui affectent la fiabilité aujourd'hui — le recalcul complet réussi cette
nuit (`docs/soutenance/PLAN_15_JOURS_VERS_EXCELLENCE.md`, tâche 3.3) le
prouve. Les corriger maintenant serait du temps d'ingénierie dépensé sur un
problème qui n'est pas encore réel, au prix d'un risque de régression qui,
lui, serait réel à 15 jours de l'oral.

## 1. Chargement DWH : inserts par lots plutôt que `COPY` natif

**Constat** : `etl/dwh/dwh_utils.write_to_dwh()` charge chaque table via
`pandas.DataFrame.to_sql(if_exists="replace", method="multi", chunksize=5000)`
— des `INSERT` par lots de 5000 lignes via psycopg2, pas la commande
`COPY` native de PostgreSQL (ordres de grandeur plus rapide pour du chargement
en masse).

**Mesuré cette nuit** : le chargement de `mart.fact_claim_scoring_features`
(367 464 lignes) a pris ~15 minutes de calcul pandas + insertion. Sur un
DWH assurantiel réel (plusieurs millions de sinistres), ce temps croîtrait
au moins linéairement, probablement plus vite (index, contraintes, réseau).

**Piste** : remplacer `to_sql` par un `COPY` via `psycopg2.copy_expert`
(export du DataFrame en CSV en mémoire, chargement en une passe). Gain
attendu : x5 à x20 sur les tables volumineuses, sans changer la logique
métier des loaders — un changement isolé dans `dwh_utils.py`.

## 2. Chaîne mart : séquentielle, pas de parallélisation

**Constat** : `etl/orchestrate_full_recompute.py::MART_CHAIN` exécute ses
8 étapes une par une (`compute_claim_scoring_features_v1` →
`compute_claim_business_rule_signals_v1_candidate` → ... → `compute_vhs_v4`).
Certaines sont indépendantes (ex. `compute_vhs_v4` ne dépend d'aucune
étape claim-scoring — voir le docstring ajouté dans l'orchestrateur le
2026-08-07) mais tournent quand même en série.

**Mesuré cette nuit** : durée totale de la chaîne mart = 5 897 secondes
(~1h38), dont `compute_claim_scoring_features_v1` (1811s),
`compute_claim_business_rule_signals_v1_candidate` (1201s),
`compute_claim_attention_hybrid_score_v1_candidate` (1171s) et
`compute_claim_ml_anomaly_signal_v1_candidate` (908s, incluant
l'entraînement d'un Isolation Forest sur 367 464 lignes à chaque run).

**Piste** : paralléliser les étapes indépendantes (VHS vs chaîne
claim-scoring) via Airflow (déjà l'outil d'orchestration du projet — deux
branches de tâches au lieu d'une chaîne linéaire dans le DAG). Ne
paralléliserait pas la chaîne claim-scoring elle-même (dépendances
séquentielles réelles entre features → règles → hybride → hybride ML),
mais gagnerait le temps de VHS (8s, négligeable) en parallèle — gain
marginal ici, mais le principe s'applique mieux à de futurs signaux
indépendants.

## 3. Recalcul complet uniquement — pas de chargement incrémental

**Constat** : chaque étape DWH et mart recharge l'intégralité de la table
(`if_exists="replace"`), même si seules quelques centaines de lignes ont
changé depuis le dernier run. Il n'existe pas de mécanisme de delta/CDC
(*change data capture*).

**Pourquoi c'est un choix délibéré et pas un oubli** : au volume actuel,
un recalcul complet garantit qu'aucune incohérence ne peut s'accumuler
silencieusement (une ligne mal mise à jour dans un delta serait invisible ;
un replace complet la corrige automatiquement à chaque run). C'est un choix
de simplicité et de fiabilité, cohérent avec les contrôles métier finaux
de l'orchestrateur (`_run_final_business_checks`).

**Piste à plus grande échelle** : un chargement incrémental (fenêtre
glissante sur `date_modification`, ou CDC via triggers/Debezium) deviendrait
nécessaire au-delà d'un certain volume, où un recalcul complet ne tiendrait
plus dans une fenêtre de maintenance nocturne.

## 4. Fragilité des contraintes PK/FK sous replace-mode (déjà corrigée, mentionnée pour mémoire)

**Constat, corrigé le 2026-08-07** (voir tâche 3.3 du plan) : le mode
replace de `to_sql` supprime les contraintes PK/FK à chaque rechargement ;
`etl/dwh/add_dwh_relations.sql` les réapplique, mais n'était pas câblé
automatiquement dans l'orchestrateur — ce qui bloquait tout recalcul
complet après la première application manuelle des contraintes. Corrigé et
validé par un run complet réussi.

**Pourquoi ça reste une limite structurelle à connaître** : ce n'est pas un
bug isolé, c'est une conséquence du choix "replace complet" (point 3
ci-dessus). Tant que le pipeline recharge des tables entières par
DROP/CREATE, toute contrainte doit être explicitement redéposée après coup
— une classe de fragilité qui disparaîtrait avec un chargement incrémental
(UPDATE/INSERT ne cassent pas les contraintes existantes).

## 5. Résilience de l'exécution longue durée

**Constat** : le recalcul complet prend ~1h45 de bout en bout (DWH +
scoring + VHS + vues). Un processus de cette durée, lancé manuellement ou
via un terminal, est vulnérable à une interruption externe (fermeture de
session, coupure réseau, redémarrage machine) — observé concrètement cette
nuit (deux tentatives interrompues par l'environnement d'exécution avant
qu'une troisième aboutisse).

**Mitigation déjà en place** : le comportement fail-fast de l'orchestrateur
restaure les vues Power BI en best-effort à tout échec détecté (voir
`_restore_views_best_effort`), donc une interruption *propre* (le process
reçoit une erreur et se termine normalement) ne laisse jamais la base sans
couche de restitution. Une interruption *brutale* (kill du process, comme
observé cette nuit) contourne ce filet de sécurité — c'est ce qui explique
pourquoi les vues sont restées supprimées deux fois avant d'être restaurées
manuellement.

**Piste** : exécuter le recalcul via Airflow (déjà en place,
`airflow/dags/iris_full_pipeline.py`) plutôt qu'en ligne de commande directe
pour les runs de production — Airflow persiste l'état de la tâche et permet
une reprise, alors qu'un process tué en ligne de commande ne laisse aucune
trace de son état d'avancement.

## Phrase jury

> « Le pipeline actuel est fiable au volume d'aujourd'hui — on l'a prouvé
> cette nuit avec un recalcul complet réussi. On sait déjà où sont les
> limites de passage à l'échelle : le chargement par lots plutôt que par
> `COPY` natif, l'absence de chargement incrémental, l'exécution
> séquentielle de la chaîne de scoring. Ce sont des choix de simplicité
> assumés à ce stade du projet, pas des angles morts — et voici comment on
> les résoudrait si le volume l'exigeait. »
