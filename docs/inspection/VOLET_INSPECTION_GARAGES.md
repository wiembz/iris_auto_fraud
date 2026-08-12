# Le volet inspection véhicule & garages agréés dans IRIS

> Document de présentation — chiffres mesurés le 15/07/2026 sur la base du projet.
> Public : encadrement BNA Assurances.

## 1. Pourquoi c'est un volet nouveau pour l'assurance

Traditionnellement, l'assureur ne « voit » un véhicule qu'à deux moments : à la
souscription (déclaratif) et après un sinistre (expertise). Entre les deux, l'état
réel du véhicule est un angle mort.

Le dispositif d'inspection en garage agréé comble cet angle mort : un réseau de
garages partenaires réalise des **fiches d'inspection standardisées** (source
STAFIM) qui documentent l'état constaté du véhicule — freins, suspension, moteur,
carrosserie — **indépendamment de tout sinistre**. Pour l'assureur, c'est une
source de vérité terrain inédite :

- l'état du véhicule est constaté par un professionnel, daté et signé par un garage identifié ;
- l'information existe **avant** le sinistre éventuel — elle ne peut pas être
  reconstruite a posteriori ;
- elle est structurée (points de contrôle standardisés), donc exploitable par un
  système d'aide à l'analyse comme IRIS.

## 2. Le dispositif tel qu'il existe dans les données

### 2.1 Volumétrie

| Indicateur | Valeur |
|---|---|
| Inspections chargées | **284** (274 véhicules distincts) |
| Période couverte | octobre 2024 → mai 2026 |
| Points de contrôle standardisés | **43**, organisés en 5 zones |
| Observations de checkpoints | **12 212** |
| Inspections complètes | 274 / 284 (96,5 %) |
| Inspections appariées à un véhicule du portefeuille | 276 / 284 (97,2 %) |
| Kilométrage moyen des véhicules inspectés | ~213 000 km |

Les 5 zones de contrôle : tour du véhicule, intérieur, sous le capot,
sous le véhicule, entretien.

### 2.2 Le réseau de garages agréés (les « agents de contrôle »)

14 garages partenaires ont réalisé les inspections, répartis sur le territoire :

| Garage agréé | Ville | Inspections | Anomalies moyennes |
|---|---|---|---|
| STE SELECTION AUTO | Sfax | 96 | 6,3 |
| STE MECAREPAR | Mghira | 51 | 2,8 |
| STE BM ROUTE X | Le Bardo | 34 | 1,6 |
| HM AUTO | Bizerte | 23 | 3,0 |
| STE GARAGE EXPERT AUTO | Sfax | 21 | 5,9 |
| CHECK AUTO | Menzel Bouzelfa | 18 | 5,0 |
| STE SMA SIDI | Fathallah | 14 | 10,3 |
| SMAOUI AUTO SERVICES SAS | Mnihla | 9 | 6,9 |
| STE MECANO DIAG | Zaouiet | 8 | 4,5 |
| STE FIX EXPRESS | Boumhel | 4 | 4,8 |
| STE BNJ EUROREPAR | Menzel Kamel | 3 | 5,0 |
| Autres (MCCS Médenine, Mansour Auto Ouerdenine, EMA Zarzis) | — | 3 | — |

Lecture prudente de la dernière colonne : l'écart entre garages (1,6 à 10,3
anomalies par inspection) reflète à la fois le **profil des véhicules reçus**
et d'éventuelles **différences de pratique de saisie**. C'est un indicateur de
pilotage du réseau (harmonisation des pratiques), pas un jugement de qualité —
le volume par garage est encore trop faible pour conclure.

### 2.3 Ce que constatent les inspections

- **1 385 anomalies** relevées au total, dont **460 critiques** ;
- **192 inspections sur 284 (67,6 %)** comportent au moins une anomalie critique —
  cohérent avec un parc âgé (213 000 km en moyenne).

## 3. Ce qu'IRIS fait de ces données : deux exploitations distinctes

### 3.1 Le score de santé véhicule (VHS) — « dans quel état est ce véhicule ? »

Chaque inspection est convertie en un **score de santé 0-100** (VHS), construit
par pénalités à partir des 43 points de contrôle, avec :

- 3 sous-scores lisibles : sécurité, fonctionnel, carrosserie ;
- un grade de sécurité A-D et une décision d'état (bon état / dégradé / critique / immobilisé) ;
- des plafonds par système mécanique (freinage, suspension, moteur…) pour éviter
  qu'un même problème soit compté plusieurs fois (version V4).

État du parc inspecté (V4) : **93 bon état · 116 dégradé · 50 critique · 25 immobilisé**
(score moyen 66/100). Un score nul signifie systématiquement un véhicule hors
d'état de rouler.

Usage métier : quand un gestionnaire ouvre un dossier sinistre, il voit l'état
réel du véhicule constaté en garage — un contexte que ni la déclaration ni la
photo du sinistre ne donnent.

### 3.2 Le signal post-inspection — « le sinistre survient-il juste après une inspection ? »

IRIS croise les dates : quand un sinistre survient **peu après une inspection**
du même véhicule, un signal d'attention est émis, gradué par fenêtre temporelle :

| Fenêtre inspection → sinistre | Signaux émis |
|---|---|
| 0-7 jours | 22 |
| 8-30 jours | 40 |
| 31-90 jours | 52 |
| **Total** | **114 signaux sur 44 sinistres** |

L'idée métier : une inspection récente qui documente des défauts (ou un bon état)
juste avant un sinistre est une information précieuse pour la revue — par exemple
des dommages déclarés incohérents avec l'état constaté quelques jours plus tôt.
Le signal **suggère une vérification, il n'accuse pas** : la fenêtre temporelle
et le niveau de confiance sont affichés au gestionnaire, qui reste seul décideur.

## 4. Gouvernance et limites assumées

1. **Périmètre pilote** : 284 inspections face à 381 893 sinistres — le volet est
   en phase d'amorçage. Les indicateurs par garage sont descriptifs, pas encore
   statistiquement significatifs.
2. **Traçabilité complète** : chaque score VHS et chaque signal post-inspection
   porte sa version de calcul et son run — l'historique V1→V4 du VHS est conservé
   intégralement (aucun recalcul n'écrase le passé).
3. **Appariement contrôlé** : 97,2 % des inspections sont rattachées à un véhicule
   du portefeuille ; le taux est suivi comme indicateur de qualité.
4. **Wording non accusatoire** : ni le VHS ni le signal post-inspection ne parlent
   de fraude ; ils décrivent un état et une chronologie.

## 5. Perspectives du volet

| Extension | Condition |
|---|---|
| Montée en volume du réseau de garages | Déploiement métier BNA |
| Indicateurs de pilotage réseau (harmonisation des pratiques de saisie) | Volume suffisant par garage |
| Scénario B : croisement inspection → avenant de contrat | Données d'avenants prêtes (readiness documentée, 0 point attribué aujourd'hui) |
| Validation métier du barème VHS V4 | Atelier de validation BNA |

---

*En une phrase pour l'encadrement : le volet inspection transforme le réseau de
garages agréés en capteur terrain de l'état réel des véhicules, qu'IRIS restitue
sous deux formes complémentaires — un score de santé du véhicule pour contextualiser
chaque dossier, et un signal chronologique quand un sinistre suit de près une
inspection — le tout tracé, versionné et sans jamais se substituer au gestionnaire.*
