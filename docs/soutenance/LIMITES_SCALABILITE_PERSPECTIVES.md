# Limites de scalabilité connues et pistes d'amélioration

> Écrit le 08/08/2026, à partir d'observations directes faites en exécutant
> le pipeline complet la nuit précédente (task 3.3 du plan de soutenance) —
> pas des suppositions.
>
> **Mise à jour du 08/08/2026** : 3 des 5 points ci-dessous (1, 2, 5) ont
> finalement été corrigés le jour même, sur demande explicite — chacun
> validé par un run réel réussi avant d'être considéré fait. Restent en
> l'état, par choix documenté et non par oubli : le point 3 (chargement
> incrémental — hors de portée en 15 jours, refonte d'architecture) et le
> point 4 (déjà réglé lors de la tâche 3.3, gardé ici pour le contexte).

## Pourquoi documenter d'abord, corriger ensuite au cas par cas

Le projet fonctionne correctement au volume actuel (~382 000 sinistres,
~586 000 contrats, 284 inspections). Les limites ci-dessous sont des
questions de **passage à l'échelle** (10x, 100x le volume), pas des bugs
qui affectent la fiabilité aujourd'hui — le recalcul complet réussi cette
nuit (`docs/soutenance/PLAN_15_JOURS_VERS_EXCELLENCE.md`, tâche 3.3) le
prouve. La démarche suivie : documenter d'abord (zéro risque), puis
évaluer chaque correction individuellement selon son rapport effort/risque
avant de toucher au code — pas de refonte générale précipitée à 15 jours
de l'oral. Les 3 corrections faites (1, 2, 5) avaient chacune un risque
mesuré et contenu ; le chargement incrémental (3) a été explicitement
exclu car hors de portée dans ce délai.

## 1. Chargement DWH : inserts par lots plutôt que `COPY` natif — ✅ CORRIGÉ le 08/08/2026

**Constat initial** : `etl/dwh/dwh_utils.write_to_dwh()` chargeait chaque
table via `pandas.DataFrame.to_sql(if_exists="replace", method="multi",
chunksize=5000)` — des `INSERT` par lots de 5000 lignes via psycopg2, pas
la commande `COPY` native de PostgreSQL.

**Mesuré la veille** : le chargement de `mart.fact_claim_scoring_features`
(367 464 lignes) avait pris ~15 minutes de calcul pandas + insertion.

**Correction appliquée** : `write_to_dwh()` crée maintenant le schéma via
`to_sql` sur un DataFrame vide (0 ligne, rapide, dtypes corrects), puis
charge les données via `COPY` natif (`psycopg2.copy_expert`) — même
idiome déjà utilisé dans les scripts mart scoring
(`compute_claim_attention_hybrid_score_v1_candidate.py` et consorts).
Validé avant commit par un test round-trip isolé (2000 lignes avec valeurs
adversariales : accents, apostrophes, tabulations/retours à la ligne dans
le texte, NULL/NaN, précision flottante — hash de contenu identique avant
et après), puis par un chargement réel (`load_dim_date.py`,
`load_dim_client.py`) contre le DWH vivant : comptages et lignes
échantillonnées identiques, 264 tests toujours verts.

## 2. Chaîne mart : séquentielle, pas de parallélisation — ✅ CORRIGÉ le 08/08/2026 (gain marginal, fait sur demande explicite)

**Constat initial** : `etl/orchestrate_full_recompute.py::MART_CHAIN` exécutait
ses 8 étapes une par une. `compute_vhs_v4` est indépendant de la chaîne
claim-scoring (lit `dwh.fact_inspection_vehicule/checkpoint`, écrit
`mart.fact_vhs_score/penalty_detail` — aucune table partagée) mais tournait
quand même en dernier, en série.

