# Regles V1 du module de signaux post-inspection IRIS

> **Module :** Inspection x Sinistre / Avenant - signaux post-inspection  
> **Version documentaire :** `IRIS_POST_INSPECTION_SIGNAL_RULES_V1`  
> **Principe :** aide a l'analyse humaine, non conclusion de fraude

---

## 1. Objectif

Ce document specifie les regles candidates du module post-inspection IRIS.

Le module identifie des situations post-inspection necessitant une verification
humaine prioritaire. Il croise les inspections STAFFIM, les sinistres et, lorsque
c'est mesurable, les mouvements de contrat ou avenants.

Le signal ne constitue pas une accusation, une preuve de fraude ou une decision
automatique. Il indique uniquement qu'une chronologie ou un contexte technique
documente merite une analyse gestionnaire.

---

## 2. Positionnement métier

Les gestionnaires BNA Assurances peuvent utiliser ce module pour :

- prioriser la revue de certains dossiers ;
- comprendre la chronologie inspection -> sinistre ;
- consulter le contexte technique documente lors de l'inspection ;
- identifier les zones ou checkpoints concernes ;
- demander des documents ou controles complementaires si necessaire.

Le module doit rester dans une logique de priorisation et d'aide a l'analyse.
Les libelles metier doivent parler de signal a examiner, d'element a verifier ou
de verification prioritaire suggeree.

Les elements produits par le module sont soumis a l'appreciation du
gestionnaire. La decision finale reste humaine.

---

## 3. Scenario A - Inspection -> Sinistre

Statut readiness : **GO**.

### 3.1 Regle candidate

Un lien candidat Scenario A est cree uniquement lorsque les conditions suivantes
sont reunies :

- meme `vehicule_sk` non nul entre l'inspection et le sinistre ;
- date d'inspection valide ;
- date de survenance sinistre valide ;
- date d'inspection avant ou egale a la date de survenance sinistre ;
- delai entre inspection et sinistre compris entre 0 et 90 jours calendaires ;
- anomalie inspection documentee preferee pour un signal exploitable.

Les dates doivent etre converties en vraies dates calendaires avant calcul du
delai. Il ne faut pas utiliser d'arithmetique directe de type `YYYYMMDD + 90`.

### 3.2 Buckets de delai

| Delai inspection -> sinistre | Lecture metier |
|---|---|
| 0-7 jours | Chronologie post-inspection courte, proximite forte |
| 8-30 jours | Proximite chronologique moyenne |
| 31-90 jours | Proximite chronologique faible, a examiner avec prudence |

---

## 4. Scenario A - confidence levels

La confiance qualifie la robustesse du signal. Elle ne transforme pas le signal
en preuve.

| Niveau | Conditions candidates |
|---|---|
| HIGH | Meme `vehicule_sk`, dates valides, delai 0-30 jours, anomalie documentee, zone disponible ou partiellement coherente |
| MEDIUM | Meme `vehicule_sk`, dates valides, delai 31-90 jours, anomalie documentee, mapping zone incomplet |
| LOW | Meme `vehicule_sk`, dates valides, aucune anomalie documentee ou information zone faible |
| NOT_READY | Cle vehicule manquante, date manquante, inspection apres sinistre, ou lien faible uniquement par client |

Les cas `NOT_READY` ne doivent pas produire de signal metier exploitable dans un
futur mart.

---

## 5. Zone matching strategy

Les zones d'inspection actuellement disponibles sont :

- `SOUS_VEHICULE`
- `TOUR_DU_VEHICULE`
- `INTERIEUR`
- `ENTRETIEN`
- `SOUS_CAPOT`

La zone de dommage cote sinistre n'est pas encore totalement prouvee. Les champs
sinistre disponibles peuvent aider l'analyse, mais ne suffisent pas encore a
garantir un matching fiable zone defaut -> zone sinistre.

Strategie conservative :

- si la zone sinistre est indisponible, ne pas annoncer de correspondance meme
  zone ;
- utiliser la zone inspection comme contexte technique documente ;
- ne pas convertir le contexte de zone en preuve ;
- separer clairement `defective_zone`, `claim_area` et `zone_match_status` ;
- attribuer une confiance reduite lorsque le mapping de zone est incomplet.

---

## 6. Scenario B - Inspection -> Avenant

Statut readiness : **PARTIAL**.

La validation montre que le timing inspection -> avenant est mesurable, mais que
le changement exact de couverture, produit ou garantie n'est pas encore prouve.

Regle de prudence :

- Scenario B ne doit pas recevoir de points d'attention pour le moment ;
- il ne doit pas etre integre au Claim Attention Score V1 ;
- il doit rester un controle de faisabilite et de contexte ;
- une analyse supplementaire des changements de garantie, produit ou couverture
  est necessaire avant toute exploitation metier forte.

