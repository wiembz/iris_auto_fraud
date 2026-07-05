# Plan d'audit ETL GEO

## Objectif

L'objectif de cette premiere etape est de comprendre l'architecture actuelle de la chaine GEO du projet IRIS Auto Fraud Decision Platform, sans modifier les traitements existants. L'audit vise a identifier les fichiers, tables, colonnes, referentiels et rapports qui manipulent les notions de region, agence, gouvernorat, delegation, localite, adresse, lieu de sinistre, code postal et cle GEO.

Le resultat attendu est une base documentaire claire pour decider ensuite ou normaliser, ou auditer, et ou conserver les corrections metier.

## Perimetre

L'audit couvre uniquement les elements lies a la geographie dans le projet :

- sources staging issues de `Sinistres`, `Clients` et `Production` ;
- scripts ETL DWH qui construisent `dim_geo`, `dim_client`, `fact_sinistre`, `fact_contrat` et les dimensions connexes ;
- scripts d'audit GEO existants ;
- fichiers de reference GEO et postale ;
- rapports qualite GEO ;
- documentation de modelisation mentionnant la geographie.

## Exclusions

Cette etape exclut volontairement :

- toute modification du module VHS ;
- toute modification de `etl/mart/compute_vhs_v3_candidate.py` ;
- toute modification de `docs/vhs/` ;
- toute ecriture en base de donnees ;
- toute correction automatique des donnees metier ;
- toute creation de score fraude ou modele ML ;
- toute refonte massive des scripts ETL.

## Regles de securite

L'audit est read-only cote donnees et base PostgreSQL. Les scripts existants ne doivent pas etre executes s'ils contiennent des operations d'ecriture ou de chargement DWH.

Les requetes SQL fournies sont uniquement des `SELECT`. Elles servent a diagnostiquer les nulls, `UNKNOWN`, doublons, incoherences et ruptures de referentiel.

## Decision d'architecture GEO

La normalisation GEO doit commencer des le staging pour les corrections techniques sures :

- `TRIM` des chaines ;
- casse uniforme ;
- chaines vides converties en `NULL` ;
- standardisation des valeurs `UNKNOWN` ;
- nettoyage des doubles espaces ;
- conservation des valeurs brutes dans des colonnes `*_raw` ;
- creation de colonnes normalisees `*_norm`.

Les corrections metier doivent rester dans les referentiels, dimensions ou couches d'audit controlees :

- rattachement agence / region ;
- mapping gouvernorat / delegation / localite ;
- correction d'un lieu ambigu ;
- deduction a partir d'une adresse libre ;
- validation d'un code postal a partir d'une reference officielle.

Cette separation evite de masquer les erreurs de saisie manuelle dans le staging tout en produisant un DWH lisible et defendable.

## Methode d'audit

1. Inventorier les fichiers contenant des termes GEO.
2. Identifier les scripts ETL qui manipulent clients, sinistres, contrats, production, agences et regions.
3. Relever les tables staging, DWH, facts, dimensions et rapports cites dans le code.
4. Relever les colonnes GEO detectees dans les scripts et configurations.
5. Produire des requetes SQL read-only pour mesurer la qualite effective en base.
6. Documenter les risques avant toute correction.

## Livrables attendus

- `docs/geo/geo_etl_audit_plan.md`
- `docs/geo/geo_etl_file_inventory.md`
- `docs/geo/geo_dwh_table_inventory.md`
- `docs/geo/geo_data_quality_audit.md`
- `docs/geo/sql/001_geo_audit_readonly.sql`
