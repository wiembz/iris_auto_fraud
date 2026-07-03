# IRIS Auto Fraud Decision Platform

## 1. Project Purpose

**IRIS Auto Fraud Decision Platform** is a decision-support platform for automobile insurance fraud investigation.

The goal is not to automatically prove fraud. The platform helps fraud managers and claim handlers prioritize claims, understand suspicious patterns, and make better-informed decisions using structured data, business indicators, historical behavior, vehicle inspection results, and scoring signals.

The project transforms raw automobile insurance data into a clean, auditable PostgreSQL Data Warehouse that can feed Power BI dashboards and later an investigation-oriented application.

Main objectives:

- centralize data about clients, contracts, products, guarantees, intermediaries, vehicles, drivers, third parties, claims, and vehicle inspections;
- build a defensible dimensional Data Warehouse model for an academic PFE project;
- analyze automobile claims across business-relevant dimensions;
- detect suspicious recurrence patterns such as repeated claims, same third party, same driver, same vehicle, same location, unusual chronology, or abnormal claim amounts;
- integrate STAFIM vehicle inspection data to evaluate vehicle condition;
- prepare a progressive suspicion scoring layer;
- provide Power BI with a clean, traceable, and business-oriented model.

---

## 2. Business Positioning

IRIS is an **aide a la decision** platform.

It must remain business-friendly and understandable by non-technical insurance users. The system should avoid presenting itself as an automatic fraud detector. It provides signals, priorities, explanations, and investigation support.

Principles:

- IRIS suggests, it does not decide.
- The final decision remains the responsibility of the claim or fraud manager.
- Suspicion indicators must be explainable.
- The platform must preserve traceability of source data, cleaning decisions, and quality limitations.
- Data quality issues are documented instead of hidden.

Recommended business wording:

```text
Les elements presentes constituent une aide a l'analyse.
La decision finale reste sous la responsabilite du gestionnaire.
```

---

## 3. Global ETL Architecture

```text
Excel sources
    -> Data profiling
    -> Staging area
    -> Cleaning / normalization / reference mapping
    -> PostgreSQL Data Warehouse
    -> Dimensions + Facts
    -> Scoring / investigation mart
    -> Power BI dashboards
```

### 3.1 Source Layer

Main source files:

- `Clients.xlsx`
- `Production.xlsx`
- `Sinistres.xlsx`
- `FicheVoitureStafim.xlsx`
- reference files: `Produit.xlsx`, `PE033.xlsx`, `PR01.xlsx`, `SI001.xlsx`, `correspondance garantie.xlsx`

### 3.2 Staging Layer

The staging layer keeps data close to the source format while applying technical cleaning. It is used to load Excel files, preserve source columns, profile data quality, detect nulls and duplicates, prepare normalized columns, and support controlled transformation into the DWH.

### 3.3 Data Warehouse Layer

The DWH contains clean, normalized, business-usable data. Technical intermediate columns such as `*_raw`, `*_norm`, `*_clean`, `mapping_status`, `join_status`, and pipeline flags are not kept in final DWH tables unless they have clear audit or business value.

The model is a **dimensional constellation model** centered around automobile claims.

---

## 4. Current Status

### 4.1 Validated dimensions

The following dimensions have been built and validated structurally:

```text

dim_date
dim_client
dim_camtier
dim_tiers
dim_contrat
dim_produit
dim_vehicule
dim_conducteur
dim_intermediaire
dim_sinistre
dim_garantie
dim_geo
```

Important validation note:

```text
dim_geo is technically valid but still requires a deep geographical/business audit because source fields come from manual entry.
```

### 4.2 Removed dimension

```text
dim_expert
```

Reason:

```text
NATEXPERT and IDEXPERT are 100% NULL in the source data.
```

Therefore, `dim_expert` and `expert_sk` should not be reintroduced unless a reliable expert source is added.

---

## 5. Source Data and Modeling Decisions

### 5.1 Clients

Source: `Clients.xlsx`

Important columns:

```text
CNAT, NUMPERS, TYPEID, ID, ADR1, CPOST, CITE, GOUVERNOR,
DATE_NAISS, PRF, SEXE, NBRENF, SITUAFAMI, DEBCNT
```

Target:

```text
dim_client
```

Final grain:

```text
1 row per client
```

Business key:

```text
NUMPERS
```

Final DWH columns:

