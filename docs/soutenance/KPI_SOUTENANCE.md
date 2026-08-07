# KPIs de soutenance — IRIS Auto Fraud

> Valeurs rafraîchies le 07/08/2026 sur la base de production locale (précédente version : 15/07/2026).
> Runs de référence : `IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE_20260802_190116` (sinistres)
> et `VHS_BALANCED_V4_CANDIDATE_20260807_115527` (véhicules).
>
> **Changement notable depuis le 15/07** : le nombre de dossiers « Examen prioritaire » est
> passé de 752 à 2 251 (×3). Ce n'est pas une dérive de données : 4 règles métier ont été
> ajoutées au catalogue entre les deux dates (commits `dba7435`, `b2f8648`, `5a438cf` —
> réserve/paiement/franchise/recours, statut garantie/validité contrat, règles tiers-repeat).
> Plus de signaux couverts → plus de dossiers légitimement remontés. C'est un argument de
> couverture croissante, pas une anomalie à esquiver si le jury pose la question.

## Principe de sélection

Un jury pose trois questions ; chaque famille de KPIs répond à l'une d'elles :

| Question du jury | Famille de KPIs |
|---|---|
| « À quoi ça sert concrètement ? » | A. KPIs métier (pilotage) |
| « Peut-on faire confiance aux données ? » | B. KPIs qualité de données |
| « Le modèle est-il rigoureux ? » | C. KPIs modèle |

Règle de présentation : **3 à 4 KPIs maximum sur la slide principale** (famille A),
les familles B et C en slides d'appui ou en annexe.

---

## A. KPIs métier — pilotage stratégique

### A1. Taux de ciblage prioritaire — **0,61 %**
- **Formule** : dossiers « Examen prioritaire » / dossiers auto scorés = 2 251 / 367 464
- **Pourquoi stratégique** : c'est le KPI fondateur du projet. Un service anti-fraude ne peut
  pas relire 367 464 dossiers ; IRIS en isole 2 251, soit une file de travail humainement
  traitable (~9 dossiers/jour ouvré sur un an pour un gestionnaire).
- **Phrase jury** : « IRIS transforme un volume impossible à auditer en une file de travail
  de 2 251 dossiers, sans écarter le reste : 13 % supplémentaires restent sous vigilance graduée. »

### A2. Exposition financière sous vigilance — **50,7 M TND (7,1 % de l'exposition)**
- **Formule** : Σ montants des dossiers « prioritaire + renforcé » / Σ montants totaux
  = (6,35 M + 44,3 M) / 711,9 M TND
- **Pourquoi stratégique** : traduit le score en langage financier — 5,3 % des dossiers
  concentrent 50,7 M TND d'exposition à examiner. C'est l'argument budgétaire du projet :
  même un faible taux de fraude évitée sur ce périmètre couvre le coût de la plateforme.
- **Phrase jury** : « Le ciblage concentre l'effort humain là où se trouve l'argent :
  50,7 millions de dinars d'exposition sur seulement 5,3 % des dossiers. »

### A3. Pyramide d'attention (distribution du triage)
| Niveau | Dossiers | Part | Exposition (TND) |
|---|---|---|---|
| Examen prioritaire | 2 251 | 0,61 % | 6 350 819 |
| Examen renforcé | 17 052 | 4,64 % | 44 312 543 |
| Points à vérifier | 47 752 | 13,00 % | 130 195 046 |
| Analyse standard | 300 409 | 81,75 % | 531 017 692 |
- **Pourquoi stratégique** : montre que le système est **gradué** et non binaire
  (fraude/pas fraude). Aucun dossier n'est « acquitté » par la machine : la décision
  finale reste humaine (principe human-in-the-loop).
- **Phrase jury** : « La pyramide garantit qu'aucun dossier n'est écarté par l'algorithme ;
  elle hiérarchise l'ordre de passage devant le gestionnaire. »

