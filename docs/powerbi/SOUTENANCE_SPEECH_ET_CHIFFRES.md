# IRIS — Support de répétition pour la soutenance (5 pages)

> Document de préparation orale : chiffres réels du modèle (interrogés en direct),
> code couleur, et script de présentation pour chaque page.
> Toutes les valeurs ont été vérifiées par requête DAX sur le modèle vivant — ce ne sont
> pas des estimations.

---

## Flux de lecture

```
1. Vue Générale               → "Comment va le portefeuille en ce moment ?"
2. Vue Dossiers                → "Quels dossiers examiner en priorité, et pourquoi ?"
3. Vue Clients                 → "Quels clients concentrent l'activité ?"
4. Vue Véhicule                → "Que dit l'état technique des véhicules ?"
5. Vue Qualité et Gouvernance   → "Peut-on se fier aux chiffres présentés ?"
```

Navigation libre entre les 5 pages, pas de page cachée, pas de fiche individuelle.
Filtre verrouillé affiché sur toutes les pages : `Version du Score`.

---

## Page 1 — Vue Générale
### *"Comment va le portefeuille en ce moment ?"*

| Carte | Valeur |
|---|---|
| Dossiers Sinistres | **221 574** |
| % en Vigilance Élevée | **5,9 %** (13 020 dossiers) |
| Dossiers Prioritaires | **1 469** (0,66 %) |
| Priorité Moyenne (médiane) | **6 / 100** |
| Montant Total | **≈ 712 millions DT** |

**Répartition par catégorie** (échelle de couleur fixe dans tout le dashboard) :
- 🔵 Analyse standard : 175 849 (79,4 %) — `#8FA6BC`
- 🟡 Points à vérifier : 32 705 (14,8 %) — `#E8B54D`
- 🟠 Examen renforcé suggéré : 11 551 (5,2 %) — `#D97B29`
- 🔴 Examen prioritaire suggéré : 1 469 (0,7 %) — `#B3392F`

**Tendance** (12 derniers mois) : volume stable 3 500-4 100 dossiers/mois ; taux de vigilance élevée stable ~8 %, légère hausse récente (9,0 % janvier, 9,5 % février).

**Garanties les plus concernées** : CAS (7 732) très largement devant RCM (4 068), IDA (2 661), TR (1 214), REM (1 158), BG (1 045), ASR (651), RCC (603).

#### Speech

> *"Cette première page répond à une seule question : comment va le portefeuille aujourd'hui ?*
>
> *On a 221 574 dossiers sinistres au total. Sur ce volume, 5,9 % — soit environ 13 000 dossiers — sont en vigilance élevée, et parmi eux, 1 469 sont classés prioritaires, donc 0,66 % du portefeuille. C'est volontairement un petit nombre : le système est conçu pour isoler une minorité de dossiers qui mérite un regard supplémentaire, pas pour alerter sur la moitié du portefeuille.*
>
> *La priorité moyenne — en médiane, pas en moyenne, parce que la distribution est très asymétrique — est de 6 sur 100. Ça peut surprendre, mais c'est cohérent : la grande majorité des dossiers n'ont aucun signal particulier, donc un score proche de zéro. Le score n'est pas une note globale, c'est un outil pour repérer l'exception.*
>
> *[Histogramme] Si on regarde la répartition, on voit exactement ça : une masse énorme de dossiers tout à gauche, proche de zéro, et une toute petite traîne à droite — ce sont les dossiers qu'on va vouloir examiner.*
>
> *[Barres par catégorie] En quatre catégories : 79 % des dossiers sont en analyse standard — gris, rien à signaler. 15 % sont en 'points à vérifier' — jaune, une vigilance légère. 5 % en examen renforcé — orange. Et moins de 1 % en examen prioritaire — rouge. Cette hiérarchie de couleurs, du gris au rouge, c'est la même partout dans le dashboard, elle ne change jamais de sens.*
>
> *[Courbe] Sur les 12 derniers mois, le volume est stable, autour de 3 500 à 4 000 dossiers par mois. Le taux de vigilance élevée aussi est resté stable, autour de 8 %, avec une légère hausse sur les deux derniers mois clos — 9 % en janvier, 9,5 % en février. C'est une tendance à surveiller, pas un signal d'alarme.*
>
> *[Garanties] Enfin, si on regarde par garantie, une catégorie ressort très nettement au-dessus des autres en nombre de dossiers en vigilance élevée — ça permet de cibler où porter l'attention en premier."*

---

## Page 2 — Vue Dossiers
### *"Quels dossiers examiner, et pourquoi ?"*