```text
client_sk
idclt
typeid
id_piece
nature_client
adr1
cpost
cite
gouvernor
pays
localite
date_naissance
sexe
nombre_enfant
situation_familiale
source_system
created_at
```

Decisions:

- `PRF` excluded because it is empty or not exploitable.
- `DEBCNT` from Clients is not used as first subscription date.
- `geo_sk` is not added to `dim_client` to avoid dimension-to-dimension relationships.
- Client geography remains denormalized inside `dim_client`.
- Client geography was enriched and validated with a residual data-quality reserve.
- Remaining `UNKNOWN` values are kept when the data is absent, noisy, truncated, or not interpretable.

Status:

```text
dim_client: VALIDATED with residual data-quality reserve for geography.
```

---

### 5.2 Production / Contracts

Source: `Production.xlsx`

Important columns:

```text
NUMCNT, NUMAVT, NUMMAJ, CODFAM, CODPROD, LIBPRDT,
NATCLT, IDCLT, NATINT, IDINT, IDDELEGA, DUREE,
DEBCNT, FINCNT, DEBEFFET, FINEFFET, COASSUR,
SITUAT, DATEPREC, TYPERESIL, LIB_RESIL, TOTAL_PRIME
```

Targets:

```text
dim_contrat
dim_produit
dim_intermediaire
fact_contrat
```

Decisions:

- `dim_contrat` grain: one row per normalized contract business key.
- `dim_contrat.contrat_key = normalize_numcnt(NUMCNT)` is the stable join key used by facts.
- Contract identifiers are preserved as business strings; Excel artifacts such as trailing `.0` are removed only when safe.
- `fact_contrat` grain: `NUMCNT + NUMAVT + NUMMAJ`.
- `TOTAL_PRIME` is a measure and belongs in `fact_contrat`.
- `COASSUR` is an indicator and not a separate dimension.
- Contract versions, amendments, and updates are handled in `fact_contrat`.

Status:

```text
dim_contrat: VALIDATED with stable contrat_key
dim_produit: VALIDATED
dim_intermediaire: VALIDATED
```

---

### 5.3 Claims / Sinistres

Source: `Sinistres.xlsx`

Critical columns:

```text
NUMSNT, GRNTSINI, CAUSESINI, DTSURV, NUMCNT, NUMAVT, NUMMAJ,
NUMRISQ, NATCLT, IDCLT, NATINT, IDINT, CODFAM, CODPROD,
IMMAT, REFEXTERN, DTDECSNT, INDFORCAG, CODE_ETAT,
NOMCONDUC, DATNAICON, NUMPERMIS, CATEGPERM, DATEPERMI,
CPOSTSINI, CITESINI, REGSINI, GOUVSINI,
NOMTIERS, IMVEHTIER, NUMCNTTIE, NUMSNTTIE, NATCAMTIE, IDCAMTIER,
CAS_IDA, RESPIDA, DTOUVSNT, DTCLTSNT, DTREOUSNT,
COASSUR, REASSUR, RESPSNT, TAUX, DPECSIN, DDETRANSA,
EVAL_INIT, MNTPROVIS, MNTPAIGRN, MNTAGGRAV, MNTAMELIO,
MNTRECUPC, MNTBONIS, FRANCHIS, MNTDECLAR, MNTPREVIS,
MNTRECOUR, MNTTOTAL, MNTTOTNET, ETATGRNT, MOTIFCLOT, DATCLTGRN
```

Main targets:

```text
dim_sinistre
dim_conducteur
dim_tiers
dim_camtier
dim_geo
fact_sinistre
fact_scoring_sinistre
```

Critical grain decision:

```text
dim_sinistre grain  = NUMSNT
fact_sinistre grain = NUMSNT + GRNTSINI
```

Important decisions:

- `TAUX` goes to `fact_sinistre` as `taux_responsabilite`.
- `DPECSIN` is excluded because it is constant / analytically useless.
- `CODFORMU` is excluded because it is not validated in the guarantee reference.
- `UPDATE_IDENT`, `UPDATE_IDENT.1`, and `NUMSNT.1` are technical columns and excluded.
- `MOTIFCLOT` is not stable at `NUMSNT` level and is excluded from `dim_sinistre`.
- `MOTIFCLOT` belongs to `fact_sinistre` as `motif_cloture_garantie`.
- Claim geography is not stored in `dim_sinistre`.
- Claim geography is modeled in `dim_geo` and connected through `fact_sinistre.geo_sinistre_sk`.

