# Rapport d'impact dim_conducteur — 20260724_152449

Seuil utilisé (WEAK_PERMIS_ABNORMAL_USE_THRESHOLD) : 20
Littéraux placeholder : ['/', '0', '0 /00000', '00', '01', '1', 'NON FOURNI', 'SANS COND', 'SANS CONDU', 'STATIONNE', 'UNKNOWN']

## Métriques avant / après

| Métrique | Avant (comportement historique) | Après (correctif) |
|---|---|---|
| Lignes staging lues | 381893 | 381893 |
| Lignes totalement vides exclues | 29630 | 29630 |
| Lignes candidates conducteur | 352263 | 316161 |
| Lignes identité faible exclues | 0 | 36102 |
| Lignes permis-seul conservées (rares) | — | 62359 |
| Conducteurs réels distincts | 161524 | 161439 |
| Total avec UNKNOWN | 161525 | 161440 |

## Distribution des permis seuls

- Valeurs distinctes observées : 27900
- Valeurs suspectes (traitées comme repli) : 58
- Lignes concernées par une valeur suspecte : 36102
- Détail complet : `dim_conducteur_permis_seul_distribution_20260724_152449.csv`
- Valeurs suspectes seules : `dim_conducteur_valeurs_suspectes_20260724_152449.csv`

## Impact sur dwh.fact_sinistre (état actuel de la base, avant recalcul)

- `conducteur_sk` fantômes actuellement en base : 81
- Lignes fact_sinistre qui basculeront vers UNKNOWN (sk=0) : 32522
- `conducteur_sk=0` actuel : 33230 / 381893 (8.70%)
- `conducteur_sk=0` estimé après correctif : 65752 / 381893 (17.22%)

## Dossiers actuellement aberrants (dernier run de scoring)

- Dossiers avec `driver_claim_count_12m > 100` : 40547

## Dossier de référence G26511000017765|REM

- claim_sk : 14188
- conducteur_sk actuel : 1042
- numero_permis : 1
- nom_conducteur : None
