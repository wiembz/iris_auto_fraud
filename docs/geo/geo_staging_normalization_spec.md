# Spécification de normalisation GEO staging

## Objectif

Cette spécification prépare la normalisation technique des champs géographiques dès le staging afin de fiabiliser les contrôles qualité, les jointures DWH et les futurs tableaux de bord Power BI.

Cette étape ne constitue pas une correction métier. Elle ne doit pas être interprétée comme une validation définitive des rattachements géographiques, ni comme une résolution officielle des gouvernorats, localités, régions, agences ou codes postaux.

## Principe d'architecture

La chaîne GEO doit séparer clairement les niveaux de traitement :

- source brute : valeur exacte extraite depuis les fichiers sources ;
- staging : normalisation technique et contrôlée ;
- référentiels GEO : corrections métier validées ;
- dimensions DWH : consolidation analytique ;
- marts / Power BI : exploitation décisionnelle.

Règle d'architecture :

```text
La normalisation technique commence au staging, mais les corrections métier restent dans les référentiels et dimensions contrôlées.
```

Cette séparation permet de réduire le bruit technique sans masquer les erreurs de saisie ou les ambiguïtés métier.

## Périmètre initial

Colonnes candidates dans `staging.stg_sinistres` :

- `gouvsini`
- `citesini`
- `cpostsini`
- `iddelega`

Colonnes candidates dans `staging.stg_clients` :

- `cpost`
- `cite`
- `gouvernor`

Colonnes candidates dans `staging.stg_production` :

- `iddelega`

La première intégration future doit commencer par `staging.stg_sinistres`, car `dwh.fact_sinistre.geo_sinistre_sk` dépend du rattachement GEO sinistre.

## Normalisation technique autorisée

Les règles autorisées à ce stade sont strictement techniques :

- suppression des espaces au début et à la fin ;
- uniformisation de la casse en majuscules ;
- suppression des doubles espaces ;
- conversion des chaînes vides en `NULL` côté base / `None` côté Python ;
- conversion de `N/A`, `NA`, `-`, `--`, `.` en `NULL` / `None` ;
- conversion de `UNKNOWN`, `INCONNU`, `INCONNUE`, `NON RENSEIGNE`, `NON RENSEIGNÉ` en `UNKNOWN` ;
- conservation des accents dans les libellés, afin de ne pas modifier le sens visible de la valeur source ;
- normalisation des codes postaux en texte ;
- suppression du suffixe `.0` dans les codes postaux issus d'Excel ;
- conservation des zéros initiaux si possible ;
- normalisation des codes numériques comme `iddelega`.

Ces règles ne doivent pas rattacher une valeur à un référentiel métier. Elles rendent seulement les valeurs plus stables pour les contrôles et les jointures techniques.

## Corrections interdites à ce stade

Les actions suivantes sont interdites dans cette étape :

- rattacher automatiquement une localité à un gouvernorat ;
- déduire une région depuis une adresse libre ;
- corriger une localité ambiguë ;
- rattacher une agence ou un intermédiaire à une région sans référentiel validé ;
- remplacer une valeur manquante par une valeur supposée ;
- modifier le sens métier d'un champ ;
- modifier les tables DWH existantes ;
- modifier les scripts ETL existants.

## Traçabilité attendue

La stratégie de traçabilité cible est la suivante :

- conserver les valeurs brutes ;
- produire des valeurs normalisées ;
- comparer les volumes avant/après ;
- documenter les écarts ;
- garder les requêtes de contrôle en read-only ;
- tester d'abord en local / TEST avant toute intégration DWH.

Convention future proposée :

- `*_raw` pour la valeur brute ;
- `*_norm` pour la valeur normalisée.

Cette convention est appliquée dans `staging.stg_sinistres` depuis l'intégration du 2026-07-05 (voir section « Décision d'intégration retenue »).

## Décision d'intégration retenue — Option A

**Date :** 2026-07-05  
**Fichier modifié :** `etl/staging_area/load_sinistres_sa.py`

### Colonnes ajoutées dans staging.stg_sinistres

| Colonne normalisée | Colonne source | Fonction appliquée        |
|--------------------|----------------|---------------------------|
| `gouvsini_norm`    | `gouvsini`     | `normalize_geo_text`      |
| `citesini_norm`    | `citesini`     | `normalize_geo_text`      |
| `cpostsini_norm`   | `cpostsini`    | `normalize_postal_code`   |
| `iddelega_norm`    | `iddelega`     | `normalize_numeric_code`  |