---

## 6. Dimension Decisions Already Made

### 6.1 `dim_sinistre`

Role:

```text
Claim file descriptor at NUMSNT grain.
```

Final approved structure:

```text
sinistre_sk
numero_sinistre
cause_sinistre
libelle_cause_sinistre
code_etat
indicateur_forcage
cas_ida
coassur
reassur
indicateur_transaction
source_system
created_at
```

Decisions:

- Removed highly-null descriptive columns from the initial design.
- Kept only attributes that are actually populated and useful.
- Added `libelle_cause_sinistre` from enriched claim cause mapping when available.
- `cas_ida`, `coassur`, `reassur`, and `indicateur_transaction` are normalized as business indicators.
- `motif_cloture` is not included because one claim can have multiple closure motifs.
- `MOTIFCLOT` is handled later in `fact_sinistre`.

Validation performed:

```text
231,496 sinistres loaded
0 duplicate numero_sinistre
0 nulls on retained indicator columns after simplification
1,103 sinistres have more than one distinct MOTIFCLOT
```

Status:

```text
dim_sinistre: VALIDATED without motif_cloture and without geography.
```

---

### 6.2 `dim_geo`

Role:

```text
Geographical reference for claim locations.
```

Current decision:

```text
dim_geo is based on claim geography only, not client addresses.
```

Source:

```text
staging.stg_sinistres
```

Source mappings are extracted as source signals, then resolved before the DWH load:

```text
REGSINI   -> source_region
GOUVSINI  -> source_gouvernorat
CITESINI  -> source_localite
CPOSTSINI -> source_code_postal
```

Final structure:

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

Grain:

```text
1 row per normalized claim geographical zone.
```

Functional key:

```text
pays | gouvernorat | region | localite | code_postal
```

Rules:

- No `CLIENT` rows in `dim_geo`.
- Client geography remains in `dim_client`.
- No full street or client address in `dim_geo`.
- No `type_geo` in this version because this dimension is claim-location specific.
- One technical `UNKNOWN` row is required with `geo_sk = 0`.
- No nulls are allowed in final business fields; use `UNKNOWN`.
- `geo_key` must be unique.
- `fact_sinistre` will later hold `geo_sinistre_sk`.

Current final validation results after geography resolution:

```text
total rows                                : 2,402
business NULLs                            : 0
geo_key NULLs                             : 0
geo_key dupes                             : 0
UNKNOWN technical rows                    : 1
postal_only_bad_rows                      : 0
remaining_unknown_postal_with_full_geo    : 483
rows_with_code_postal_UNKNOWN             : 1,371
```

Quality distribution with strict postal validation:

```text
AMBIGUOUS : 1093
VALIDATED : 969
PARTIAL   : 339
UNKNOWN   : 1
```

Interpretation:

```text
VALIDATED = geography resolved + postal code confirmed by the dedicated postal reference.
PARTIAL   = useful resolved geography, but postal code missing or not reference-confirmed.
AMBIGUOUS = unresolved conflict or non-unique geography/postal evidence.
UNKNOWN   = technical anchor only.
```

Final transformation workflow:

```text
staging.stg_sinistres
  -> source geography extraction
  -> text normalization
  -> Tunisian administrative reference resolution
  -> APPROVED corrections only, matched by stable geo/source key
  -> dedicated postal-reference validation/enrichment
  -> APPROVED postal corrections only, matched by generated geo_key
  -> geo_key and geo_quality_level recomputation
  -> quality-ranked deduplication
  -> dwh.dim_geo load
```

Reference files used by the final loader:

```text
data/reference/dim_geo/geo_tunisia_reference.csv
data/reference/dim_geo/geo_tunisia_postal_reference.csv
data/reference/dim_geo/geo_dim_approved_corrections.csv
data/reference/dim_geo/geo_dim_postal_approved_corrections.csv
```

Important postal-reference reserve:

```text
geo_tunisia_postal_reference.csv is populated from the official public Tunisian Post governorate/delegation/locality lists and currently has 4,833 usable rows.
Therefore, remaining UNKNOWN postal codes are either absent from the official postal reference, ambiguous across several official postal rows, or insufficiently specific in the source.
The loader does not invent postal codes and does not validate source CPOSTSINI without postal reference confirmation. Global locality matches are rejected when an official source/final governorate conflicts with the candidate postal governorate; the current run reports 39 such conflicts outside the DWH.
```

