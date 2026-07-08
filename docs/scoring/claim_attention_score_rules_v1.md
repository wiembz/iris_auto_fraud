# Regles V1 du score d'attention dossier IRIS

> **Module :** Claim Attention Score / priorisation des dossiers sinistres automobiles  
> **Version :** `IRIS_CLAIM_ATTENTION_V1_CANDIDATE`  
> **Principe :** aide a l'analyse humaine, non preuve de fraude

---

## 1. Objectif

Ce document definit les regles candidates V1 du score d'attention dossier IRIS.

Le score sert a prioriser les dossiers sinistres automobiles a examiner. Il ne
constitue pas une accusation, une preuve de fraude ou une decision automatique.

La V1 reste volontairement deterministe et explicable.

---

## 2. Sources

La V1 utilise uniquement les features produites dans :

```text
mart.fact_claim_scoring_features
```

Version attendue :

```text
IRIS_CLAIM_ATTENTION_FEATURES_V1_CANDIDATE
```

Les features proviennent principalement de :

- `dwh.fact_sinistre`
- `dwh.fact_contrat` pour la date de debut contrat

---

## 3. Familles actives dans le score V1

Seules trois familles contribuent aux points V1.

| Famille | Poids maximum | Statut |
|---|---:|---|
| Recurrence client | 25 | Active V1 |
| Montant atypique | 25 | Active V1 |
| Chronologie | 20 | Active V1 |

Le score final est borne entre 0 et 100. La V1 peut donc produire des scores
moderes tant que les familles P2/P3 ne sont pas validees.

---

## 4. Familles exclues des points V1

Les familles suivantes sont conservees comme flags de readiness ou limites de
confiance, mais ne donnent pas de points d'attention en V1 :

- recurrence vehicule ;
- recurrence tiers / conducteur ;
- coherence geographique ;
- VHS / etat technique.

Raison : leur couverture et leur chronologie doivent encore etre auditees avec
une logique tenant compte des cles techniques `0`.

---

## 5. Regles de points

### 5.1 Recurrence client

Maximum : 25 points.

| Condition | Points |
|---|---:|
| `client_claim_count_12m >= 3` | 20 |
| `client_claim_count_12m = 2` | 12 |
| `client_claim_count_12m = 1` | 6 |
| `days_since_previous_claim <= 30` | +5 |

Le total famille est plafonne a 25 points.

### 5.2 Montant atypique

Maximum : 25 points.

| Condition | Points |
|---|---:|
| `high_amount_flag = true` | 20 |
| `amount_percentile_by_guarantee >= 0.90` ou ratio >= 2.0 | 12 |
| `amount_percentile_by_guarantee >= 0.80` ou ratio >= 1.5 | 6 |

Le total famille est plafonne a 25 points.

### 5.3 Chronologie

Maximum : 20 points.

| Condition | Points |
|---|---:|
| `claim_before_contract_start_flag = true` | 15 |
| `0 <= days_contract_start_to_claim <= 30` | 10 |
| `31 <= days_contract_start_to_claim <= 90` | 5 |
| `days_claim_to_declaration < 0` | 8 |
| `days_claim_to_declaration >= 90` | 8 |
| `30 <= days_claim_to_declaration < 90` | 5 |

Le total famille est plafonne a 20 points.

---

## 6. Confiance

Les problemes de qualite de donnees ne doivent pas augmenter le score
d'attention. Ils alimentent `confidence_level`.

Exemples :

- cle technique `0` ;
- date `0` ou invalide ;
- date sinistre future ;
- donnees avant migration 2019 ;
- dimensions optionnelles non reliees.

---

## 7. Niveaux metier

| Score | Niveau |
|---:|---|
| 0-24 | Analyse standard |
| 25-49 | Points a verifier |
| 50-74 | Examen renforce suggere |
| 75-100 | Examen prioritaire suggere |

---

## 8. Sorties attendues

Le moteur V1 produit :

```text
mart.fact_claim_attention_score
mart.fact_claim_attention_signal_detail
data/quality_reports/scoring/claim_attention_v1/
```

Les motifs principaux sont les trois signaux positifs les plus contributifs.
Les signaux de qualite des donnees peuvent apparaitre dans le detail avec
`points = 0`, afin d'expliquer la confiance sans augmenter l'attention.

---

## 9. Limites V1

La V1 n'est pas calibree sur des labels de fraude ou d'investigation humaine.
Elle doit etre presentee comme une version candidate, explicable et prudente.

Le Machine Learning reste exclu tant que des labels humains fiables ne sont pas
disponibles.
