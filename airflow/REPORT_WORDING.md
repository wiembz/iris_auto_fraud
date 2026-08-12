# Formulation académique pour le rapport

## Statut exact

Apache Airflow est intégré comme couche d'orchestration locale du pipeline
IRIS. Le DAG appelle les points d'entrée Python existants et ne contient
aucune règle de transformation ou de scoring. Cette séparation conserve
l'autonomie et la testabilité des traitements tout en centralisant les
dépendances, les états et les journaux d'exécution.

Le DAG est déclenché manuellement et limité à une seule exécution simultanée,
car le recalcul complet remplace certaines tables et nécessite une fenêtre de
maintenance. Les reprises automatiques sont volontairement désactivées pour
les opérations destructives. La base cible doit être confirmée explicitement
et correspondre à la configuration PostgreSQL avant toute exécution.

## Limite à déclarer

L'environnement fourni repose sur `airflow standalone` et constitue une
intégration locale adaptée à la démonstration et à la validation du PFE. Il ne
doit pas être présenté comme un déploiement de production. Une
industrialisation nécessiterait une base de métadonnées externe, une
authentification adaptée, une stratégie d'alertes, des sauvegardes et une
supervision du scheduler.