Quality and audit reports:

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

Clean architecture rule:

```text
Audit columns such as geo_audit_status, confidence_score, candidate_gouvernorat,
candidate_localite, postal_resolution_status, and geo_audit_reason remain in
quality reports only. They must not be added to dwh.dim_geo.
```

Approved correction rule:

```text
load_dim_geo.py applies only APPROVED rows from:

- data/reference/dim_geo/geo_dim_approved_corrections.csv
- data/reference/dim_geo/geo_dim_postal_approved_corrections.csv

Rows marked REJECTED, KEEP_SOURCE, MANUAL_REVIEW, or PENDING remain outside dwh.dim_geo.
Geo corrections are matched by stable business/source geo keys, and postal approved corrections are matched by generated geo_key, not by geo_sk.
```

Postal-code rule:

```text
A postal code is written as VALIDATED only when it is a real 4-digit code confirmed
by the dedicated postal reference. Source postal codes may be kept as PARTIAL evidence
when structurally valid and not prefix-conflicting, but they are not treated as validated
without postal-reference confirmation. Prefixes such as 20xx or 90xx are never written
as final postal codes. Ambiguous, missing, and prefix-conflicting postal cases are
explained in quality reports.
```

Status:

```text
dim_geo: CLEAN DWH LOAD READY structurally, with a documented mandatory postal-reference enrichment reserve.
```

---
### 6.3 `dim_garantie`

Role:

```text
Guarantee descriptor by product and claim guarantee code.
```

Final grain:

```text
1 row per observed CODPROD + GRNTSINI combination from staging.stg_sinistres.
```

Business key:

```text
garantie_key = CODPROD || '|' || GRNTSINI
```

Final structure:

```text
garantie_sk
garantie_key
code_produit
code_garantie
libelle_garantie
garantie_quality_level
source_system
created_at
```

Rules:

- The dimension is rebuilt from all distinct observed `CODPROD|GRNTSINI` combinations in `staging.stg_sinistres`.
- Existing reference labels are used when available.
- Observed combinations missing from the reference are still loaded with `libelle_garantie = UNKNOWN`.
- Missing-reference combinations are documented outside the DWH; they are not removed from the dimension.
- One technical UNKNOWN row is kept with `garantie_sk = 0` and `garantie_key = UNKNOWN|UNKNOWN`.
- `fact_sinistre` joins this dimension through `garantie_key`, not through labels.

Current validation after correction:

```text
dim_garantie rows including UNKNOWN       : 438
observed guarantee combinations           : 437
duplicate garantie_key                    : 0
VALIDATED_REFERENCE                       : 279
OBSERVED_IN_SINISTRES_MISSING_REFERENCE   : 158
UNKNOWN technical rows                    : 1
```

Quality report:

```text
data/quality_reports/dim_garantie/dim_garantie_missing_reference_observed.csv
```

Status:

```text
dim_garantie: VALIDATED for fact_sinistre coverage, with a documented missing-reference reserve.
```
### 6.4 `dim_tiers`

Role:

```text
Third-party descriptor for claims.
```

Cleaning decisions:

- Invalid placeholders such as `NF`, `ND`, `N.D`, `RAS`, and zero-like values are converted to null.
- Special non-vehicle statuses such as `#MOBYLETTE`, `#PIETON`, and `NON ASSURE` are handled carefully.
- Event descriptions such as `DERAPAGE`, `DIVERS CHOCS`, and `BRIS DE GLACE` are not considered valid third-party names.
- `code_postal_tiers` is removed if 100% null or non-exploitable.

Status:

```text
dim_tiers: VALIDATED with data-quality reserve.
```

### 6.5 `dim_camtier`

Valid values retained:

```text
CA|1 to CA|22
CL|8
```

Status:

```text
dim_camtier: VALIDATED.
```

### 6.6 `dim_conducteur`

Status:

```text
dim_conducteur: VALIDATED with completeness reserve.
```

Important note: STAFIM `NOM ET PRENOM` is not considered a driver without business confirmation.

### 6.7 `dim_vehicule`

Status:

```text
dim_vehicule: VALIDATED.
```

Important note: `kilometrage` belongs to `fact_inspection_vehicule`, not `dim_vehicule`.

---

## 7. STAFIM Vehicle Inspection Source

Source: `FicheVoitureStafim.xlsx`

Targets:

```text
dim_vehicule
fact_inspection_vehicule
```

