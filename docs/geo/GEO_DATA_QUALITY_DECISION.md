# GEO Data Quality Decision

## Decision candidate

Statut actuel : GEO_PARTIAL.

Le depot contient deja une base GEO exploitable : documentation d'inventaire, specification de normalisation, scripts d'audit, outils de resolution et tests dedies. Le lot ne doit donc pas etre recommence. Il doit etre consolide par des mesures de qualite et par une decision explicite avant toute contribution geographique au Claim Attention Score V2.

## Elements existants constates

- Documentation GEO sous `docs/geo/`.
- Normalisation sous `etl/utils/geo_normalization.py`.
- Chargement dimensionnel sous `etl/dwh/load_dim_geo.py`.
- Audits candidats sous `etl/dwh/geo_audit_tools/`.
- Tests GEO existants sous `tests/test_geo_*.py` et `tests/test_load_dim_geo_resolution.py`.

## Conditions pour passer a GEO_READY

- Taux de mapping documente pour gouvernorat, delegation, localite, agence et region.
- Valeurs UNKNOWN et non mappees quantifiees.
- Doublons et libelles divergents documentes.
- Agences sans rattachement region identifiees.
- Regles de fallback explicites.
- Aucun code geographique perdu silencieusement.
- Tests GEO existants au vert.

## Conditions de blocage

Le statut doit rester GEO_PARTIAL ou GEO_BLOCKED si les mesures de couverture ne permettent pas de distinguer clairement :

- donnees absentes ;
- donnees non mappees ;
- libelles divergents ;
- conflit de rattachement agence-region ;
- migration ou source historique non comparable.

## Regle metier

Une difference geographique ne constitue pas une conclusion. Elle peut uniquement produire un contexte formule comme : situation geographique a examiner.

## Prochaine action

Generer ou completer `reports/geo/geo_quality_summary.csv` a partir des audits read-only existants, puis documenter le passage eventuel de GEO_PARTIAL a GEO_READY.