### A4. Taux de véhicules inspectés nécessitant une action — **67,3 %**
- **Formule** : décisions VHS ≠ OK / inspections scorées = (116 + 25 + 50) / 284
  (DÉGRADÉ 116, IMMOBILISÉ 25, CRITIQUE 50 — score santé moyen 66/100)
- **Pourquoi stratégique** : relie l'état technique du véhicule au risque sinistre —
  un véhicule déjà dégradé avant sinistre est un contexte précieux pour la revue du dossier.
- **Phrase jury** : « Le VHS ajoute une dimension que le dossier seul ne montre pas :
  l'état réel du véhicule constaté en atelier, résumé en un score 0–100. »
- *(Chiffre inchangé depuis le 15/07 — le run VHS du 07/08 produit une distribution
  identique à celle du 22/07, aucune dérive des données sources d'inspection.)*

---

## B. KPIs qualité de données — confiance

### B1. Indice de confiance des dossiers scorés — **79,7 % HIGH**
- **Formule** : répartition du `confidence_level` calculé par dossier
  (HIGH 292 993 · MEDIUM 74 456 · LOW 15)
- **Pourquoi stratégique** : le système **auto-évalue** la fiabilité de chaque score selon
  la complétude des jointures (clés manquantes, dimensions inconnues). Un score n'est jamais
  présenté sans son niveau de confiance — honnêteté algorithmique.
- **Phrase jury** : « Chaque score est accompagné de sa propre fiabilité : environ 80 % des
  dossiers sont scorés sur données complètes, et les 20 % restants sont signalés comme tels
  au gestionnaire. »

### B2. Couverture référentielle du DWH — **100 % (0 clé orpheline)**
- **Formule** : lignes de faits avec FK résolue / lignes de faits totales, après audit
  (381 893 sinistres · 585 514 contrats · 461 882 clients · 128 037 véhicules)
- **Pourquoi stratégique** : c'est le socle. Prouvé par un **audit automatisé rejouable**
  (`etl/dwh/audit_etl_quality_completeness.py`) intégré comme gate au pipeline : le chargement
  échoue si la qualité régresse.
- **Phrase jury** : « La qualité n'est pas vérifiée une fois : elle est un portail bloquant
  du pipeline, rejoué à chaque chargement. »
- *(Dernier audit complet : run `20260726_204124` du 26/07 — 27/27 vérifications FK à
  `nonzero_orphan_fk_rate=0.0`. Un rejeu daté de la semaine de soutenance est prévu en
  tâche 3.3 du plan.)*

### B3. Traçabilité des scores — **100 % versionnés, 0 écrasement**
- **Formule** : tout score porte (score_version, score_run_id) ; les décisions humaines
  sont en append-only avec lien de correction (`corrects_decision_id`).
- **Pourquoi stratégique** : exigence d'auditabilité assurantielle — on peut rejouer
  l'historique complet : quel score, quelle version du moteur, qui a décidé quoi, et
  quelles corrections ont eu lieu, sans qu'aucune donnée n'ait jamais été modifiée.
- **Phrase jury** : « Toute décision — machine ou humaine — est datée, versionnée et
  corrigeable sans effacement : le dossier est défendable devant un auditeur. »

---

## C. KPIs modèle — rigueur technique

### C1. Cohérence score / réalité physique (VHS V4) — **100 %**
- **Formule** : véhicules à score 0 qui sont effectivement non roulants / véhicules à score 0
  = 4/4 (en V3 : 8 des 21 véhicules à 0 roulaient encore — incohérence corrigée)
- **Pourquoi stratégique** : montre la démarche d'**itération critique** V3 → V4 :
  détection d'une saturation d'échelle, correction par plafonds par système fonctionnel
  (fin du double comptage frein/suspension) et plancher roulable à 5 points.
- **Phrase jury** : « Nous avons détecté que l'échelle saturait à zéro, diagnostiqué le
  double comptage par système mécanique, et corrigé : en V4, un score nul signifie
  toujours un véhicule hors d'état de rouler. »
- *(Reconfirmé sur le run du 07/08 : 4 véhicules à score 0, tous en décision
  CRITIQUE ou IMMOBILISE — 0 en OK/DEGRADE.)*

### C2. Architecture de score hybride — 3 étages validés séparément
- **Formule** : score final = règles métier (explicables) + signaux post-inspection
  + anomalie ML (Isolation Forest), chaque étage ayant son run et son rapport de validation.
- **Pourquoi stratégique** : répond à l'objection classique « boîte noire » — le ML
  n'est qu'un étage complémentaire ; chaque signal affiché au gestionnaire est traçable
  à une règle documentée (catalogue V2 : seuils sourcés, grain validé, golden tests).
- **Phrase jury** : « Le gestionnaire ne voit jamais un score brut : il voit les raisons,
  chacune rattachée à une règle du catalogue ou à un facteur ML explicité. »

### C3. Non-régression automatisée — **264 tests verts**
- **Formule** : suite pytest couvrant parsing de dates, règles métier (golden tests),
  API en lecture seule (scan anti-écriture), chargeurs de dimensions.
- **Pourquoi stratégique** : garantit que les scores publiés ne dérivent pas silencieusement
  quand le code évolue — dont un test qui interdit structurellement toute écriture SQL
  hors du chemin de validation humaine.
- **Phrase jury** : « La contrainte lecture seule de l'API n'est pas une convention :
  c'est un test qui fait échouer la build si on la viole. »
- *(Rejoué le 07/08 : 264 passed en 7,5 s. Vérifier que l'environnement utilisé le jour J a
  pytest installé — voir tâche 3.6 du plan, les tests ne passent pas avec le `.venv` fourni.)*

### C4. Performance de restitution — **< 10 ms par page**
- **Formule** : latence de l'endpoint `/api/summary` mesurée le 07/08 par requêtes HTTP
  réelles (curl, après warm-up) : ~5 ms médian, contre ~4 s avant optimisation.
- **Pourquoi stratégique** : condition d'adoption — un outil de triage lent n'est pas
  utilisé. Montre la maîtrise de la chaîne complète (index PostgreSQL → API → Angular).
- **Phrase jury** : « L'écran du gestionnaire répond en quelques millisecondes
  sur 367 000 dossiers scorés. »
- *(Chiffre plus favorable qu'au 15/07 — ancienne mesure 83 ms, méthodologie non documentée.
  Garder « quelques millisecondes » à l'oral plutôt qu'un chiffre précis, pour rester robuste
  si la machine de soutenance est plus lente que la machine de dev.)*

---

## Slide de synthèse recommandée (« IRIS en 4 chiffres »)

| | |
|---|---|
| **367 464** | sinistres auto analysés automatiquement |
| **0,61 %** | ciblés en examen prioritaire — une file de travail humaine réaliste |
| **50,7 M TND** | d'exposition financière concentrée sous vigilance |
| **100 %** | des scores traçables : version, run, décision humaine corrigeable sans effacement |

## Pièges à éviter à l'oral

1. **Ne pas annoncer un « taux de fraude détectée »** : sans vérité terrain labellisée,
   ce chiffre n'existe pas — IRIS mesure un *taux de ciblage*, pas un taux de détection.
   L'assumer explicitement est une force académique, pas une faiblesse.
2. **Ne pas présenter le score comme une décision** : le vocabulaire officiel est
   « attention suggérée » ; la décision est toujours humaine et auditée.
3. **Toujours donner le dénominateur** : « 2 251 dossiers » ne veut rien dire seul ;
   « 2 251 sur 367 464 » raconte l'histoire.
4. Si le jury demande la validation externe : V4 VHS et le score hybride sont des
   **candidats** en attente de validation métier BNA — dire « candidat validé
   techniquement, en attente de validation métier » est la réponse exacte.
5. **Si le jury compare à une version antérieure du rapport/slides** (752 dossiers,
   40,7 M TND) : expliquer que le catalogue de règles s'est enrichi entre-temps (voir
   encart en tête de ce document) — ce n'est pas une incohérence, c'est une évolution
   datée et tracée par commit.