Decisions:

- `NÃ‚Â° D'IMMATRICULATION` is cleaned and used to link with vehicle dimension.
- `kilometrage` belongs to `fact_inspection_vehicule` because it changes over time.
- STAFIM `Score` is used as an input to vehicle condition scoring.
- Images `image1` to `image10` are not loaded into analytical DWH columns.
- `NOM DE L'AGENT` and `NOM ET PRENOM` are separated.
- `NOM ET PRENOM` is not treated as driver without business confirmation.
- `geo_inspection_sk` is excluded because there is no reliable inspection location.

---

## 8. Facts

### 8.1 `fact_sinistre`

Role:

```text
Central fact table for automobile claim-guarantee analysis.
```

Implemented loader:

```text
etl/dwh/load_fact_sinistre.py
```

Grain:

```text
1 row per NUMSNT + GRNTSINI
sinistre_garantie_key = NUMSNT || '|' || GRNTSINI
```

Implemented structure follows the current clean PFE scope:

```text
fact_sinistre_sk
numero_sinistre
code_garantie
sinistre_garantie_key
sinistre_sk
garantie_sk
client_sk
contrat_sk
vehicule_sk
conducteur_sk
tiers_sk
camtier_sk
geo_sinistre_sk
date_survenance_sk
date_declaration_sk
date_ouverture_sk
date_cloture_sk
montant_evaluation
montant_reglement
montant_reserve
montant_recours
montant_charge_sinistre
delai_survenance_declaration_jours
delai_declaration_ouverture_jours
delai_ouverture_cloture_jours
est_cloture
est_corporel
est_materiel
est_ida
est_transaction
est_forcage
est_coassurance
est_reassurance
motif_cloture_garantie
etat_garantie_sinistre
source_system
created_at
```

Rules:

- All dimension joins are left joins.
- Missing dimension matches use technical key `0`, never NULL.
- `geo_sinistre_sk` is joined through the resolved `dim_geo` mapping, not raw geography fields.
- Monetary NULLs remain NULL; they are not replaced by zero.
- Negative delays are preserved and reported as quality anomalies.
- No AI score, suspicion score, expert key, or raw geography text is stored in this fact.

Current validation after load:

```text
source rows                         : 381,893
fact_sinistre rows loaded           : 381,893
duplicate sinistre_garantie_key     : 0
NULL foreign keys                    : 0
missing sinistre_sk                  : 0
missing garantie_sk                  : 0
missing client_sk                    : 17
missing contrat_sk                   : 289
missing vehicule_sk                  : 381,128
missing conducteur_sk                : 33,230
missing tiers_sk                     : 102,783
missing camtier_sk                   : 117,162
missing geo_sinistre_sk              : 747
negative surv->decl delays           : 51,109
negative decl->ouv delays            : 15,554
negative ouv->clot delays            : 8,202
amount anomaly rows                  : 3,205
```

Guarantee and contract coverage notes:

```text
The previous 14,429 missing garantie_sk rows were caused by an incomplete dim_garantie build that relied on codprod_from_contract and excluded observed CODPROD|GRNTSINI combinations. dim_garantie now uses CODPROD|GRNTSINI as the stable business key and includes all observed staging combinations, including missing-reference rows documented in the dim_garantie quality report.

The previous 4,015 missing contrat_sk rows were mostly EXISTS_IN_PRODUCTION_JOIN_PROBLEM cases caused by inconsistent NUMCNT normalization and dim_contrat coverage. A shared normalize_numcnt rule now builds dim_contrat.contrat_key and fact_sinistre.source_contrat_key. After correction, missing contrat_sk is 289, all classified as ABSENT_PRODUCTION in the dedicated quality report.
```

Quality reports:

```text
data/quality_reports/fact_sinistre/fact_sinistre_unmatched_dimensions.csv
data/quality_reports/fact_sinistre/fact_sinistre_unmatched_contrats.csv
data/quality_reports/fact_sinistre/fact_sinistre_date_anomalies.csv
data/quality_reports/fact_sinistre/fact_sinistre_duplicate_grain.csv
data/quality_reports/fact_sinistre/fact_sinistre_amount_anomalies.csv
data/quality_reports/fact_sinistre/fact_sinistre_load_summary.csv
```
### 8.2 `fact_contrat`

Role:

```text
Contract movement / contract version fact table.
```

Implemented loader:

```text
etl/dwh/load_fact_contrat.py
```

Grain:

```text
1 row per NUMCNT + NUMAVT + NUMMAJ
contrat_mouvement_key = contrat_key || '|' || numero_avenant || '|' || numero_mise_a_jour
```

Key rule:

```text
contrat_key = normalize_numcnt(NUMCNT)
```

The fact does not join on raw `NUMCNT`; it uses the same shared contract-key normalization as `dim_contrat` and `fact_sinistre`.

Implemented structure:

```text
fact_contrat_sk
contrat_mouvement_key
contrat_key
numero_contrat
numero_avenant
numero_mise_a_jour
contrat_sk
client_sk
produit_sk
intermediaire_sk
date_debut_contrat_sk
date_fin_contrat_sk
date_debut_effet_sk
date_fin_effet_sk
date_derniere_operation_sk
date_resiliation_sk
duree_contrat
total_prime
nombre_contrat_mouvement
est_contrat_actif
est_contrat_resilie
est_coassurance
est_avenant
est_mise_a_jour
est_auto_scope
situation_contrat
type_resiliation
libelle_resiliation
source_system
created_at
```

Rules:

- All dimension joins are left joins.
- Missing dimension matches use technical key `0`, never NULL.
- Monetary NULLs remain NULL; they are not replaced by zero.
- Duplicate `contrat_mouvement_key` rows are reported and resolved deterministically.
- Contract key, date, amount, and unmatched-dimension issues are documented outside the DWH.
- No geography, client names, product labels, intermediary labels, or fraud scoring logic is stored in this fact.

Quality reports:

```text
data/quality_reports/fact_contrat/fact_contrat_unmatched_dimensions.csv
data/quality_reports/fact_contrat/fact_contrat_duplicate_grain.csv
data/quality_reports/fact_contrat/fact_contrat_date_anomalies.csv
data/quality_reports/fact_contrat/fact_contrat_amount_anomalies.csv
data/quality_reports/fact_contrat/fact_contrat_invalid_contract_keys.csv
data/quality_reports/fact_contrat/fact_contrat_load_summary.csv
```

Status:

```text
fact_contrat loader implemented; execute etl/dwh/load_fact_contrat.py to load and validate PostgreSQL results.
```

### 8.3 `fact_inspection_vehicule`

Grain:

```text
1 row per vehicle inspection.
```

Expected keys:

```text
vehicule_sk
date_inspection_sk
```

Measures and indicators:

```text
kilometrage
score_etat_vehicule
niveau_etat_vehicule
nb_anomalies_tour_vehicule
nb_anomalies_interieur
nb_anomalies_sous_capot
nb_anomalies_sous_vehicule
nb_anomalies_entretien
nb_anomalies_total
indicateur_mauvais_etat
```

### 8.4 `fact_scoring_sinistre`

Grain:

```text
1 row per sinistre + date_score + version_regle
```

Expected scores:

```text
score_client
score_conducteur
score_tiers
score_vehicule
score_geo
score_contrat
score_montant
score_delai
score_historique
score_global
```

---

## 9. Validation Principles for Codex

Codex must respect these rules.

### 9.1 Never change the grain without justification

Critical grains:

```text
dim_sinistre     = NUMSNT
fact_sinistre    = NUMSNT + GRNTSINI
dim_contrat      = NUMCNT
fact_contrat     = NUMCNT + NUMAVT + NUMMAJ
dim_geo          = normalized claim geographical zone
fact_inspection  = one vehicle inspection
fact_scoring     = sinistre + date_score + version_regle
```

### 9.2 Do not re-add removed expert objects

Do not re-add:

```text
dim_expert
expert_sk
```

unless a reliable expert source is introduced.

### 9.3 Do not duplicate geography

Current rule:

```text
client geography stays in dim_client
claim geography goes to dim_geo
fact_sinistre carries geo_sinistre_sk
dim_sinistre contains no geography
dim_client contains no geo_sk
```

### 9.4 Do not add mostly-null columns to final DWH

If a column is mostly null or not stable at the target grain, either exclude it, move it to the appropriate fact, keep it only in audit output, or document the reserve.

### 9.5 Do not auto-correct risky business data

Especially for geography:

- manual entries must be audited;
- candidate corrections must be generated;
- ambiguous cases must remain visible;
- no blind correction should be applied.

### 9.6 Keep DWH user-facing and business-readable

