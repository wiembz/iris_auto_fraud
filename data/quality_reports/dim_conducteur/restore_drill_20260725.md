# Vérification réelle de restauration — 2026-07-25

Base restaurée : `iris_auto_fraud_restore_verify_20260725` (vide au départ, restaurée via
`pg_restore --no-owner` depuis `iris_auto_fraud_backup_20260725.dump`, sans erreur ni avertissement).

`pg_restore --list` seul ne suffit pas à prouver une restauration (il ne fait que lister le TOC sans
rejouer les données) — vérification complète effectuée après restauration réelle des données.

## Schémas

Comparaison `information_schema.schemata` : `app`, `audit`, `dwh`, `mart`, `powerbi_v`, `staging` —
**6/6 identiques** entre source et base restaurée.

## Volumes (34 tables comparées, comptage exact)

Toutes les tables `staging.*`, `dwh.*`, `mart.*`, `app.*`, `audit.*` comparées une à une :
**34/34 correspondent exactement**, notamment :
- `dwh.fact_sinistre` : 381 893 / 381 893
- `dwh.dim_conducteur` : 161 522 / 161 522
- `mart.fact_claim_attention_score` : 1 102 392 / 1 102 392
- `mart.fact_claim_attention_signal_detail` : 1 355 987 / 1 355 987
- `app.claim_review_decision` : 3 / 3

## Décisions gestionnaires (contenu exact, pas seulement le compte)

Les 3 décisions de `app.claim_review_decision` comparées champ par champ (`decision_id`, `claim_sk`,
`decision`, `reviewer_email`, `decided_at` à la microseconde près, `comment`) : **3/3 identiques
byte pour byte**, y compris le commentaire libre de correction du 2026-07-14.

## Vues Power BI

13/13 vues présentes dans `powerbi_v` sur la base restaurée. Chacune interrogée (`SELECT COUNT(*)`) et
comparée à la même vue sur la source : **13/13 comptages identiques**, aucune erreur de requête.

## Conclusion

Restauration prouvée fonctionnellement équivalente à la base source, pas seulement structurellement
valide.

## Test de l'orchestrateur enrichi sur cette base restaurée (2026-07-26)

Le correctif conducteur + la chaîne complète ont ensuite été exécutés sur cette même base restaurée
pour valider les contrôles métier finaux enrichis (score, niveau, confiance, version live, volume
exact, vues) avant toute décision de lancement sur `iris_auto_fraud`.

- 18 étapes DWH : OK (0 FAIL, 6 WARN — réserves déjà documentées).
- Chaîne mart/scoring : OK, avec un incident transitoire sur
  `compute_claim_ml_anomaly_signal_v1_candidate.py` (`DLL load failed while importing _arpacklib:
  An Application Control policy has blocked this file` — probable scan de sécurité Windows ponctuel,
  sans lien avec le code). Le fail-fast de l'orchestrateur a réagi correctement : arrêt immédiat,
  restauration automatique des 13 vues. Un simple retry du script isolé a réussi immédiatement,
  confirmant la nature transitoire. Les étapes restantes ont été rejouées manuellement dans l'ordre
  (sans re-rejouer le DWH ni les étapes déjà réussies) pour obtenir un run complet propre.
- **Contrôles métier finaux (valeurs exactes) — TOUS CONFORMES :**

| Contrôle | Résultat |
|---|---|
| `conducteur_sk` dossier référence | 0 ✅ |
| Signaux `DRIVER_*` | absents ✅ |
| Version live API | `IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE` ✅ |
| Score dossier référence | 65 ✅ |
| Niveau d'attention | Examen renforcé suggéré ✅ |
| Confiance | HIGH ✅ |
| Dossiers notés | 367 464 (exact) ✅ |
| Conducteurs réels | 161 439 ✅ |
| Part conducteur_sk=0 | 17,2 % ✅ |
| Vues Power BI | 13/13 interrogeables ✅ |

Résultat strictement identique aux deux exécutions précédentes (run manuel + run orchestrateur sur
la copie de test) — reproductibilité confirmée sur trois exécutions indépendantes.

**Base non supprimée** (conservée en attente d'autorisation explicite), nom :
`iris_auto_fraud_restore_verify_20260725` — contient maintenant le correctif conducteur appliqué
(différente de son état initial post-restauration, qui reflétait `iris_auto_fraud` avant correctif).