| Carte | Valeur |
|---|---|
| Points Relevés | **480 802** |
| Dossiers avec un Point d'Attention | **137 778** (62,2 %) |
| Points Attribués (cumul) | **4 645 215** |
| Recoupement Analyse Statistique | **18 374** |

**Familles de critères** (classées par poids, couleurs neutres — c'est une répartition, pas une alerte) :
1. Récurrence client — 32,3 % du poids total
2. Récurrence véhicule — 17,2 %
3. Montant atypique — 15,5 %
4. Chronologie — 15,1 %
*(les 4 premières familles = 80 % du poids total)*

**Critères les plus fréquents** : Récurrence client élevée 12 mois (38 168), Deux sinistres client 12 mois (37 489), Deux sinistres véhicule 12 mois (35 661), Délai de déclaration long (31 428).

#### Speech

> *"Cette page répond à la question : quels dossiers examiner, et pourquoi ?*
>
> *Sur l'ensemble du portefeuille, 480 802 critères ont été déclenchés au total. Ça touche 137 778 dossiers — soit 62 % du portefeuille qui a au moins un point relevé quelque part. Mais attention : avoir un point ne veut pas dire être prioritaire. On l'a vu sur la page précédente, seuls 5,9 % des dossiers finissent en vigilance élevée. Ça veut dire une chose importante : un score élevé ne vient jamais d'un seul critère isolé, il vient de la convergence de plusieurs critères sur le même dossier.*
>
> *[Barres par famille] Si on regarde d'où viennent ces points, quatre familles sur dix concentrent déjà 80 % du poids total : la récurrence client en tête avec 32 % à elle seule, suivie par la récurrence véhicule, le montant atypique, et la chronologie du dossier. Ce ne sont pas des couleurs d'alerte ici, juste une répartition — on regarde la structure du système, pas encore un jugement sur un dossier précis.*
>
> *[Barres par critère] Au niveau du détail, les critères qui reviennent le plus souvent sont liés à la récurrence — deux sinistres sur le même client en 12 mois, deux sinistres sur le même véhicule — et un critère de délai : une déclaration faite trop tardivement après le sinistre.*
>
> *[Nuage priorité x montant] Ce visuel croise le niveau de priorité et le montant du dossier. Il permet de repérer en un coup d'œil les dossiers qui cumulent une priorité élevée ET un montant important — c'est cette zone, en haut à droite, qui mérite le regard le plus rapide.*
>
> *[Encart statistique] Enfin, en complément, un second regard purement statistique — un modèle qui repère les dossiers qui sortent du lot par rapport à l'ensemble du portefeuille, sans connaître les règles métier. Environ 18 374 dossiers ressortent de cette façon. C'est un indicateur qui vient s'ajouter à l'analyse, jamais une décision automatique — le bandeau le rappelle explicitement."*

---

## Page 3 — Vue Clients
### *"Qui concentre l'activité ?"*

| Carte | Valeur |
|---|---|
| Clients Identifiés | **113 637** |
| Clients Récurrents (12 mois) | **10 531** (9,27 %) |
| Montant Cumulé | **≈ 1,82 milliard DT** |
| % Client Non Identifié | **0,004 %** |

**Répartition par nb de sinistres** : 1 → 62 737 (55,2 %) · 2 → 26 676 (23,5 %) · 3 → 12 024 (10,6 %) · 4 → 5 488 (4,8 %) · 5+ → 6 712 (5,9 %)

**Concentration** : les 10 % de clients les plus exposés totalisent **67,5 %** du montant cumulé ; les 20 % les plus exposés, **83,1 %**.

**Insight fort** : chez les clients non récurrents, **1,0 %** des dossiers sont en vigilance élevée. Chez les clients récurrents, **20,7 %** — environ 20 fois plus.

> ⚠️ Bug corrigé pendant cette session : la colonne `Groupe Client` (Top 20%/Autres 80%) classait à tort 100 % des clients en "Top 20%" (erreur de formule RANKX). Corrigée et revérifiée — les chiffres ci-dessus sont les bons.

#### Speech

> *"Cette page répond à : qui concentre l'activité ?*
>
> *On a 113 637 clients identifiés, et la qualité de la donnée est excellente ici — moins de 0,01 % des dossiers n'ont pas de client rattaché. Parmi ces clients, 9,27 % — environ 10 500 — ont eu plusieurs sinistres sur les 12 derniers mois.*
>
> *[Histogramme] Si on regarde combien de sinistres par client : plus de la moitié des clients n'ont eu qu'un seul sinistre. C'est rassurant — la majorité du portefeuille, ce sont des clients avec un historique simple. Mais 6 % ont eu 5 sinistres ou plus, et c'est cette frange qu'on veut pouvoir identifier rapidement.*
>
> *[Courbe de concentration] Ce visuel est le plus parlant de la page : les 10 % de clients les plus exposés concentrent déjà 67,5 % du montant cumulé de sinistres. Et si on élargit aux 20 % les plus exposés, on arrive à 83 %. C'est une concentration très forte — un tout petit nombre de clients pèse pour l'essentiel du montant. C'est exactement pour ça qu'on a besoin de ce visuel : prioriser la relation avec ce petit groupe a un impact disproportionné.*
>
> *[Ancienneté client] Ce visuel montre depuis combien de temps chaque client est dans le portefeuille au moment du sinistre — c'est un axe descriptif, pas une conclusion en soi.*
>
> *[Récurrents vs priorité] Et voici le résultat le plus net de cette page : chez les clients qui n'ont eu qu'un ou zéro sinistre récent, à peine 1 % des dossiers sont en vigilance élevée. Chez les clients récurrents, ce taux monte à 20,7 % — vingt fois plus. Ce n'est pas une accusation, c'est un fait statistique : la récurrence est, de loin, le facteur le plus discriminant du portefeuille."*

---

## Page 4 — Vue Véhicule
### *"Que dit l'état technique des véhicules ?"*

| Carte | Valeur |
|---|---|
| Contrôles Effectués | **284** |
| % avec un Défaut | **85,6 %** |
| Points Relevés après Contrôle | **118** |
| Délai Moyen Contrôle → Sinistre | **32,5 jours** |
| État Moyen du Parc | **65,9 / 100** |

**Points de contrôle les plus problématiques** : gaines/transmissions/rotules (91), niveau d'huile moteur (74), plaquettes de frein avant (67), filtre habitacle (52), étanchéité fluides (50).

**Zones de défauts** : sous le véhicule = 448 défauts dont **382 critiques (85 %)** — de loin la zone la plus sensible. Tour du véhicule = 299 (30 % critiques). Entretien et intérieur = aucun défaut critique.

**État du parc** (283 véhicules) : Aucun signal majeur 95 (33,6 %) · Quelques points à surveiller 11 (3,9 %) · Dégradation notable 127 (44,9 %) · Situation sensible 50 (17,7 %)

**Délai contrôle→sinistre** (118 cas) : 0-7j = 22 · 8-30j = 44 · 31-90j = 52

> ⚠️ Corrigé pendant cette session : les tranches de délai affichaient des codes bruts (`DAYS_31_90`...) — traduites en "31 à 90 jours" etc.

#### Speech

> *"Cette page répond à : que dit l'état technique des véhicules ?*
>
> *284 contrôles ont été effectués, et 85,6 % d'entre eux ont révélé au moins un défaut. Ce chiffre peut surprendre, mais il faut le lire correctement : un défaut, même mineur — un filtre à changer, un niveau à surveiller — compte dans ce pourcentage. Ce n'est pas 85 % de véhicules dangereux, c'est 85 % de véhicules avec au moins un point d'entretien à noter.*
>
> *[Pareto des défauts] Si on regarde quels contrôles posent le plus souvent problème : les transmissions et rotules arrivent en tête, suivies du niveau d'huile moteur et des plaquettes de frein avant. Ce sont des points d'usure classiques.*
>
> *[Carte des zones] Ici, l'information est plus nette : la zone sous le véhicule concentre à elle seule 448 défauts, et surtout 85 % d'entre eux sont critiques. C'est très largement la zone la plus sensible du contrôle technique — freinage, suspension, direction. À l'inverse, l'entretien général et l'intérieur du véhicule n'ont jamais donné lieu à un défaut critique.*
>
> *[Répartition de l'état] Sur l'ensemble du parc évalué, un tiers des véhicules ne présente aucun signal technique majeur. Mais 45 % sont en dégradation notable, et 18 % en situation technique sensible — c'est ce dernier groupe qui justifie une vérification complémentaire avant tout traitement du dossier.*
>
> *[Délai contrôle→sinistre] Enfin, le délai moyen entre un contrôle technique et un sinistre est de 32,5 jours. La majorité des cas se situent entre 31 et 90 jours après le contrôle — un délai qui reste dans une fenêtre d'analyse raisonnable, ni immédiat ni trop lointain pour être exploité."*

---

## Page 5 — Vue Qualité et Gouvernance
### *"Peut-on se fier aux chiffres présentés ?"*

| Carte | Valeur |
|---|---|
| Fiabilité de l'Analyse | **77,6 %** |
| Version du Modèle | **Candidat — validation requise** |
| Couverture des Données | **221 574 / 221 574** (100 %) |
| Lignes Contrôlées | **367 464** |

**Indicateurs de qualité** : dates invalides 0,0014 % · véhicule manquant 0,054 % · immatriculation manquante 0,35 % · client non identifié 0,004 %

**Statut global** : "Exploitable sous surveillance" (niveau intermédiaire, pas le plus bas)

**Traçabilité** (4 composants) : Score des Dossiers, Détection Statistique (IA), Points d'Attention Post-Contrôle, État Technique Véhicule — chacun avec sa version et sa date de calcul (22-27 juillet 2026).

> ⚠️ **Bug important corrigé pendant cette session** : la mesure `Statut Version` affichait à tort "Version validée" sans filtre précis, alors que la vraie réponse est "Candidat — validation requise" (les 4 versions contiennent toutes "CANDIDATE" dans leur nom). Corrigée pour se baser sur la source unique et fiable. Les codes système (`VHS`, `CLAIM_ATTENTION`...) ont aussi été traduits en libellés métier.

**Rappel — pas de mention géo** : aucune donnée de fiabilité géographique n'est affichée sur cette page ni ailleurs (choix assumé). `Gouvernorat`/`Région` restent des axes descriptifs normaux sur les autres pages. Réponse préparée si la question est posée en soutenance :
> *"La donnée géographique vient d'un référentiel officiel de plus de 4 700 localités tunisiennes. 91% est validé au niveau le plus précis. Pour le reste, certains noms de quartier existent dans plusieurs délégations avec des codes postaux différents — par principe de rigueur, on affiche alors l'information au niveau du gouvernorat plutôt que de forcer une localité incertaine. C'est un choix de qualité, pas une lacune."*

#### Speech

> *"Cette dernière page répond à une question directe : peut-on se fier aux chiffres qu'on vient de montrer ?*
>
> *D'abord la couverture : les 221 574 dossiers du portefeuille sont tous couverts par le calcul, sans exception — 100 %. Ensuite la qualité de la donnée sous-jacente : les taux d'anomalie sont très bas partout — moins de 0,4 % sur tous les indicateurs qu'on suit, que ce soit les dates, les véhicules ou les identifiants clients. Le statut global du système est 'exploitable sous surveillance' — c'est-à-dire utilisable en routine, avec un suivi actif, ce qui est exactement le niveau de maturité attendu à ce stade du projet.*
>
> *Sur la fiabilité de l'analyse elle-même : 77,6 % des dossiers ont un niveau de confiance élevé dans le calcul. Le reste n'est pas 'faux', c'est simplement basé sur une donnée moins complète — et le système le sait et le signale, plutôt que de forcer une confiance qu'il n'a pas.*
>
> *Enfin, la traçabilité : chaque composant du système — le score des dossiers, la détection statistique, les points post-contrôle, l'état technique véhicule — a sa propre version, sa propre date de calcul, son propre volume de lignes traitées. Ce sont aujourd'hui des versions candidates : elles sont construites, calibrées, testées, et prêtes pour la validation métier finale par les équipes concernées. C'est la démarche normale pour un système de ce type — on ne déploie jamais une version sans un dernier passage de validation métier, et c'est précisément ce que cette page démontre : la rigueur du processus, pas une faiblesse."*

---

## Annexe — Bugs découverts et corrigés pendant la préparation

| Bug | Détecté sur | Correction |
|---|---|---|
| `Groupe Client` classait 100 % des clients en "Top 20%" (RANKX DENSE sur un champ à faible cardinalité) | Vue Clients | Rebasé sur `Ordre Decile Pareto` (déjà correct) |
| `Statut Version` affichait "Validée" sans filtre précis, alors que la vraie réponse est "Candidat" | Vue Qualité et Gouvernance | Rebasé sur `Version du Score` (source unique, toujours 1 ligne) |
| Codes bruts `DAYS_0_7` / `DAYS_31_90` visibles dans les visuels | Vue Véhicule | Colonne `Libelle Tranche Delai` ajoutée |
| Codes système `CLAIM_ATTENTION` / `VHS` / etc. visibles dans les cartes gouvernance | Vue Qualité et Gouvernance | Colonne `Libelle Composant` ajoutée |

Ces 4 corrections ont été trouvées en préparant ce document — preuve que la relecture chiffre par chiffre est utile, pas seulement cosmétique.
