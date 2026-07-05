# Rapport initial d'audit qualite GEO

## Objectif du rapport

Ce document prepare les controles qualite a executer sur la chaine GEO sans modifier les donnees. Il sert a mesurer les risques avant toute correction ETL.

## Controles a executer

Les controles prioritaires sont :

- lister toutes les colonnes GEO presentes en base via `information_schema` ;
- mesurer les valeurs `NULL`, vides et `UNKNOWN` dans les colonnes GEO sources et finales ;
- detecter les doublons de cles fonctionnelles comme `geo_key` ;
- verifier les lignes sinistre sans rattachement `geo_sinistre_sk` fiable ;
- detecter les codes agence ou intermediaire rattaches a plusieurs regions ;
- detecter les codes presents dans les faits mais absents des dimensions ;
- comparer les anomalies avant/apres 2019 si la date sinistre est disponible.

## Valeurs manquantes

Colonnes a verifier en priorite :

- `staging.stg_sinistres.regsini`
- `staging.stg_sinistres.gouvsini`
- `staging.stg_sinistres.citesini`
- `staging.stg_sinistres.cpostsini`
- `dwh.dim_geo.region`
- `dwh.dim_geo.gouvernorat`
- `dwh.dim_geo.localite`
- `dwh.dim_geo.code_postal`
- `dwh.fact_sinistre.geo_sinistre_sk`
- colonnes agence/intermediaire si presentes dans `dwh.dim_intermediaire`.

## Valeurs UNKNOWN

Les `UNKNOWN` sont acceptables uniquement s'ils representent une absence reelle, une ambiguite documentee ou la ligne technique. Ils deviennent un risque lorsque :

- une localite connue existe mais le gouvernorat reste `UNKNOWN` ;
- un code postal seul existe sans region/gouvernorat/localite ;
- une ligne finale DWH est exploitable analytiquement mais conserve trop d'inconnues ;
- le rapport qualite n'explique pas pourquoi la valeur reste inconnue.

## Doublons

Doublons a controler :

- `dwh.dim_geo.geo_key` ;
- codes agences/intermediaires si une dimension agence existe ;
- combinaisons `source_geo_key -> resolved_geo_key` dans le mapping GEO ;
- rattachements multiples d'une agence vers plusieurs regions.

## Incoherences agence / region

A verifier si les colonnes existent :

- meme code agence rattache a plusieurs regions ;
- meme intermediaire rattache a plusieurs delegations sans periode de validite ;
- faits contrats ou sinistres contenant un code absent de la dimension intermediaire ;
- ruptures de codification autour de 2019.

## References non mappees

Les references a auditer :

- reference administrative tunisienne ;
- reference postale ;
- alias geographiques ;
- corrections approuvees ;
- corrections postales approuvees ;
- rapports de conflits et unresolved.

Une valeur non mappee ne doit pas etre forcee. Elle doit rester documentee jusqu'a validation metier.

## Impact migration 2019

L'audit doit comparer les donnees avant/apres 2019 pour verifier si une migration, une refonte de codification ou un changement de saisie a modifie :

- le taux de `NULL` ;
- le taux de `UNKNOWN` ;
- la couverture `geo_sinistre_sk` ;
- la distribution des regions/gouvernorats ;
- les codes agence/intermediaire ;
- les references non mappees.

## Résultats initiaux de couverture GEO par période

Ces résultats proviennent des requêtes SQL read-only exécutées sur `staging.stg_sinistres`. Les alias exacts des quatre champs incomplets n'étant pas encore confirmés dans le résultat source transmis, ils sont documentés sous forme générique :

- `champ_geo_incomplet_1`
- `champ_geo_incomplet_2`
- `champ_geo_incomplet_3`
- `champ_geo_incomplet_4`

Aucune correction métier ne doit être déduite uniquement de ces volumes sans validation des alias exacts.

### Volumes confirmés

| Période | Total sinistres | champ_geo_incomplet_1 | champ_geo_incomplet_2 | champ_geo_incomplet_3 | champ_geo_incomplet_4 |
|---|---:|---:|---:|---:|---:|
| Global | 381 893 | 62 465 | 25 247 | 18 924 | 0 |
| BEFORE_2019 | 74 678 | 4 588 | 13 409 | 0 | 0 |
| FROM_2019 | 307 215 | 57 877 | 11 838 | 18 924 | 0 |

### Taux d'incomplétude

| Période | champ_geo_incomplet_1 | champ_geo_incomplet_2 | champ_geo_incomplet_3 | champ_geo_incomplet_4 |
|---|---:|---:|---:|---:|
| Global | 16,36 % | 6,61 % | 4,96 % | 0,00 % |
| BEFORE_2019 | 6,14 % | 17,96 % | 0,00 % | 0,00 % |
| FROM_2019 | 18,84 % | 3,85 % | 6,16 % | 0,00 % |

### Interprétation prudente

- `champ_geo_incomplet_1` est davantage incomplet après 2019 : 18,84 % depuis 2019 contre 6,14 % avant 2019.
- `champ_geo_incomplet_2` est davantage incomplet avant 2019 : 17,96 % avant 2019 contre 3,85 % depuis 2019.
- `champ_geo_incomplet_3` présente un comportement spécifique à la période post-2019 : aucun cas avant 2019, puis 18 924 cas depuis 2019.
- `champ_geo_incomplet_4` ne remonte aucun cas incomplet dans les résultats confirmés.

### Lecture métier provisoire

Ces résultats constituent un signal de qualité à examiner. Ils peuvent indiquer un effet migration, un changement de codification ou une évolution de la saisie après 2019. Cependant, aucune conclusion définitive ne doit être formulée sans validation des alias exacts correspondant aux quatre champs incomplets.

Pour l'étape suivante, les requêtes SQL doivent produire des alias explicites et lisibles, par exemple `gouvsini_incomplet`, `citesini_incomplet`, `cpostsini_incomplet` et `iddelega_incomplet` lorsque ces colonnes correspondent réellement au contrôle exécuté.

## Risques pour Power BI

Risques principaux :

- filtres regionaux incomplets si `region` ou `gouvernorat` restent inconnus ;
- cartes ou visuels geographiques trompeurs en cas de code postal non valide ;
- double comptage si une agence est rattachee a plusieurs regions ;
- rupture temporelle invisible autour de 2019 ;
- confusion entre geographie client, geographie sinistre et geographie agence.

## Recommandations provisoires

- Garder les corrections techniques sures au staging avec colonnes brutes et normalisees.
- Garder les corrections metier dans des references versionnees et des dimensions controlees.
- Ne jamais corriger une localite ambigue sans preuve ou approbation.
- Ne pas melanger geographie client et geographie sinistre.
- Documenter chaque `UNKNOWN` significatif dans un rapport qualite.
- Valider separement la logique agence/region avant integration Power BI.
