# Rapport final — correctif conducteur_sk, simulation et outillage (2026-07-25)

Statut : **validé sur copie (`iris_auto_fraud_test_20260724`), non appliqué sur `iris_auto_fraud`**.
Deux exécutions indépendantes (manuelle puis via l'orchestrateur `etl/orchestrate_full_recompute.py`)
produisent des résultats identiques.

## 1. Décomposition complète du score 80 → 65 (dossier claim_sk=14188)

Source : `mart.fact_claim_attention_signal_detail`, comparaison run `..._20260713_222301` (avant)
vs `..._20260725_092853` (après, orchestrateur).

| Famille de signal | Avant | Après | Détail |
|---|---|---|---|
| ML atypicité calibrée | 10 pts (HIGH) | **7 pts (MEDIUM)** | raw_anomaly_score 0.609→0.541 ; le retrait de `driver_claim_count_12m` change la population de référence de l'Isolation Forest (40 547 dossiers affectés), le percentile de CE dossier baisse sous le seuil HIGH |
| Post-inspection | 15 pts | 15 pts | inchangé |
| Récurrence client | 20 pts | 20 pts | inchangé |
| **Récurrence conducteur** | **12 pts** (10 High + 2 Recent) | **0 pt (absent)** | family_cap=12 (`config/scoring/claim_attention_hybrid_v1_candidate.json`) — la raw candidate_points du sous-signal "Sinistre conducteur précédent récent" était déjà cappée de 5→2 par ce plafond famille, donc la famille ne valait déjà que 12, pas 15 |
| Récurrence véhicule | 15 pts | 15 pts | inchangé |
| Répétition garantie | 8 pts | 8 pts | inchangé |
| **Total** | **80** | **65** | **−12 (famille conducteur) + −3 (repli ML HIGH→MEDIUM) = −15** |

Point clé : la famille "Récurrence conducteur" ne contribuait déjà que 12 pts (pas 15) avant le
correctif, à cause du plafond `family_caps["Recurrence conducteur"]=12`. L'écart de 15 constaté
combine donc deux effets distincts : le retrait complet de cette famille (−12) et un effet de second
ordre sur le signal ML, dont la population de référence change pour tous les dossiers une fois
`driver_claim_count_12m` corrigé (−3 supplémentaires sur ce dossier précis).

## 2. Scripts SQL désormais réellement versionnés

`.gitignore` corrigé (`*.sql` blanket-ignorait tout SQL hors 3 dossiers pré-existants) :
- `!docs/claim_attention/*.sql`
- `!data/quality_reports/powerbi_views/*.sql`
- `!data/quality_reports/dim_conducteur/*.csv` (le rapport d'impact était lui aussi invisible pour git)

Fichiers désormais suivis (`git status` → `??`, prêts à `git add`) :
`docs/claim_attention/claim_sk_14188_control_queries.sql`,
`data/quality_reports/powerbi_views/*.sql`,
`data/quality_reports/dim_conducteur/*.csv`,
`etl/dwh/audit_dim_conducteur_impact.py`, `etl/orchestrate_full_recompute.py`,
`tests/test_load_dim_conducteur.py`.
**Rien n'a été commit** (aucune demande explicite de commit).

## 3. Sauvegarde PowerBI complétée

`data/quality_reports/powerbi_views/powerbi_v_backup_manifest_20260724.md` (manifeste enrichi) +
`powerbi_v_definitions_backup_20260725_080201.sql` (capture fraîche générée automatiquement par
l'orchestrateur avant son propre drop) :
- **Propriétaire** : `postgres` pour les 13 vues et le schéma `powerbi_v` (rôle superuser unique de
  cet environnement local — pas de rôle applicatif PowerBI dédié dans cette base).
- **Permissions** : aucun GRANT explicite au-delà des privilèges implicites du propriétaire ; aucun
  autre grantee.
- **Dépendances** : graphe complet vue→table (dwh/mart) et vue→vue, ordre topologique validé.

## 4. Orchestrateur fail-fast

`etl/orchestrate_full_recompute.py` : garde-fou `--confirm-db` obligatoire (testé : refuse de
démarrer si le nom ne correspond pas à `DB_NAME` résolu depuis `.env`, aucun effet de bord constaté).
Séquence : sauvegarde vues → drop vues → `load_all_dwh.py` → chaîne mart (6 scripts) →
`etl/powerbi/create_powerbi_views.py` (recréation officielle + smoke-test intégré). Fail-fast : arrêt
immédiat + tentative de restauration des vues à la première étape en échec.

## 5. Ré-exécution complète sur la copie

`iris_auto_fraud_test_20260724`, run du 2026-07-25, **exit code 0** :

| Étape | Durée | Statut |
|---|---|---|
| load_all_dwh (18 étapes) | 2536s | OK (0 FAIL, 6 WARN — réserves déjà documentées) |
| compute_claim_scoring_features_v1 | 907s | OK |
| compute_claim_business_rule_signals_v1_candidate | 595s | OK |
| compute_post_inspection_attention_signal_v1_candidate | 42s | OK |
| compute_claim_ml_anomaly_signal_v1_candidate | 963s | OK |
| compute_claim_attention_hybrid_score_v1_candidate | 165s | OK |
| compute_claim_attention_hybrid_ml_score_v1_candidate | 202s | OK |
| ensure_scoring_indexes | 4s | OK |
| create_powerbi_views (13 vues, smoke-test) | 55s | OK |
| **Total** | **5469s (~91 min)** | **SUCCES** |

Résultat sur le dossier de référence, identique à l'exécution manuelle précédente :
`conducteur_sk=0`, score=65, niveau="Examen renforcé suggéré", confiance=HIGH. Les 13 vues
recréées et lisibles.

## 6. Badge qualité et chronologie STAFIM (traités)

**Badge qualité** (`backend/services/claim_review_service.py`) :
- `missing_driver_flag`, `missing_client_flag`, `weak_join_flag` ajoutés au SELECT (ce dernier était
  déjà référencé dans le code mais jamais sélectionné → toujours `False` par défaut, bug latent
  corrigé au passage).
- Nouvelle fonction pure `_confidence_explanation()` : si `missing_driver_flag` ou
  `missing_client_flag`, affiche **"Qualité partielle — conducteur non identifié."** (ou les deux
  gaps listés) au lieu de "Qualité de données optimale", quel que soit `confidence_level` (qui reste
  HIGH car son seuil ne porte pas spécifiquement sur l'identité conducteur).
- Interface TS `ClaimReviewClaim` (`iris-api.service.ts`) complétée avec ces 3 champs.
- 4 tests unitaires ajoutés (`tests/test_backend_readonly_api.py`).

**Chronologie STAFIM** (`backend/services/claim_review_service.py`,
`_timeline_from_feature_and_inspections`) :
- Les lignes de `mart.fact_post_inspection_attention_signal` (une par zone de checkpoint) sont
  désormais regroupées par `inspection_sk` avant de générer les événements de chronologie : **un
  seul événement "Inspection STAFFIM"** par inspection réelle, listant toutes les zones concernées,
  au lieu de 3 événements séparés générant de faux délais "0 jour".
- 2 tests unitaires ajoutés (regroupement + non-fusion d'inspections réellement distinctes).

**Suite de tests complète : 211/211 passent** (205 avant cette session + 6 nouveaux).

## Prochaine étape

Tout est validé sur la copie. Rien n'a été appliqué sur `iris_auto_fraud`. En attente
d'autorisation explicite pour lancer :
```
python etl/orchestrate_full_recompute.py --confirm-db iris_auto_fraud
```