Les colonnes brutes (`gouvsini`, `citesini`, `cpostsini`, `iddelega`) sont conservées intactes.

### Point d'insertion dans le flux

```python
df = sa_utils.add_technical_columns(df, SOURCE_FILE, run_id)
df = add_geo_normalized_columns(df, logger)   # ← inséré ici
n_rows, elapsed = sa_utils.write_to_postgres(df, engine, SCHEMA, TABLE_NAME, logger)
```

La table `staging.stg_sinistres` étant recréée à chaque run via `to_sql(if_exists="replace")`,
les nouvelles colonnes apparaissent automatiquement sans `ALTER TABLE`.

### Loaders DWH non modifiés à cette étape

`load_dim_geo.py` et `load_fact_sinistre.py` continuent de lire les colonnes brutes.
Ils ne référencent pas les colonnes `*_norm`. Leur comportement est inchangé.

### Pourquoi Option A et non Option B

L'Option B (remplacement des valeurs brutes) a été écartée car :

- elle supprimerait la valeur source originale, rendant l'audit impossible ;
- le mapping `source_geo_key → resolved_geo_key` de `dim_geo_source_to_resolved_mapping.csv`
  est calculé depuis les colonnes brutes par `load_dim_geo.py` — remplacer les brutes
  introduirait une incohérence de clés entre les deux loaders ;
- `load_fact_sinistre.py` reconstruit `source_geo_key` depuis `gouvsini`, `citesini`, `cpostsini` bruts —
  un remplacement casserait la résolution de `geo_sinistre_sk`.

## Tests attendus

Les fonctions Python devront être testées avec les cas suivants :

- valeur `None` ;
- chaîne vide ;
- chaîne avec espaces ;
- casse mixte ;
- double espace ;
- `N/A`, `NA`, `-`, `--`, `.` ;
- `UNKNOWN`, `INCONNU`, `NON RENSEIGNE` ;
- code postal entier ;
- code postal float Excel comme `1000.0` ;
- code postal texte avec espaces ;
- code numérique `iddelega`.

## Impact attendu

Cette étape doit permettre :

- des libellés plus stables ;
- des jointures plus fiables ;
- une meilleure lecture des valeurs `UNKNOWN` ;
- moins de variantes parasites ;
- une meilleure préparation des dashboards Power BI ;
- aucun changement métier automatique.

## Risques maîtrisés

Le risque est limité car :

- un seul loader est modifié (`load_sinistres_sa.py`) ; les loaders DWH (`load_dim_geo.py`,
  `load_fact_sinistre.py`) restent inchangés et lisent toujours les colonnes brutes ;
- aucune base n'est modifiée directement dans ce patch ; les colonnes `*_norm` n'apparaîtront
  dans `staging.stg_sinistres` qu'après le prochain run de chargement en environnement TEST ;
- aucune correction métier n'est appliquée ;
- les fonctions sont pures et testables (21/21 tests passés) ;
- les données brutes restent conservées ;
- rollback immédiat : retirer `df = add_geo_normalized_columns(df, logger)` et le bloc
  d'import suffit à revenir à l'état précédent.

## Étapes suivantes

1. Créer des tests unitaires — **FAIT** (21/21 tests passés, `tests/test_geo_normalization.py`).
2. Valider les fonctions sur échantillons — **FAIT**.
3. Intégrer progressivement dans le loader sinistres — **FAIT** (`load_sinistres_sa.py` modifié le 2026-07-05).
4. Recharger uniquement en base TEST — **FAIT** (run 2026-07-05, 381 893 lignes chargées).
5. Comparer les contrôles qualité avant/après avec des requêtes SELECT read-only — **FAIT**
   (voir `docs/geo/geo_staging_normalization_validation.md`).
6. Documenter la validation — **FAIT** (`docs/geo/geo_staging_normalization_validation.md`).
7. Comparer la résolution GEO avant/après dans `dwh.dim_geo` : relancer `load_dim_geo.py`
   en TEST et mesurer l'impact des 38 tokens non-informatifs désormais en NULL staging
   sur le taux `VALIDATED` / `PARTIAL` / `AMBIGUOUS` / `UNKNOWN`.
8. Seulement ensuite envisager les corrections référentielles (ajout de `gouvsini_norm` dans
   `COLUMN_CANDIDATES` de `load_dim_geo.py` pour bénéficier de la pré-normalisation staging).


## Decision complementaire - fiabilisation de `dwh.dim_geo`

**Date :** 2026-07-05  
**Fichier modifie :** `etl/dwh/load_dim_geo.py`

