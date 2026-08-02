# Rapport de validation — Claim Attention Hybrid V1 (candidat)

**Date :** 2026-08-02 (mis a jour apres la correction du bug conducteur, section 8)
**Perimetre :** pipeline de priorisation des dossiers sinistre (regles metier -> score hybride -> score hybride ML), tel qu'affiche dans "Pourquoi ce dossier attire l'attention" de l'application IRIS.
**But :** photographie condensee de l'etat du scoring a date, pour revue rapide (soutenance, point d'avancement) sans avoir a rouvrir les rapports bruts par etape.

Ce document est une synthese manuelle. Les chiffres sont tires des rapports generes automatiquement a chaque recalcul, sous `data/quality_reports/scoring/`.

---

## 1. Vue d'ensemble du pipeline

| Etape | Version | Run ID | Lignes |
|---|---|---|---:|
| Regles metier | `IRIS_CLAIM_BUSINESS_RULE_SIGNAL_V1_CANDIDATE` | `..._20260802_005052` | 421 475 signaux |
| Score hybride | `IRIS_CLAIM_ATTENTION_HYBRID_V1_CANDIDATE` | `..._20260802_010740` | 367 464 scores / 410 555 details |
| Score hybride ML | `IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE` | `..._20260802_011048` | 367 464 scores / 447 302 details |
| Signal ML (Isolation Forest) | `IRIS_CLAIM_ML_ANOMALY_SIGNAL_V1_CANDIDATE` | `..._20260727_111631` | 367 464 signaux |
| Post-inspection (scenario A) | `IRIS_POST_INSPECTION_SIGNAL_V1_CANDIDATE` | `..._20260727_111523` | 118 signaux |

Le score hybride ML est celui affiche a l'utilisateur (`backend/config.py: DEFAULT_SCORE_VERSION`). Il ne modifie jamais le score V1 historique ni le VHS — les deux moteurs coexistent en lecture seule.

---

## 2. Validation technique — 0 anomalie sur toutes les etapes recalculees

| Check | Regles metier | Score hybride | Score hybride ML |
|---|---:|---:|---:|
| Doublons de grain | 0 | 0 | 0 |
| Cles requises manquantes | 0 | — | — |
| Points negatifs | 0 | — | — |
| Score hors intervalle [0, 100] | — | 0 | 0 |
| Niveau d'attention NULL | — | 0 | 0 |
| Incoherence detail/points | — | 0 | 0 |
| Explication vide | 0 | — | — |
| **Texte accusatoire** (`fraude`, `fraudeur`, etc.) | **0** | **0** | **0** |
| Signal qualite-donnees avec points > 0 | 0 | — | — |

Le controle "texte accusatoire" est bloquant (`etl/mart/compute_claim_business_rule_signals_v1_candidate.py::contains_accusatory_wording`) : un run qui en produirait un seul serait rejete avant ecriture en base. Aucun des trois runs ne declenche ce garde-fou.

---

## 3. Distribution finale (score hybride ML, 367 464 dossiers)

| Niveau d'attention | Dossiers | Part |
|---|---:|---:|
| Analyse standard | 300 111 | 81,7 % |
| Points a verifier | 48 137 | 13,1 % |
| Examen renforce suggere | 17 307 | 4,7 % |
| Examen prioritaire suggere | 1 909 | 0,5 % |

Confiance associee : HIGH 341 060 (92,8 %) / MEDIUM 80 380 (7,2 %*) / LOW 35 (<0,01 %) — *(chiffres du run regles metier ; le run score hybride ML applique sa propre repartition, voir rapport brut pour le detail exact).*

**Non-regression confirmee (2026-08-01)** : la refonte du vocabulaire ("Recurrence" -> "Frequence", preuve chiffree embarquee dans chaque explication) n'a eu **aucun impact sur les chiffres** — seul le texte a change, pas les seuils ni les points.

**Regression corrigee (2026-08-02)** : voir section 8. La distribution ci-dessus reflete l'etat *apres* cette correction (legere baisse des niveaux Points a verifier / Examen renforce / Examen prioritaire, ces dossiers etaient partiellement pousses par un faux signal conducteur).

---

## 4. Catalogue des regles actives (70 pts max, plafonnes par famille)

| Famille | Plafond | Regles actives (points) |
|---|---:|---|
| Frequence sinistres client | 25 | HIGH >=3/12m (20) · MEDIUM =2/12m (12) · LOW =1/12m (6) · recent <=30j (5) |
| Montant atypique | 25 | HIGH percentile>=0.95 (20) · MEDIUM >=0.90 (12) · LOW >=0.80 (6) |
| Chronologie | 20 | proche debut contrat (10) · avenant recent (10) · declaration rapide (10) · declaration avant sinistre (8) · delai long >=90j (8) · fenetre 90j (5) · delai 30-89j (5) |
| Frequence sinistres vehicule | 15 | HIGH >=3/12m (15) · MEDIUM =2/12m (10) · recent (5) |
| Frequence sinistres conducteur | 12 | HIGH >=2/12m (10) · recent (5) |
| Frequence sinistres tiers | 12 | HIGH >=2/12m (10) · recent (5) |
| Frequence sinistres garantie | 10 | HIGH >=3/12m (12) · MEDIUM =2/12m (8) · recent (4) |
| Tiers (non plafonnee) | — | Identite tiers incomplete (6) · Couple client-tiers repete >=2 dossiers (18) |
| Qualite donnees | 0 pt | Documente uniquement, n'augmente jamais l'attention |

