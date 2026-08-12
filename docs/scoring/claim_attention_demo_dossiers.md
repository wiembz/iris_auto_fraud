# Dossiers de démonstration — Claim Attention Hybrid ML V1

**Date de sélection :** 2026-08-02
**Run utilisé :** `IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE_20260802_011048` (après correction du bug conducteur — voir note en bas de page)
**But :** 4 dossiers réels, un par niveau d'attention, pour illustrer en démo/soutenance que chaque raison affichée est chiffrée et vérifiable, jamais une accusation.

Comment les retrouver dans l'application : coller le numéro de dossier dans la recherche globale ou la file de travail, ou naviguer directement vers `/app/claims/<claim_sk>`.

---

## 1. Analyse standard — `S20511000014794|RCM` (claim_sk 150077)

**Score : 24/100** · Confiance élevée · Garantie RCM · Montant 1 950 TND (10/08/2020)

Un dossier avec quelques signaux de contexte, mais rien qui justifie un examen — bon exemple pour montrer que le score ne s'affole pas sur du bruit normal.

| Signal | Points | Explication affichée |
|---|---:|---|
| Fréquence sinistres client | +6 | Ce client a déclaré 1 sinistre précédent au cours des 12 derniers mois. Cet antécédent, à lui seul, ne signale rien d'anormal. |
| Fréquence sinistres client | +5 | Le sinistre précédent de ce client remonte à seulement 7 jour(s). |
| Fréquence sinistres véhicule | +5 | Le sinistre précédent sur ce même véhicule remonte à seulement 7 jour(s). |
| Fréquence sinistres garantie | +4 | Le sinistre précédent de ce client sur cette même garantie remonte à seulement 7 jour(s). |
| Signal statistique (ML) | +4 | Ce dossier se situe au 92e percentile d'atypicité statistique de la population de ce run. |

**Point de démo :** même avec 5 signaux actifs, le total reste sous le seuil "à vérifier" — montre que le score cumule sans s'emballer.

---

## 2. Points à vérifier — `G25511000002829|REM` (claim_sk 2237)

**Score : 49/100** · Confiance élevée · Garantie REM · Montant 330,82 TND (19/06/2025)

Le montant est proportionnellement très élevé pour cette garantie, malgré une somme absolue modeste — bon exemple pour expliquer que "montant atypique" compare au profil de la garantie, pas à une valeur absolue.

| Signal | Points | Explication affichée |
|---|---:|---|
| Montant atypique | +20 | Le montant évalué est nettement supérieur au profil habituel de cette garantie (au 94e percentile, soit 6,8 fois le montant médian habituel). |
| Fréquence sinistres client | +6 | Ce client a déclaré 1 sinistre précédent au cours des 12 derniers mois. |
| Fréquence sinistres client | +5 | Le sinistre précédent de ce client remonte à seulement 9 jour(s). |
| Fréquence sinistres conducteur | +5 | Le sinistre précédent rattaché à ce même conducteur remonte à seulement 9 jour(s). |
| Fréquence sinistres véhicule | +5 | Le sinistre précédent sur ce même véhicule remonte à seulement 9 jour(s). |
| Fréquence sinistres garantie | +4 | Le sinistre précédent de ce client sur cette même garantie remonte à seulement 9 jour(s). |
| Signal statistique (ML) | +4 | Ce dossier se situe au 93e percentile d'atypicité statistique. |

**Point de démo :** "6,8 fois le montant médian" est le genre de preuve concrète qu'un gestionnaire peut vérifier en 30 secondes sur le dossier papier.

---

## 3. Examen renforcé suggéré — `S23530000000373|RCDE` (claim_sk 288098)

**Score : 74/100** · Confiance élevée · Garantie RCDE · Montant 1 600 TND (22/04/2023)

Le meilleur exemple pour montrer la règle "couple client-tiers répété" livrée cette session — et son avertissement de prudence intégré au texte.

| Signal | Points | Explication affichée |
|---|---:|---|
| Tiers | +18 | Ce client et ce tiers (identifié par son nom) apparaissent ensemble dans 2 dossiers distincts. Ce rapprochement, basé sur le seul nom du tiers, mérite une vérification auprès du constat — **ce n'est pas une preuve en soi**. |
| Fréquence sinistres client | +12 | Ce client a déclaré 2 sinistres au cours des 12 derniers mois. |
| Fréquence sinistres tiers | +10 | Ce tiers est impliqué dans 2 sinistres au cours des 12 derniers mois. |
| Fréquence sinistres véhicule | +10 | Ce véhicule est associé à 2 sinistres au cours des 12 derniers mois. |
| Fréquence sinistres conducteur | +10 | Ce conducteur est rattaché à 2 sinistres au cours des 12 derniers mois. |
| Chronologie | +8 | Ce sinistre a été déclaré 112 jours après sa survenance, un délai très long. |
| Signal statistique (ML) | +4 | 94e percentile d'atypicité. |
| Montant atypique | +2 | Au 89e percentile de la garantie, soit 1,7 fois le montant médian. |

**Point de démo :** montrer le ton du signal Tiers — signale sans accuser, et dit explicitement au gestionnaire que ce n'est pas une preuve.

---

## 4. Examen prioritaire suggéré — `S22510000001806|RCC` (claim_sk 212318)

**Score : 80/100** · Confiance élevée · Garantie RCC · Montant 26 700 TND (23/11/2022)

Le dossier le plus riche : 9 signaux sur 6 familles différentes, montant élevé, tiers non identifié et signal ML au 99e percentile.

| Signal | Points | Explication affichée |
|---|---:|---|
| Historique | +15 | Ce client a déclaré 2 sinistres en seulement 30 jours. |
| Fréquence sinistres client | +12 | Ce client a déclaré 2 sinistres au cours des 12 derniers mois. |
| Fréquence sinistres véhicule | +10 | Ce véhicule est associé à 2 sinistres au cours des 12 derniers mois. |
| Signal statistique (ML) | +10 | Ce dossier se situe au **99e percentile** d'atypicité statistique de la population. |
| Fréquence sinistres tiers | +10 | Ce tiers est impliqué dans 9 sinistres au cours des 12 derniers mois. |
| Chronologie | +8 | Déclaré 341 jours après sa survenance — délai très long. |
| Tiers | +6 | Un tiers est rattaché au dossier mais son identité (nom) n'est pas renseignée. |
| Fréquence sinistres client | +5 | Sinistre précédent remonte à 10 jours. |
| Fréquence sinistres véhicule | +4 | Sinistre précédent sur ce véhicule remonte à 10 jours. |

**Point de démo :** dossier idéal pour montrer la richesse de la vue "Pourquoi ce dossier attire l'attention" — plusieurs familles indépendantes convergent, avec un montant (26 700 TND) qui justifie à lui seul l'attention du gestionnaire.

---

## Note sur la fraîcheur des chiffres

Ces 4 dossiers ont été re-sélectionnés **après** la correction du bug "conducteur non identifié" du 2026-08-02 (voir [claim_attention_hybrid_v1_validation_report.md](claim_attention_hybrid_v1_validation_report.md)) : les deux premiers candidats "Examen prioritaire" trouvés initialement affichaient des compteurs conducteur absurdes (517 et 1154 sinistres) causés par ce bug, et ont été écartés. Les 4 dossiers ci-dessus ont été vérifiés propres sur les données corrigées.