---

## 7. Future mart output

Table cible future, a ne pas creer dans cette phase :

```text
mart.fact_post_inspection_attention_signal
```

Colonnes proposees :

| Colonne | Description |
|---|---|
| `signal_run_id` | Identifiant du run de calcul |
| `signal_version` | Version des regles |
| `scenario_code` | Scenario A ou B |
| `inspection_sk` | Cle technique inspection si disponible |
| `claim_sk` | Cle technique sinistre si applicable |
| `contract_sk` | Cle technique contrat si applicable |
| `vehicule_sk` | Cle vehicule non nulle |
| `inspection_date` | Date inspection |
| `claim_date` | Date de survenance sinistre |
| `avenant_date` | Date avenant / effet / mouvement |
| `days_inspection_to_claim` | Delai inspection -> sinistre |
| `days_inspection_to_avenant` | Delai inspection -> avenant |
| `delay_bucket` | Bucket 0-7, 8-30, 31-90 |
| `defective_zone` | Zone inspection avec anomalie |
| `defective_checkpoint_code` | Code checkpoint defaillant |
| `defective_checkpoint_label` | Libelle checkpoint defaillant |
| `claim_area` | Zone ou nature dommage cote sinistre, si fiable |
| `zone_match_status` | `MATCH`, `PARTIAL`, `UNAVAILABLE`, `NOT_ASSESSED` |
| `attention_level` | Niveau de priorisation du signal |
| `confidence_level` | `HIGH`, `MEDIUM`, `LOW`, `NOT_READY` |
| `linkage_method` | Methode de rattachement |
| `business_explanation` | Explication lisible gestionnaire |
| `created_at` | Date de creation technique |

---

## 8. Business labels

Libelles autorises pour l'interface ou les rapports :

- Signal post-inspection a examiner
- Verification prioritaire suggeree
- Chronologie post-inspection courte
- Contexte technique documente
- Confiance elevee
- Confiance moyenne
- Confiance faible

Ces libelles doivent eviter toute formulation accusatoire.

---

## 9. Non-goals

Ce module V1 ne fait pas :

- accusation de fraude ;
- conclusion automatique ;
- decision de gestion automatique ;
- modele ML ;
- Isolation Forest ;
- SHAP ;
- modification VHS ;
- modification Claim Attention Score V1 ;
- ajout de points post-inspection au score V1 ;
- creation immediate de `mart.fact_post_inspection_attention_signal`.

---

## 10. Validation evidence

La correction DWH vehicule et la validation post-inspection donnent les mesures
suivantes :

| Indicateur | Valeur |
|---|---:|
| `dwh.dim_vehicule` | 128,038 vehicules |
| `dwh.fact_sinistre` avec `vehicule_sk` lie | 377,970 |
| `dwh.fact_sinistre` avec `vehicule_sk` manquant | 3,923 |
| Taux manquant apres correction | 1.0273 % |
| Taux manquant precedent | 99.7578 % |
| Scenario A - paires inspection -> sinistre toutes dates | 937 |
| Scenario A - paires post-inspection 0-90 jours | 61 |
| Scenario A - paires 0-7 jours | 10 |
| Scenario A - paires 8-30 jours | 18 |
| Scenario A - paires 31-90 jours | 33 |
| Scenario A - liens avec anomalie inspection documentee | 50 |
| Scenario A - sinistres distincts apres inspection avec anomalie | 49 |
| Scenario B - liens inspection -> avenant 0-90 jours | 16 |
| Scenario B - statut | PARTIAL |

Repartition zone des liens candidats Scenario A :

| Zone inspection | Liens candidats |
|---|---:|
| `SOUS_VEHICULE` | 35 |
| `TOUR_DU_VEHICULE` | 34 |
| `INTERIEUR` | 27 |
| `ENTRETIEN` | 21 |
| `SOUS_CAPOT` | 20 |
| `NO_DOCUMENTED_ANOMALY` | 11 |

Ces mesures proviennent des rapports read-only generes sous :

```text
data/quality_reports/scoring/post_inspection_signals/readiness/
```

---

## 11. Recommended next step

Prochaine etape recommandee :

1. Rediger un plan d'implementation separe pour
   `mart.fact_post_inspection_attention_signal`.
2. Garder le module post-inspection separe du Claim Attention Score.
3. Implementer d'abord le mart explicatif et ses rapports de validation.
4. Valider le mapping zone inspection -> zone sinistre avant tout signal fort.
5. Auditer le detail garantie / produit / couverture avant d'utiliser Scenario B
   comme signal metier fort.
6. Decider seulement apres validation si une integration Claim Attention V1.1 est
   justifiee.

Le module peut passer a la specification technique du mart post-inspection, mais
pas encore a l'ajout de points dans le score global.