Signal ML complementaire : Isolation Forest calibre par percentile de population, 0 a 10 pts (>=98e percentile = 10 pts, >=95e = 7 pts, >=90e = 4 pts).

### Regles desactivees (code present, non appelees par le moteur)

| Regle | Raison |
|---|---|
| `GEO_CLAIMS_12M_HIGH` / `GEO_RECENT_PREVIOUS_CLAIM` | Seuil absolu (3 sinistres/12 mois/zone) se declenchait sur 98 % des dossiers sur donnees reelles — densite urbaine normale, pas un signal. A recalibrer par percentile avant reactivation. |
| `TIERS_REPEATED_ACROSS_CLIENTS` | Se declenchait sur ~19 % des dossiers non pas a cause du rapprochement nom-seul (attendu), mais parce que `nom_tiers` contient massivement des causes de sinistre ("DERAPAGE" 182x, "BRIS DE GLACE" 135x) et des placeholders plutot que de vrais noms de tiers. Necessite un chantier de qualite de donnees sur `dim_tiers` avant reactivation. |

---

## 5. Tests

**262 / 264** tests passent (suite complete `pytest`, 2026-08-02).

Les 2 echecs restants (`test_airflow_dag_contract.py`, `test_backend_readonly_api.py::test_backend_service_sql_stays_read_only`) proviennent de fichiers non commites d'un chantier parallele en cours (gestion d'images d'inspection STAFIM, DAG Airflow) et ne sont pas lies au scoring ni a l'authentification traites ici.

---

## 6. Limites connues et decisions en attente (BNA)

- **VHS score 0** : 4 vehicules a score exactement 0, verifies comme reellement CRITIQUE/IMMOBILISE (inspection complete, non-artefact). Masques de la liste par defaut sur demande metier ; KPI globaux inchanges. Decision en attente : plancher de decision automatique ou score borne par construction.
- **`fin_effet < debut_effet`** sur 8,5 % des contrats (dwh, non lie au bug de dates corrige en juillet) : pattern source a interpreter avec le metier (avenants/resiliations retroactives ?).
- **Reserves qualite DWH documentees, non bloquantes** : variantes d'ecriture des noms tiers (dim_tiers), completude partielle de dim_conducteur (91,3 % de couverture), ~8,8 % des localites geo en statut PARTIAL (ambiguite structurelle, pas une erreur).
- **Authentification** : le role est resolu par annuaire email cote backend (plus de choix libre cote utilisateur), mais sans mot de passe — a completer si IRIS depasse le cadre pilote.

---

## 7. Correction appliquee le 2026-08-02 — signal "Frequence sinistres conducteur" fausse

**Constat :** en preparant des dossiers de demonstration, deux candidats "Examen prioritaire" affichaient des compteurs absurdes ("Ce conducteur est rattache a 517 sinistres", "1154 sinistres"). Investigation :

- Certains `conducteur_sk` de `dwh.dim_conducteur` n'ont ni nom ni numero de permis, mais recoivent quand meme une cle technique reelle (non nulle) au lieu d'etre traites comme "conducteur inconnu" (comme le sk=0 deja exclu).
- Pire : d'autres `conducteur_sk` ont un `nom_conducteur` renseigne mais qui n'est pas un nom -- ce sont des circonstances d'accident ("EN STATIONNEMENT", "SANS CONDUCTEUR", "EN ARRET") avec **au moins 6 variantes orthographiques** de "stationnement" repertoriees. Un filtre par mot-cle aurait ete aussi fragile que celui deja ecarte pour `nom_tiers`.

**Preuve retenue :** sur la population courante (367 464 dossiers), tout `conducteur_sk` lie a plus de ~20 sinistres s'est revele etre a 100 % un de ces placeholders (verifie manuellement sur les 48 cles concernees) ; les vrais conducteurs individuels plafonnent naturellement a quelques sinistres.

**Correction :** `etl/mart/compute_claim_business_rule_signals_v1_candidate.py` exclut desormais du calcul de recurrence conducteur :
1. les `conducteur_sk` sans nom NI permis (`dwh.dim_conducteur`) ;
2. tout `conducteur_sk` lie a plus de `DRIVER_KEY_MAX_PLAUSIBLE_CLAIMS = 20` sinistres dans le lot traite (signal de volume, pas de texte -- robuste aux fautes de frappe).

Aucun seuil ni point de la regle `DRIVER_CLAIMS_12M_HIGH` (>=2 sinistres = signal) n'a change : c'est une correction de qualite des cles d'entree, pas une recalibration.

**Impact mesure :**
- Signaux "Frequence sinistres conducteur" : 48 295 -> 11 698 (-76 %).
- Dossiers avec un signal conducteur actif : 28 788 -> 9 914.
- Distribution globale : legere baisse des trois niveaux au-dessus de "Analyse standard" (section 3), aucun dossier ne passe d'un niveau a un autre par un saut brutal.
- 2 tests de regression ajoutes (`test_degenerate_conducteur_sk_never_produces_a_driver_recurrence_signal`, `test_overloaded_conducteur_sk_excluded_by_claim_volume_even_with_a_real_looking_name`), plus le test existant `test_real_repeated_conducteur_sk_still_fires_when_not_degenerate` confirmant que les vrais recidivistes continuent de declencher le signal.

## 8. Ce qui n'a pas ete touche

Recalibration de seuils/poids, reactivation des regles desactivees, regle "conducteur != titulaire" (infaisable avec les donnees actuelles — aucun champ nom exploitable), et toute modification des zones administration / analytics / audit / images STAFIM (chantier parallele en cours, non commite).
