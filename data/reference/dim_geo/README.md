# dim_geo - Tracabilite de nettoyage et normalisation

## Objectif metier

`dwh.dim_geo` represente la localisation du sinistre, pas l'adresse client.
La dimension finale doit rester lisible par le metier, stable pour Power BI, et sans colonnes d'audit.

Structure finale conservee dans `dwh.dim_geo` :

```text
geo_sk
pays
region
gouvernorat
localite
code_postal
geo_quality_level
geo_key
source_system
source_context
created_at
```

## Probleme constate

Les champs source de localisation sinistre viennent de saisie manuelle :

```text
REGSINI
GOUVSINI
CITESINI
CPOSTSINI
```

Les problemes observes etaient :

- valeurs `UNKNOWN`, nulles, numeriques ou non geographiques ;
- gouvernorats mal ecrits ou incomplets ;
- `REGSINI` contenant parfois une delegation/localite au lieu d'une region analytique ;
- localites exploitables avec region/gouvernorat encore inconnus ;
- contradictions entre localite et gouvernorat ;
- codes postaux absents, saisis manuellement ou incoherents ;
- lignes avec code postal seul mais sans region/gouvernorat/localite ;
- doublons fonctionnels apres correction de libelles.

## Solution finale retenue

Le nettoyage est fait avant le chargement final de `dwh.dim_geo`.
Le DWH ne recoit pas les donnees chaotiques puis une correction apres coup.

Pipeline final :

```text
staging.stg_sinistres
  -> extraction geographie sinistre uniquement
  -> normalisation des textes
  -> resolution par referentiel administratif tunisien
  -> application des corrections APPROVED seulement
  -> validation/enrichissement par referentiel postal dedie
  -> application des corrections postales APPROVED par geo_key
  -> recalcul geo_key + geo_quality_level
  -> deduplication par ranking qualite
  -> chargement dwh.dim_geo
```

## Fichiers de reference conserves

```text
data/reference/dim_geo/geo_tunisia_reference.csv
data/reference/dim_geo/geo_tunisia_postal_reference.csv
data/reference/dim_geo/geo_dim_approved_corrections.csv
data/reference/dim_geo/geo_dim_postal_approved_corrections.csv
```

### geo_tunisia_reference.csv

Role : referentiel administratif tunisien de confiance.

Colonnes attendues :

```text
localite
delegation
gouvernorat
region
aliases
confidence
```

`code_postal` peut exister pour compatibilite historique, mais la validation postale finale doit utiliser le referentiel postal dedie.

Utilisation :

- resoudre `region`, `gouvernorat`, `localite` a partir de la localite/delegation/alias ;
- detecter les conflits localite/gouvernorat ;
- fournir la region analytique standard a partir du gouvernorat.

### geo_tunisia_postal_reference.csv

Role : referentiel postal separe, obligatoire pour valider ou enrichir les codes postaux.

Colonnes attendues :

```text
code_postal
bureau_postal
localite
delegation
gouvernorat
region
aliases
source
confidence
```

Etat actuel :

```text
rows loaded : 4833
usable rows : 4833
```

Interpretation : les codes postaux encore `UNKNOWN` sont actuellement une limite de reference postale, pas une erreur du DWH. Aucun code postal n'est invente.

### geo_dim_approved_corrections.csv

Role : corrections validees apres revue humaine/conservative.

Regle stricte :

```text
approval_status = APPROVED uniquement
```

Statuts non appliques :

```text
REJECTED
KEEP_SOURCE
MANUAL_REVIEW
PENDING
```

Les corrections sont matchees par cle metier stable (`geo_key` ou cle source reconstruite), pas par `geo_sk`.

### geo_dim_postal_approved_corrections.csv

Role : corrections postales validees apres mapping des lignes chargees avec `code_postal = UNKNOWN`.

Regle stricte :

```text
approval_status = APPROVED uniquement
```

Etat actuel :

```text
approved postal corrections loaded  : 163
approved postal corrections matched : 163
rows corrected before deduplication : 274
unmatched approved postal corrections: 0
rows corrected by unique localite fallback: 0
global localite rejected due to governorate conflict: 39
```

Ces corrections sont matchees par le `geo_key` metier genere avant deduplication. Elles ne sont pas appliquees par `geo_sk`.

## Ce qui a ete corrige