La fiabilisation finale de `dwh.dim_geo` doit rester portee par le loader DWH et les referentiels controles, pas par un remplacement des valeurs staging.

Actions retenues :

- `normalize_cpost` cote DWH traite desormais les codes postaux issus d'Excel ou PostgreSQL comme `9174.0` sans les transformer en `91740` ;
- la cascade `STEP4_POSTAL` utilise d'abord `DimRegion.csv` pour deduire un gouvernorat seulement quand le code postal pointe vers un gouvernorat unique ;
- la localite est deduite depuis le code postal seulement si `DimRegion.csv` donne une localite unique dans le gouvernorat resolu ;
- les corrections GEO `APPROVED` sont appliquees dans le flux actif avant exclusion et deduplication ;
- les corrections postales `APPROVED` sont appliquees dans le flux actif avant deduplication ;
- les statuts actifs de resolution `STEP*_DIMREGION_*` sont correctement classes lors de la deduplication.

Regle de securite conservee :

```text
Une valeur ambigue reste en revue ; seule une correspondance unique ou une correction APPROVED peut enrichir la dimension finale.
```

Consequence attendue : `dwh.dim_geo` peut devenir fiable sans perdre l'audit des valeurs brutes et sans casser le mapping `source_geo_key -> resolved_geo_key` utilise par `fact_sinistre`.

## Decision complementaire - reference Tunisie unique

**Date :** 2026-07-05  
**Fichier modifie :** `etl/dwh/load_dim_geo.py`

`data/reference/dim_geo/DimRegion.csv` est la reference maitresse pour la resolution Tunisie dans `load_dim_geo.py` : gouvernorat, delegation, localite et code postal.

Regles appliquees :

- `geo_tunisia_reference.csv` n'est plus charge comme source de verite concurrente par `load_dim_geo.py` ;
- les index administratifs et postaux du loader sont construits depuis `DimRegion.csv` ;
- le rattachement par code postal n'utilise plus de fallback par prefixe ; le code doit exister dans `DimRegion.csv` ;
- un code postal source absent de `DimRegion.csv`, ou rattache a un autre gouvernorat/localite, produit un statut de conflit et reste en revue ;
- un alias manuel ne peut canonicaliser une localite que si sa cible est confirmee dans `DimRegion.csv` pour le gouvernorat resolu ;
- une correction metier `APPROVED` reste la seule voie controlee pour corriger une saisie manuelle non resoluble automatiquement.

Nouveau statut qualite possible : `CONFLICT`, utilise pour separer les contradictions metier des simples cas `AMBIGUOUS`.

## Decision complementaire - verification Google Maps des candidats rue/quartier

**Date :** 2026-07-06  
**Fichier ajoute :** `etl/dwh/audit_dim_geo_google_maps_candidates.py`

La verification Google Maps est ajoutee comme couche d'aide au controle qualite des candidats issus de `rue`, quartiers et zones libres. Elle ne remplace pas `DimRegion.csv`, qui reste la reference maitresse Tunisie.

Regles retenues :

- le script lit `data/quality_reports/dim_geo/dim_geo_excluded_rue_review_candidates.csv` ;
- il interroge Google Maps Geocoding uniquement si `GOOGLE_MAPS_API_KEY` est fourni ;
- il restreint les recherches au pays Tunisie via `components=country:TN` ;
- il produit `data/quality_reports/dim_geo/dim_geo_google_verified_candidates.csv` ;
- une ligne devient `AUTO_APPROVABLE` seulement si Google confirme le pays, le gouvernorat attendu et le libelle attendu ;
- un pays explicite different de la Tunisie produit `GOOGLE_CONFLICT` ;
- les cas partiels, ambigus ou non confirmes restent en `REVIEW` ;
- aucune correction n'est appliquee automatiquement dans `dwh.dim_geo`.

Commandes d'execution :

```powershell
# Preparation sans appel API
python etl/dwh/audit_dim_geo_google_maps_candidates.py --offline --limit 5

# Verification reelle apres activation de la cle Google Maps
$env:GOOGLE_MAPS_API_KEY = "VOTRE_CLE"
python etl/dwh/audit_dim_geo_google_maps_candidates.py --limit 50

# Optionnel : inclure aussi les candidats ambigus
python etl/dwh/audit_dim_geo_google_maps_candidates.py --limit 50 --include-ambiguous
```

Regle de securite conservee :

```text
Google Maps peut accelerer la revue, mais seule une correction APPROVED ou une correspondance DimRegion unique peut alimenter la dimension finale.
```