Avoid final DWH columns such as `*_raw`, `*_norm`, `*_clean`, `mapping_status`, `join_status`, `pipeline_status`, and `technical_rule` unless explicitly required for audit.

---

## 10. Next Steps for Codex

Priority order:

```text
1. Build or improve etl/dwh/audit/audit_dim_geo.py
2. Use data/reference/dim_geo/geo_tunisia_reference.csv if available
3. Generate dim_geo audit and correction candidate reports
4. Build fact_sinistre
5. Build fact_contrat
6. Build fact_inspection_vehicule
7. Build fact_scoring_sinistre
8. Prepare Power BI model and investigation KPIs
```

### 10.1 Immediate task: geographical audit

Codex should implement a separate audit process:

```text
etl/dwh/audit/audit_dim_geo.py
```

It should read:

```text
dwh.dim_geo
```

Compare against:

```text
data/reference/dim_geo/geo_tunisia_reference.csv
```

And output:

```text
data/quality_reports/dim_geo/dim_geo_audit_all.csv
data/quality_reports/dim_geo/dim_geo_validated.csv
data/quality_reports/dim_geo/dim_geo_correction_candidates.csv
data/quality_reports/dim_geo/dim_geo_conflicts.csv
data/quality_reports/dim_geo/dim_geo_manual_review.csv
data/quality_reports/dim_geo/dim_geo_non_corrigeable.csv
```

It must add these columns to audit reports only, not to `dwh.dim_geo`:

```text
geo_audit_status
geo_audit_reason
confidence_score
candidate_region
candidate_gouvernorat
candidate_delegation
candidate_localite
candidate_code_postal
```

Expected audit statuses:

```text
VALIDATED_REFERENCE
VALIDATED_GOV_ONLY
CORRECTION_CANDIDATE
CONFLICT
MANUAL_REVIEW
NON_CORRIGEABLE
UNKNOWN
```

No risky correction should be applied automatically.

---

## 11. DWH Target Model Summary

Validated dimensions:

```text
dim_date
dim_client
dim_camtier
dim_tiers
dim_contrat
dim_produit
dim_vehicule
dim_conducteur
dim_intermediaire
dim_sinistre
dim_garantie
dim_geo
```

Removed:

```text
dim_expert
```

Facts to build:

```text
fact_sinistre
fact_contrat
fact_inspection_vehicule
fact_scoring_sinistre
```

---

## 12. Final Modeling Reminder

The project goal is to help insurance fraud managers investigate and prioritize automobile claims.

It is not a black-box AI project and not an automatic fraud accusation system.

The final product must be:

```text
business-readable
auditable
technically clean
defensible academically
safe for decision support
```




```text
La dimension géographique des sinistres est exploitable pour les analyses par gouvernorat et région, mais la normalisation fine des localités, rues et adresses partielles fera l’objet d’une itération dédiée.
```

---

## Project Structure

`IRIS_AUTO_FRAUD` contains only active project code and final documentation.
Historical experiments, audit scripts, and cleanup utilities are externalized
to `ArchiveVHS/` and are not part of the active Git project.

### Active VHS pipeline

| Component | Path |
|-----------|------|
| VHS compute script | `etl/mart/compute_vhs_v3_candidate.py` |
| Checkpoint reference loader | `etl/mart/load_dim_checkpoint.py` |

### VHS documentation

| Document | Path |
|----------|------|
| Technical specification | `docs/vhs/vhs_calculation_method.md` |
| Business explanation (FR) | `docs/vhs/vhs_business_explanation.md` |
| Validation summary (FR) | `docs/vhs/vhs_validation_summary.md` |
| Technical diagrams | `docs/diagrams/` |
| Internal cleanup audit trail | `docs/vhs/internal_cleanup/` |

### Final validated reports

All final VHS reports are under `data/quality_reports/vhs/final/`:

- `vhs_v3_audit_summary.md` — distribution of decisions and grades for the final run
- `vhs_v2_vs_v3_comparison_summary.md` — narrative comparison V2 → V3
- `dim_checkpoint_immobilizing_update_summary.md` — reference table update log
- `v3_immobilise_fix_summary.md` — validation of the immobilizing fix (8 checks passed)

### External archive (outside Git)

`ArchiveVHS/` contains all historical VHS material including:
- pre-deletion backup of original scripts
- V1/V2 compute engines and audit scripts
- intermediate experiment reports and CSVs
- project cleanup scripts