**Mesuré la veille** : durée totale de la chaîne mart = 5 897 secondes
(~1h38), dont `compute_claim_scoring_features_v1` (1811s),
`compute_claim_business_rule_signals_v1_candidate` (1201s),
`compute_claim_attention_hybrid_score_v1_candidate` (1171s) et
`compute_claim_ml_anomaly_signal_v1_candidate` (908s, incluant
l'entraînement d'un Isolation Forest sur 367 464 lignes à chaque run) —
`compute_vhs_v4` lui-même ne prend que ~16-20s : le gain de la
parallélisation est donc marginal (<0,5% du temps total), signalé comme
tel avant de l'implémenter, sur demande explicite.

**Correction appliquée** : `compute_vhs_v4` est lancé en tâche de fond
(`subprocess.Popen`) dès le début de la chaîne mart et rejoint juste avant
`create_powerbi_views`, qui dépend des deux chaînes. Validé par un run
réel où les logs confirment un démarrage à la même seconde pour
`compute_vhs_v4` et l'étape séquentielle en cours, et où l'orchestrateur a
correctement attendu la fin de VHS avant de poursuivre — `statut global :
SUCCES`, données vérifiées identiques après coup.

**Ce qui reste vrai** : la chaîne claim-scoring elle-même (features →
règles → ML → hybride → hybride ML) garde des dépendances séquentielles
réelles et n'est pas parallélisable sans changer la logique métier. Le
principe s'appliquerait mieux à de futurs signaux indépendants qu'à cette
chaîne actuelle.

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

## 5. Résilience de l'exécution longue durée — ✅ CORRIGÉ (partiellement) le 08/08/2026

**Constat initial** : le recalcul complet prend ~1h45 de bout en bout (DWH
+ scoring + VHS + vues). Un processus de cette durée, lancé manuellement ou
via un terminal, est vulnérable à une interruption externe (fermeture de
session, coupure réseau, redémarrage machine) — observé concrètement à
plusieurs reprises pendant cette session (process tués silencieusement par
l'environnement d'exécution, sans rapport avec le code du projet).

**Mitigation déjà en place avant correction** : le comportement fail-fast
de l'orchestrateur restaure les vues Power BI en best-effort à tout échec
*détecté* (`_restore_views_best_effort`) — une interruption *propre* ne
laisse jamais la base sans couche de restitution. Une interruption
*brutale* (kill du process) contourne ce filet de sécurité, ce qui a
nécessité une restauration manuelle des vues à plusieurs reprises cette
nuit.

**Correction appliquée** : ajout d'un flag `--mart-from <etape>` à
`orchestrate_full_recompute.py`, sur le même principe que le `--from` déjà
existant de `load_all_dwh.py`. Permet de reprendre la chaîne mart à
n'importe quelle étape après une interruption, sans refaire les étapes
déjà réussies (chaque étape mart est additive — la rejouer ne corromprait
rien, mais coûte du temps). Validé par un run réel interrompu puis repris :
`--mart-from compute_vhs_v4` a sauté les 7 étapes précédentes et terminé
en 179s (au lieu de 5897s pour la chaîne complète), avec `statut global :
SUCCES` et tous les contrôles métier finaux passés.

**Ce qui reste vrai** : ceci ne couvre que la chaîne mart, pas les 18
étapes de `load_all_dwh.py` (qui a déjà son propre `--from`, non testé
dans cette session) ni une reprise *automatique* — il faut relire le log
pour savoir où reprendre manuellement. Une vraie persistance d'état
(comme le permettrait Airflow, déjà en place via
`airflow/dags/iris_full_pipeline.py`, pour les runs de production) irait
plus loin : reprise automatique sans intervention humaine pour identifier
la dernière étape réussie.

## Phrase jury

> « Le pipeline actuel est fiable au volume d'aujourd'hui — on l'a prouvé
> avec plusieurs recalculs complets réussis. On avait identifié 5 limites de
> passage à l'échelle ; 3 ont été corrigées et validées par des runs réels
> (chargement `COPY` natif, parallélisation VHS, reprise après interruption),
> une reste hors de portée en 15 jours par choix assumé (chargement
> incrémental — refonte d'architecture), une dernière était déjà réglée en
> amont. Ce ne sont pas des angles morts découverts en urgence : c'est une
> démarche d'amélioration continue documentée et mesurée, pas juste promise. »