## Decision complementaire - option gratuite OpenStreetMap/Nominatim

**Date :** 2026-07-06  
**Fichier ajoute :** `etl/dwh/audit_dim_geo_nominatim_candidates.py`

Une option gratuite est ajoutee via OpenStreetMap Nominatim pour verifier les candidats issus de `rue`, quartiers et zones libres sans cle Google Maps. Cette option reste une aide a la revue, pas une source de verite concurrente a `DimRegion.csv`.

Regles retenues :

- le script lit `data/quality_reports/dim_geo/dim_geo_excluded_rue_review_candidates.csv` ;
- il produit `data/quality_reports/dim_geo/dim_geo_nominatim_verified_candidates.csv` ;
- aucun appel reseau n'est fait sans le flag explicite `--online` ;
- les requetes utilisent uniquement les termes candidats (`matched_reference_terms`, localite, delegation, gouvernorat), pas le texte brut complet de `rue` ;
- les recherches sont limitees a la Tunisie avec `countrycodes=tn` ;
- le cache local `dim_geo_nominatim_cache.json` evite de renvoyer les memes requetes ;
- le rythme par defaut est `--sleep-seconds 1.1`, compatible avec la limite publique de Nominatim ;
- une ligne devient `AUTO_APPROVABLE` seulement si Nominatim confirme le pays, le gouvernorat attendu et le libelle attendu ;
- les cas partiels, non confirmes ou contradictoires restent en `REVIEW` ;
- aucune correction n'est appliquee automatiquement dans `dwh.dim_geo`.

Commandes d'execution :

```powershell
# Preparation sans appel reseau
python etl/dwh/audit_dim_geo_nominatim_candidates.py --limit 5

# Verification gratuite en petit batch
python etl/dwh/audit_dim_geo_nominatim_candidates.py --online --limit 50

# Optionnel : ajouter un contact conforme a l'usage Nominatim
$env:NOMINATIM_EMAIL = "votre.email@example.com"
python etl/dwh/audit_dim_geo_nominatim_candidates.py --online --limit 50

# Batch complet des candidats selectionnes, a lancer seulement si necessaire
python etl/dwh/audit_dim_geo_nominatim_candidates.py --online --limit 857
```

Regle de securite conservee :

```text
Nominatim/OpenStreetMap peut reduire la revue manuelle, mais `DimRegion.csv` et les corrections APPROVED restent les seules entrees controlees de la dimension finale.
```
## Decision complementaire - export des validations Nominatim vers corrections candidates

**Date :** 2026-07-06  
**Fichier ajoute :** `etl/dwh/export_dim_geo_nominatim_auto_approvals.py`

Les lignes `AUTO_APPROVABLE` issues de Nominatim peuvent etre exportees vers un fichier de corrections candidates, mais pas appliquees directement.

Regles retenues :

- le script lit `data/quality_reports/dim_geo/dim_geo_nominatim_verified_candidates.csv` ;
- il genere `data/quality_reports/dim_geo/dim_geo_nominatim_auto_approvable_corrections.csv` ;
- le statut par defaut est `PENDING`, afin que `load_dim_geo.py` ne les applique pas automatiquement ;
- une correction est exportee seulement si la meme `source_geo_key` pointe vers une seule cible `DimRegion` ;
- si plusieurs libelles `rue/quartier` d'une meme `source_geo_key` donnent des cibles differentes, la cle est exclue de l'export automatique ;
- les exclusions de ce type sont documentees dans `dim_geo_nominatim_auto_approvable_skipped_ambiguous_keys.csv` ;
- pour appliquer reellement une correction, le statut doit etre passe explicitement a `APPROVED` apres acceptation de la regle metier.

Commandes d'execution :

```powershell
# Export securise en PENDING
python etl/dwh/export_dim_geo_nominatim_auto_approvals.py

# Export en APPROVED uniquement apres acceptation de la regle metier
python etl/dwh/export_dim_geo_nominatim_auto_approvals.py --approval-status APPROVED
```

Regle de securite conservee :

```text
Une confirmation Nominatim par rue ne suffit pas si la source_geo_key peut correspondre a plusieurs cibles DimRegion.
```
## Decision complementaire - alignement des cles GEO source dim_geo/fact_sinistre

**Date :** 2026-07-06  
**Fichier modifie :** `etl/dwh/load_dim_geo.py`

Un ecart technique a ete identifie entre le mapping `dim_geo_source_to_resolved_mapping.csv` et la reconstruction de `source_geo_key` dans `load_fact_sinistre.py`.

