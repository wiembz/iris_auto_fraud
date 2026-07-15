# Business Rule Catalog V2 Candidate

## Objectif

Le catalogue V2 formalise les regles metier sous une forme configurable, testable et explicable. Il alimente le score `IRIS_CLAIM_ATTENTION_V2_CANDIDATE` sans remplacer la V1.

## Format de configuration

Le catalogue est stocke dans :

```text
config/claim_attention/rules_v2_candidate.json
```

Decision : le fichier utilise JSON, car le projet ne declare pas de parseur YAML Python. Cela evite une dependance inutile et rend la validation au chargement deterministe.

## Structure d'une regle

Chaque regle contient :

- `rule_code` : identifiant stable.
- `rule_family` : famille de plafonnement.
- `version` : version de la regle.
- `grain` : grain d'application, `GUARANTEE` ou `DOSSIER`.
- `label_business` : libelle metier affiche.
- `description` : explication technique courte.
- `attention_level` : formulation metier prudente.
- `required_fields` : champs obligatoires pour evaluer la regle.
- `condition` : condition declarative.
- `points` : poids brut candidat.
- `family_cap` : plafond de famille de la regle.
- `suggested_action_code` : action de revue associee.
- `business_explanation` : texte explicatif non accusatoire.
- `threshold_source` : origine du seuil (statistique candidate, controle
  deterministe, classification qualite).
- `validated_by` / `validated_on` : tracabilite de validation metier, null
  tant que la regle n'est pas validee par BNA.
- `is_active` : activation ou desactivation.

## Validation au chargement

Le chargement refuse :

- famille absente de `family_caps` ;
- `is_active` non booleen ;
- points ou plafonds negatifs ;
- pointage superieur au plafond de regle ;
- operateur non autorise ;
- condition mal structuree ;
- champ de condition absent de `required_fields` ;
- champ `requires` non declare ;
- action suggeree inconnue ;
- version de score incoherente ;
- formulation accusatoire ;
- `grain` absent ou hors de {`GUARANTEE`, `DOSSIER`} ;
- `threshold_source` absent ou vide ;
- `validated_by` / `validated_on` absents (null autorise, vide refuse).

## Familles actives initiales

- `CHRONOLOGY`
- `HISTORY`
- `COMPARISON`
- `COMPLETENESS`
- `DATA_QUALITY`

`GEOGRAPHY` reste reserve tant que la decision GEO n'est pas `GEO_READY`.

## Plafonds

- Chronologie : 25 points.
- Historique : 20 points.
- Comparaison : 20 points.
- Completeness : 15 points.
- GEO : 10 points, non actif en `GEO_PARTIAL`.
- Data quality : 0 point, impact confiance uniquement.

## Dimensionnement des plafonds

Le plafond de famille a deux roles :

1. borner la contribution de chaque famille au score global (toujours actif) ;
2. plafonner le cumul intra-famille quand plusieurs regles co-existent.

Etat actuel du role 2 :

| Famille | Regles actives | Points max cumulables | Plafond | Plafond intra-famille effectif ? |
|---|---:|---:|---:|---|
| CHRONOLOGY | 2 | 32 | 25 | Oui (couvert par test unitaire) |
| HISTORY | 1 | 12 | 20 | Non atteint, famille mono-regle |
| COMPARISON | 1 | 15 | 20 | Non atteint, famille mono-regle |
| COMPLETENESS | 1 | 15 | 15 | Sature par une seule regle |
| GEOGRAPHY | 0 | 0 | 10 | Reserve |
| DATA_QUALITY | 1 | 0 | 0 | Par principe |

Choix documentes :

- La saturation de COMPLETENESS par `COMP_CRITICAL_DOCUMENT_MISSING` est un
  choix conservateur temporaire tant que la famille est mono-regle. Cette
  famille est de plus non evaluable sur le DWH actuel (compteurs documentaires
  absents), donc sans effet en production.
- Les plafonds HISTORY et COMPARISON sont dimensionnes pour accueillir de
  futures regles independantes. Ils ne sont pas recalibres avant la
  calibration metier BNA.

## Grain d'application

Chaque regle declare son grain via le champ `grain` :

- `GUARANTEE` : la regle s'evalue au grain `sinistre x garantie` (toutes les
  regles actuelles) ;
- `DOSSIER` : reserve aux futures regles evaluees au niveau dossier.

L'agregation vers la worklist dossier reste regie par
`docs/architecture/ADR_CLAIM_DECISION_GRAIN.md` : score dossier = MAX des
scores garanties, sans somme ni bonus multi-garanties. Declarer le grain sur
chaque regle empeche de reintroduire des priorites contradictoires pour un
meme dossier via une future regle mal positionnee.

## Criteres d'activation de la famille GEOGRAPHY

La famille GEOGRAPHY (plafond 10) reste sans regle active tant que la
decision GEO n'est pas `GEO_READY`. Criteres cumulatifs d'activation :

1. referentiel `dim_geo` stabilise et audite (taux d'`UNKNOWN` documente et
   juge acceptable) ;
2. `geo_evaluable_flag` et `geo_mapping_quality` disponibles dans les smart
   features au niveau requis ;
3. regles GEO redigees au format du present catalogue (`condition`, `points`,
   `family_cap`, `grain`, `threshold_source`, `is_active`) et validees par les
   tests ;
4. entree correspondante dans `CATALOG_CHANGELOG.md`.

Toute future source de signal (par exemple une piste photos/documents) doit
entrer par le meme format de regle et les memes exigences, jamais par un
format heterogene.

## Gouvernance

Les regles sont candidates. Toute modification de seuil, poids ou wording doit etre versionnee et testee. Le score reste une aide a la priorisation, pas une conclusion automatique.

Chaque modification du catalogue est tracee dans
`docs/claim_attention/CATALOG_CHANGELOG.md` (auteur, date, motivation, hash
SHA-256 du catalogue). Les champs `threshold_source`, `validated_by` et
`validated_on` distinguent, regle par regle, les seuils valides metier des
seuils candidats statistiques : tant que `validated_by` est null, la regle
reste une proposition, coherente avec le statut global
`BUSINESS_VALIDATION_PARTIAL`.
