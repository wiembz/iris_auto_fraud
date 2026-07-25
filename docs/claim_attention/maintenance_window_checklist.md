# Checklist fenêtre de maintenance — recalcul `iris_auto_fraud` (correctif conducteur)

À suivre avant d'exécuter `python etl/orchestrate_full_recompute.py --confirm-db iris_auto_fraud`.
Le rechargement DWH utilise `DROP TABLE` (mode replace) : toute connexion active pendant le run
verrait des tables disparaître, et Power BI/l'application liraient des résultats partiels ou
obtiendraient des erreurs.

## Contrôles automatisés (déjà intégrés dans l'orchestrateur)
- [x] L'orchestrateur refuse de démarrer si `--confirm-db` ne correspond pas à la base réelle.
- [x] L'orchestrateur refuse de démarrer si `pg_stat_activity` détecte une autre connexion active
      sur la base (backend Flask, psql/pgAdmin ouvert, refresh Power BI en cours...).
- [x] Contrôles métier finaux automatiques après le recalcul (dossier de référence, stabilité du
      nombre de sinistres notés, bornes sur la population conducteur).

## À faire manuellement avant le lancement (hors du contrôle de ce dépôt)
- [ ] **Power BI** : désactiver ou reporter tout refresh planifié (Power BI Service / Gateway) qui
      pointe sur `iris_auto_fraud`, le temps du recalcul (durée observée sur la copie : ~91 min).
- [ ] **Application** : arrêter le backend Flask (`python backend/app.py` ou équivalent) et le
      frontend Angular en dev (`npm start` / `ng serve`) s'ils tournent, ou s'assurer qu'aucun
      utilisateur n'est en train de consulter un dossier.
- [ ] **Outils SQL** : fermer toute session psql/pgAdmin/DBeaver ouverte sur `iris_auto_fraud`.
- [ ] **Fenêtre horaire** : prévoir au moins 2h de marge (91 min observées sur la copie + marge pour
      une base légèrement plus grosse en production).
- [ ] Après le lancement : relancer le backend/frontend et réactiver le refresh Power BI seulement
      après confirmation du statut SUCCES de l'orchestrateur.

## En cas d'échec pendant le run
- L'orchestrateur est fail-fast : il s'arrête à la première étape en échec et tente de restaurer les
  vues Power BI automatiquement (`etl/powerbi/create_powerbi_views.py`).
- Si la restauration des vues échoue aussi, la base est dans un état incomplet : ne PAS relancer
  Power BI ni l'application avant restauration depuis la sauvegarde (voir procédure de restauration
  dans le rapport de sauvegarde correspondant).