- `dim_geo` est basee uniquement sur la geographie sinistre, pas sur les adresses client.
- Les valeurs finales ne contiennent pas de NULL : les absences sont standardisees en `UNKNOWN`.
- Les gouvernorats sont normalises vers les 24 gouvernorats officiels tunisiens quand possible.
- Les localites connues sont utilisees en priorite pour remplir region et gouvernorat.
- Les corrections approuvees sont appliquees avant le load final.
- Les conflits localite/gouvernorat sont corriges seulement lorsqu'une reference unique et fiable existe.
- Les lignes avec code postal seul ne sont pas chargees comme `TUNISIE|UNKNOWN|UNKNOWN|UNKNOWN|code`.
- Les codes postaux sont valides seulement s'ils sont reels, a 4 chiffres, et confirmes par le referentiel postal dedie.
- Les codes source non confirmes peuvent rester comme evidence partielle, mais ne donnent pas `VALIDATED`.
- Les prefixes postaux de gouvernorat servent uniquement de controle de coherence ; ils ne sont jamais ecrits comme codes finaux.
- `geo_key` est recalcule apres correction et les doublons sont supprimes par ranking qualite.
- Une seule ligne technique `UNKNOWN` est conservee avec `geo_sk = 0`.
- Un mapping source -> geo resolue est genere pour preparer `fact_sinistre.geo_sinistre_sk`.

## Regles de code postal

Priorite de resolution :

```text
1. CPOSTSINI source si valide et non contradictoire
2. geo_dim_approved_corrections.csv si APPROVED et valide
3. referentiel postal exact gouvernorat + localite
4. referentiel postal alias localite/gouvernorat
5. referentiel postal exact gouvernorat + delegation
6. geo_dim_postal_approved_corrections.csv si APPROVED et matche par geo_key
7. correction globale localite uniquement si le gouvernorat final/source est UNKNOWN et le match est unique
8. UNKNOWN ou CONFLICT_GOV_LOCALITE si absent, ambigu ou contradictoire
```

Regle de validation :

```text
VALIDATED = geographie resolue + code postal confirme par geo_tunisia_postal_reference.csv
```

Un code postal est charge seulement si :

```text
- il est numerique ;
- il contient 4 chiffres ;
- il ne contredit pas le gouvernorat ;
- il est confirme par une reference postale unique pour obtenir VALIDATED.
```

## Resultat final valide

Dernier chargement valide : 2026-06-28.

```text
dwh.dim_geo rows                         : 2402
business NULLs                           : 0
geo_key NULLs                            : 0
duplicate geo_key                        : 0
technical UNKNOWN rows                   : 1
postal_only_bad_rows                     : 0
remaining_unknown_postal_with_full_geo   : 483
rows_with_code_postal_UNKNOWN            : 1371
postal reference usable rows             : 4833
postal approved corrections loaded       : 163
postal approved corrections matched      : 163
```

Distribution finale stricte :

```text
AMBIGUOUS : 1093
VALIDATED : 969
PARTIAL   : 339
UNKNOWN   : 1
```

Interpretation :

- `VALIDATED` : geographie resolue avec code postal confirme par le referentiel postal dedie.
- `PARTIAL` : geographie utile et officielle, mais code postal non confirme par reference postale.
- `AMBIGUOUS` : localite/delegation/code postal non resolu de maniere unique ou conflit detecte.
- `UNKNOWN` : aucune geographie exploitable, ligne technique seulement.

## Rapports regenerables

Les rapports d'audit et de resolution restent hors DWH. Ils servent a expliquer les limites et les corrections, pas a enrichir directement les dimensions.

Commandes :

```powershell
python etl/dwh/audit/audit_dim_geo.py
python etl/dwh/load_dim_geo.py
```

Principaux rapports :

```text
data/quality_reports/dim_geo/dim_geo_resolution_report.csv
data/quality_reports/dim_geo/dim_geo_unresolved.csv
data/quality_reports/dim_geo/dim_geo_conflicts_after_resolution.csv
data/quality_reports/dim_geo/dim_geo_missing_postal_codes.csv
data/quality_reports/dim_geo/dim_geo_postal_ambiguous.csv
data/quality_reports/dim_geo/dim_geo_postal_source_conflicts.csv
data/quality_reports/dim_geo/dim_geo_governorate_locality_conflicts.csv
data/quality_reports/dim_geo/dim_geo_postal_missing_reference.csv
data/quality_reports/dim_geo/dim_geo_postal_reference_public_build_log.csv
data/quality_reports/dim_geo/dim_geo_postal_only_resolved.csv
data/quality_reports/dim_geo/dim_geo_postal_only_unresolved.csv
data/quality_reports/dim_geo/dim_geo_postal_approved_corrections_unmatched.csv
data/quality_reports/dim_geo/dim_geo_deduplication_decisions.csv
data/quality_reports/dim_geo/dim_geo_source_to_resolved_mapping.csv
```

## Contraintes d'architecture conservees

- Ne pas ajouter les colonnes d'audit dans `dwh.dim_geo`.
- Ne pas ajouter `rue`.
- Ne pas ajouter `type_geo`.
- Ne pas reintroduire les adresses client dans `dim_geo`.
- Ne pas ajouter `geo_sk` dans `dim_client`.
- Ne pas mettre la geographie dans `dim_sinistre`.
- `fact_sinistre` portera plus tard la cle `geo_sinistre_sk`.








