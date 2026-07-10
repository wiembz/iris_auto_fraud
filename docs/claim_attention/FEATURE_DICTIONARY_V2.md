# Feature Dictionary V2 Candidate

## Objectif

`IRIS_CLAIM_SMART_FEATURES_V2_CANDIDATE` prepare une ligne par dossier pour alimenter des regles metier explicables. Cette couche ne remplace pas Claim Attention V1 et ne modifie pas VHS.

## Principes transverses

- Zero signifie une valeur connue egale a zero.
- `pd.NA` signifie donnee absente, inconnue ou non fournie.
- Un controle non evaluable ne produit ni signal positif ni signal negatif.
- `input_hash` est une empreinte SHA-256 deterministe construite a partir des valeurs sources utilisees.
- Les donnees manquantes reduisent la confiance de lecture, elles n'ajoutent pas automatiquement de points d'attention.

## Flags d'evaluabilite

- `history_evaluable_flag` : historique exploitable car au moins une colonne d'historique est disponible.
- `chronology_evaluable_flag` : chronologie exploitable car un delai ou un indicateur chronologique est disponible.
- `document_completeness_evaluable_flag` : completude documentaire exploitable si les compteurs attendu/disponible sont fournis et que le nombre attendu est positif.
- `data_quality_evaluable_flag` : qualite exploitable si les flags de donnees, codes non mappes et dates invalides sont disponibles.

## Completeness

- `expected_document_count` : nombre de pieces attendues selon la matrice metier disponible.
- `available_document_count` : nombre de pieces disponibles.
- `missing_document_count` : pieces attendues non disponibles.
- `completeness_rate` : ratio disponible / attendu, non calcule si le controle n'est pas evaluable.
- `critical_document_missing_count` : pieces critiques manquantes.

## Chronology

- `declaration_delay_days` : delai declaration - sinistre.
- `claim_before_contract_start_flag` : sinistre avant debut contrat.
- `declaration_before_claim_flag` : declaration avant sinistre.
- `chronology_signal_count` : nombre de controles chronologiques actives, `pd.NA` si non evaluable.

## History

- `client_claim_count_12m` et `client_claim_count_24m` : historique client recent.
- `vehicle_claim_count_12m` et `vehicle_claim_count_24m` : historique vehicule lorsque disponible.
- `days_since_previous_claim` : delai depuis le dossier precedent.

Un historique reellement egal a zero reste une information valide. Une colonne absente reste `pd.NA`.

## Similar Claims Comparison

- `comparison_reference_date` : date de reference point-in-time.
- `similar_claim_count` : taille de cohorte comparable hors dossier courant et hors futur.
- `similar_claim_cohort_level` : `PRECISE`, `BROAD`, `GENERAL` ou `NOT_AVAILABLE`.
- `comparison_reliability` : `DISPLAYABLE`, `INSUFFICIENT_SAMPLE` ou `NOT_AVAILABLE`.
- `comparison_status_reason` : raison operationnelle, par exemple `MISSING_COHORT_ATTRIBUTES`, `MISSING_REFERENCE_DATE`, `ZERO_MEDIAN`.
- `amount_median_similar`, `amount_p75_similar`, `amount_p90_similar` : statistiques robustes.
- `amount_ratio_to_median` : montant courant / mediane comparable, calcule seulement si affichable et mediane positive.

Regles de securite :

- le dossier courant est exclu par `claim_sk` ;
- les doublons d'un meme `claim_sk` ne sont comptes qu'une seule fois ;
- les dossiers futurs sont exclus ;
- les attributs manquants ne forment pas une cohorte precise ;
- une cohorte insuffisante ne produit aucun ratio.

## GEO

- `geo_evaluable_flag` : vrai seulement si le lot GEO est valide.
- `geo_mapping_quality` : statut de maturite GEO.

GEO ne doit pas ajouter de points tant que la decision GEO reste `GEO_PARTIAL`.

## Data Quality

- `required_field_completeness_rate` : completude des champs requis.
- `unknown_field_count` : champs techniques inconnus ou manquants.
- `unmapped_code_count` : codes non mappes.
- `invalid_date_count` : dates invalides.
- `data_quality_level` : `HIGH`, `MEDIUM`, `LOW` ou `NOT_EVALUABLE`.

Seuils candidats :

- `HIGH` : completude >= 95 %, aucun champ inconnu, aucun code non mappe, aucune date invalide.
- `MEDIUM` : completude >= 80 %, au plus un champ inconnu, au plus un code non mappe, au plus une date invalide.
- `LOW` : en dessous des seuils precedents.
- `NOT_EVALUABLE` : donnees de qualite source insuffisantes pour classer le dossier.

Un dossier ayant plusieurs codes non mappes ne peut pas etre classe `HIGH`.