Cause : certaines valeurs sources comme `MANNOUBA` etaient conservees dans le mapping `dim_geo`, alors que `fact_sinistre` les reconstruisait sous la forme normalisee `MANOUBA`. Le mapping ne retrouvait donc pas des lignes pourtant resolues dans `dim_geo`.

Regles retenues :

- `_source_geo_key_from_values` normalise maintenant gouvernorat, localite et code postal avant de construire la cle source ;
- les tokens de gouvernorat degeneres `A`, `B`, `I`, `S`, `X` sont traites comme non exploitables ;
- `TUNISIE -` n'est plus assimile a tort au gouvernorat `TUNIS` ;
- cette correction est technique : elle aligne les cles entre loaders sans changer les valeurs brutes staging.

Impact mesure apres rechargement :

```text
missing_geo_sinistre_sk avant correction : 4528
missing_geo_sinistre_sk apres correction : 2223
resolved_geo_key vide restant            : 0
```

Les 2223 lignes restantes pointent toutes vers l'ancre technique `UNKNOWN|UNKNOWN|UNKNOWN|UNKNOWN` et correspondent principalement a des libelles quartier/zone ambigus sans gouvernorat ni code postal fiable.

## Décision complémentaire — fiabilisation fuzzy et double preuve

**Date :** 2026-07-06  
**Fichiers modifiés :** `etl/dwh/load_dim_geo.py`, `etl/dwh/audit_dim_geo_fuzzy_web_candidates.py`

### Règle métier ajoutée

La normalisation technique du staging reste inchangée. Les corrections métier GEO sont appliquées uniquement dans le flux DWH, avec traçabilité.

Une localité issue de saisie manuelle ne doit plus être conservée comme localité finale dans `dwh.dim_geo` si elle n'est pas confirmée par `DimRegion.csv` ou par une correction approuvée.

Conséquence :

- une faute fuzzy confirmée dans `DimRegion.csv` peut être canonisée, par exemple `DJEBENIANA SFAX` -> `JEBENIANA` ;
- un libellé de type POI/adresse (`HOPITAL`, `HOTEL`, `BANQUE`, `PARKING`, `ROND POINT`, etc.) est déplacé en fragment d'adresse et ne devient jamais une localité finale ;
- un couple non prouvé, par exemple `SFAX / HAMMAMET`, est abaissé en rattachement partiel fiable au gouvernorat, avec localité finale `UNKNOWN` après finalisation ;
- les libellés bruts restent disponibles dans les rapports d'audit via `source_localite`, `source_region`, `source_rue` et `source_geo_key`.

### Couche fuzzy autorisée

Le resolver DWH utilise maintenant une clé phonétique/conservative pour les variantes tunisiennes fréquentes :

- `DJEBENIANA`, `DJEBENIENA`, `DJEBINIANA` -> `JEBENIANA` ;
- `ECHABBA`, `ECHEBBA`, `CHIBA` -> `LA CHEBBA` ;
- `RAJICH`, `RJICH`, `REJICH` -> `REJICHE` ;
- `BANANE`, `BANNANE`, `BENNENE` -> `BENNANE` ;
- suppression de suffixes de contexte comme le gouvernorat (`... SFAX`, `... MAHDIA`, etc.) pour le matching uniquement.

Cette clé n'est pas écrite dans `dim_geo`. Elle sert seulement à trouver une cible officielle unique dans `DimRegion.csv`.

### Double preuve auto

Un fichier optionnel est prévu pour les corrections automatiques validées par double preuve :

```text
data/reference/dim_geo/geo_dim_auto_double_proof_corrections.csv
```

Le loader ne l'applique que si :

- le fichier existe ;
- la ligne contient `approval_status = APPROVED` ;
- la correction pointe vers un gouvernorat/localité/code postal cohérent avec `DimRegion.csv`.

Le script suivant génère les candidats fuzzy et marque les lignes déjà confirmées par un rapport externe mis en cache :

```powershell
python etl/dwh/audit_dim_geo_fuzzy_web_candidates.py
```

Par défaut, il écrit seulement :

```text
data/quality_reports/dim_geo/dim_geo_fuzzy_web_candidates.csv
```

Pour produire le fichier de corrections auto à revoir ou appliquer :

```powershell
python etl/dwh/audit_dim_geo_fuzzy_web_candidates.py --write-auto-corrections --approval-status PENDING
```

Le passage à `APPROVED` doit rester une décision contrôlée, sauf règle métier explicitement acceptée.
