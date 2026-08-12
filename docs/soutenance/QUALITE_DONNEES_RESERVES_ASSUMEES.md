# Qualité des données : ce qui a été corrigé vs. ce qui reste une réserve documentée

> Vérifié le 07/08/2026 directement contre les rapports d'audit et la base —
> chiffres identiques à l'audit du 07/08 qui a servi de base au plan, aucune
> dérive depuis.

## Principe

Une plateforme de decision qui prétend n'avoir **aucune** anomalie de
données sur 585 514 contrats et 381 893 sinistres serait suspecte, pas
rassurante. La bonne réponse au jury n'est pas « il n'y a aucun problème »,
c'est « voici ce qu'on a corrigé, voici ce qu'on a mesuré et laissé en
réserve documentée parce que ce n'est ni bloquant ni de notre ressort, et
voici comment on le sait ».

## Ce qui a été corrigé (ne pas re-présenter comme un problème ouvert)

- Le bug de parsing de dates YYYYMMDD (voir `docs/soutenance/PLAN_15_JOURS_VERS_EXCELLENCE.md` §2.1) — corrigé, testé (25 tests).
- Le bug de saturation VHS V3→V4 (voir `docs/vhs/vhs_validation_summary.md`) — corrigé, comparé chiffre à chiffre.
- L'over-immobilisation VHS V2→V3 (motor oil gating) — corrigé.

## Réserves documentées, non-bloquantes (anomalies de la donnée source, pas du pipeline)

| Anomalie | Volume | % | Cause |
|---|---:|---:|---|
| `fact_contrat` : date de fin d'effet antérieure à la date de début d'effet | 49 979 / 585 514 | 8,54 % | Anomalie source (saisie contractuelle amont) |
| `fact_contrat` : prime totale négative | 40 | <0,01 % | Anomalie source |
| `fact_sinistre` : montant de charge sinistre négatif | 32 | <0,01 % | Anomalie source |
| `fact_sinistre` : montant de réserve négatif | 17 | <0,01 % | Anomalie source |
| `fact_sinistre` : date de déclaration manquante | 9 | <0,01 % | Anomalie source |
| `dwh.dim_geo` : zones résolues en qualité PARTIAL (pas VALIDATED) | 163 / 1 856 | 8,78 % | Adresse source insuffisamment précise pour résolution complète |

**Pourquoi ce sont des réserves et pas des bugs à corriger** : dans les 6 cas,
le pipeline IRIS a correctement **identifié, quantifié et tracé** l'anomalie
(rapports dans `data/quality_reports/fact_contrat/`,
`data/quality_reports/fact_sinistre/`) — il ne l'a ni masquée ni propagée
silencieusement dans un score. Corriger la donnée source (ressaisie
contractuelle, complément d'adresse) est hors du périmètre du pipeline de
scoring : ce serait un projet de qualité de données côté système source BNA,
pas une tâche IRIS.

**Distinct de l'attendu** : `fact_sinistre.date_cloture` manquante sur
103 231 lignes (27 % de la table) n'est **pas** une anomalie — c'est
structurel : un sinistre encore ouvert n'a pas de date de clôture. Déjà
documenté et couvert par `expected_unknown_rate_documented` dans l'audit FK
(`data/quality_reports/etl_quality/latest/fk_coverage.csv`). Ne pas le
présenter comme un problème si le jury le croise.

## Phrase jury

> « Sur 585 000 contrats et 382 000 sinistres, on a documenté chaque
> anomalie de données source, mesuré son volume exact, et tracé pourquoi
> elle est en dessous du seuil qui justifierait un blocage du pipeline.
> Ce qu'on n'a pas fait, c'est corriger la donnée source elle-même — ce
> n'est pas notre périmètre, c'est celui des systèmes amont de BNA. »

## Si le jury demande « pourquoi ne pas les avoir juste exclues ? »

Exclure ces lignes fausserait les volumétries et les KPIs métier (ex. la
prime totale) sans résoudre le problème à la source — et créerait un écart
silencieux entre le DWH et les systèmes sources de BNA, rendant les deux
irréconciliables lors d'un contrôle. Documenter et laisser visible est le
choix le plus auditable.
