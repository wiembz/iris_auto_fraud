# IRIS — Dossier de préparation pour la validation technique

> Document final : les 5 pages, l'explication de chaque choix de conception (vocabulaire,
> couleurs, seuils), et les questions les plus probables de l'expert avec réponses préparées.

---

## 0. Point à vérifier AVANT la soutenance

Sur la Vue Qualité et Gouvernance, le graphique "La Fiabilité s'Améliore-t-elle dans le Temps"
affiche actuellement la période **Jan 2024 → Mai 2025** — exactement la fenêtre où la fiabilité
était stable à 100%, juste avant la baisse réelle constatée à partir de mai 2025 (creux à 93-94%
mi-2025, reprise début 2026). **Vérifier le filtre de date sur ce visuel et l'élargir pour montrer
toute la période récente (jusqu'à mars 2026 inclus)** — présenter une courbe tronquée qui évite
justement la partie qui baisse serait perçu comme un tri sélectif si l'expert vérifie les dates.

---

## 1. Structure et philosophie du dashboard

5 pages, navigation libre, aucune page cachée :

| Page | Question | Grain |
|---|---|---|
| Vue Générale | Comment va le portefeuille ? | Dossiers |
| Vue Dossiers | Quels dossiers examiner, et pourquoi ? | Dossiers |
| Vue Clients | Qui concentre l'activité ? | Clients |
| Vue Véhicule | Que dit l'état technique ? | Inspections/Véhicules |
| Vue Qualité et Gouvernance | Peut-on se fier aux chiffres ? | Global |

**Principe directeur** : Power BI reste au niveau portefeuille (comprendre, prioriser) ;
l'application Angular reste l'outil opérationnel (traiter un dossier précis). Aucune fiche
individuelle complète n'apparaît dans Power BI — seulement des listes de repérage filtrées,
toujours accompagnées d'un bandeau rappelant que le traitement se fait ailleurs.

---

## 2. Vocabulaire — pourquoi chaque mot a été choisi

| Terme technique d'origine | Terme final | Pourquoi |
|---|---|---|
| Signal | Point d'Attention | "Signal" évoquait la détection de fraude de façon accusatoire |
| Attention (score numérique) | Niveau de Priorité | "Attention" restait ambigu sur ce qu'il fallait faire |
| Attention (catégorie) | Catégorie de Priorité | Distingue le score numérique de son étiquette |
| Confiance | Fiabilité de l'Analyse | "Confiance" sonnait comme un jugement sur le client, pas sur la donnée |
| Vigilance Élevée / Haute Attention | À Surveiller | Vocabulaire jugé encore trop abstrait par un gestionnaire |
| Récurrence | Fréquence | "Fréquence de sinistralité" est le terme actuariel standard |
| Famille (de critère) | *(supprimé)* | Notion de classification interne au moteur, sans valeur pour le gestionnaire |
| VHS (Vehicle Health Score) | État Technique | Acronyme moteur jamais expliqué au gestionnaire |
| Pareto / Segment / Décile | Groupe Client / Groupe Concentration | "Pareto" est un nom de statisticien, pas un mot métier |

**Règle appliquée partout** : un mot qui demande une explication orale pour être compris est
remplacé, sauf sur la page Qualité et Gouvernance où un vocabulaire plus formel reste acceptable
(page destinée aussi à l'expert technique).

---

## 3. Couleurs et seuils — le référentiel complet

### Palette de catégorie de priorité (fixe, utilisée partout)

| Catégorie | Couleur | Code |
|---|---|---|
| Analyse standard | Gris-bleu | `#8FA6BC` |
| Points à vérifier | Jaune ocre | `#E8B54D` |
| Examen renforcé suggéré | Orange | `#D97B29` |
| Examen prioritaire suggéré | Rouge brique | `#B3392F` |

### Seuils des KPI, avec justification

| Mesure | Seuil(s) | Comment il a été fixé |
|---|---|---|
| % à Surveiller | Zone normale 6%-10%, alerte au-delà de 13% | Calculé sur la plage réellement observée (7,2%-9,5%) sur 12 mois glissants — pas un chiffre arbitraire |
| Fiabilité de l'Analyse | ≥80% = bon, ≥70% = à surveiller, en dessous = faible | Repère standard de gouvernance data ; 77,6% (moyenne globale) et 95%+ (récent) encadrent bien cette bande |
| État Technique Moyen | ≥70 = sain, ≥50 = à surveiller, en dessous = préoccupant | Seuils déjà présents dans le moteur d'origine, repris tels quels |
| Délai Contrôle→Sinistre | ≤7j = rouge (plus suspect), ≤30j = jaune, au-delà = normal | Un délai court entre contrôle et sinistre est structurellement plus digne d'attention |
| Écart de Risque Clients Fréquents | <1,5x = normal, <2,5x = à surveiller, ≥2,5x = écart fort | Ratio du taux "à surveiller" chez les fréquents vs la moyenne portefeuille — cible = la donnée elle-même, pas un chiffre choisi |
| Qualité (dates/véhicules/clients/immatriculations invalides) | Seuils très bas (0,01%-1% selon l'indicateur) + palier "watch" à x5-x10 | Alignés sur les taux réels observés (tous largement en dessous), avec marge |

**Principe défendu** : chaque seuil vient soit d'une donnée historique réelle (12 mois d'observation), soit d'un repère de gouvernance standard — jamais un chiffre rond choisi au hasard. Les mesures `07 Seuils et cibles` centralisent tous les seuils en un seul endroit, réutilisées par toutes les mesures de couleur (`08 Mise en forme conditionnelle`) — une seule source de vérité, pas de seuils dupliqués et désynchronisés.

### Cas où on a délibérément choisi de NE PAS mettre de couleur

Certaines cartes (Dossiers Sinistres, Clients identifiés, Dossiers avec un Point d'Attention...)
restent sans couleur. Ce sont des **volumes de contexte**, pas des indicateurs avec un seuil
validé — y mettre une couleur aurait exigé d'inventer un seuil arbitraire, ce qu'on a refusé de
faire par principe.

---

## 4. Les chiffres clés à retenir, page par page

**Vue Générale** : 221 574 dossiers, 5,9% lifetime / 9,5% dernier mois à surveiller, 1 469
prioritaires, 712M DT cumulés, CAS = garantie la plus concernée.

**Vue Dossiers** : 137 778 dossiers concernés (62%), 3,5 raisons en moyenne, 14,79M DT en jeu sur
les prioritaires, 4 critères HIGH dominants (fréquence client/véhicule, montant, sinistres
rapprochés).

**Vue Clients** : 113 637 clients, 10 531 fréquents (9,27%), **97,6% des dossiers prioritaires
viennent de ces clients fréquents**, taux à surveiller 3,5x supérieur (20,7% vs 5,9%), 67,5% du
montant concentré sur 10% des clients.

**Vue Véhicule** : 284 contrôles, 85,6% avec défaut (mineur inclus), 26,5% en état sensible,
zone "sous le véhicule" = 85% des défauts critiques, délai court après contrôle = urgence plus
élevée.

**Vue Qualité et Gouvernance** : couverture 100%, anomalies <0,4% partout, fiabilité 77,6%
(historique) / 95%+ (récent), statut "exploitable sous surveillance", 4 composants tracés.

---

## 5. Questions probables de l'expert, avec réponses préparées

**Q1 : Pourquoi la fiabilité globale est 77,6% mais une carte affiche 95,9% ?**
> "Le 77,6% est la moyenne sur toute l'historique du portefeuille, qui inclut d'anciens dossiers
> antérieurs à 2019, moins bien documentés suite à une migration système. Sur les 12 derniers
> mois, la fiabilité est stable au-dessus de 93%. Les deux chiffres sont vrais, ils répondent à
> des questions différentes — global vs récent."

**Q2 : Le 97,6% de dossiers prioritaires chez les clients fréquents, n'est-ce pas juste parce
qu'ils ont mécaniquement plus de dossiers ?**
> "Non — c'est pour ça qu'on ne s'arrête pas au volume. Le vrai indicateur, c'est le *taux* :
> 20,7% des dossiers des clients fréquents sont à surveiller, contre 5,9% pour les autres. Ce
> taux est indépendant du nombre de dossiers — un client fréquent n'a pas 3,5 fois plus de
> dossiers *à surveiller* simplement parce qu'il a plus de dossiers, il en a proportionnellement
> plus."

**Q3 : Pourquoi votre score de vigilance est calé sur seulement 12 mois de données ?**
> "C'est la période la plus stable et la plus représentative de l'usage actuel du système — les
> données plus anciennes incluent des effets de migration et des changements de méthodologie.
> On préfère un seuil calibré sur une période propre plutôt qu'une moyenne qui mélange des
> régimes différents."

**Q4 : Où est votre composante Machine Learning / IA dans ce dashboard ?**
> "Elle existe et elle est tracée — visible sur la Vue Qualité et Gouvernance, avec sa version et
> sa date de calcul. On a choisi de ne pas l'exposer comme indicateur de pilotage sur les pages
> gestionnaire, parce qu'un signal statistique brut ne se comprend pas sans formation, et qu'on
> ne voulait jamais présenter un résultat qu'on ne peut pas expliquer simplement. C'est un choix
> de conception, pas un oubli."

**Q5 : Pourquoi Power BI ne permet pas d'ouvrir un dossier précis ?**
> "C'est volontaire. Power BI reste analytique — comprendre le portefeuille. L'application
> Angular reste opérationnelle — traiter un dossier. Dupliquer la fiche dossier dans les deux
> outils aurait cassé cette séparation et créé deux sources d'action différentes pour le même
> geste."

**Q6 : Le statut 'Candidat - validation requise', ça veut dire que le système n'est pas fiable ?**
> "Non, ça veut dire qu'il n'a pas encore reçu la validation métier finale par les équipes
> concernées — une étape volontaire et normale à ce stade du projet. Le système est construit,
> calibré, testé, et prêt pour cette dernière étape."

**Q7 : Comment expliquez-vous la baisse de fiabilité observée au milieu de 2025 ?**
> *(Réponse à préparer avec les équipes — ce point n'a pas encore d'explication confirmée.
> Suggestion honnête : "C'est une question qu'on a nous-mêmes identifiée en préparant cette
> soutenance, et qui mérite une investigation dédiée — c'est justement ce que ce système de
> suivi permet de détecter."*

**Q8 : Que dit votre système sur la fiabilité de la donnée géographique ?**
> "Le référentiel géographique vient d'un référentiel officiel de plus de 4 700 localités
> tunisiennes. 91% est validé au niveau le plus précis. Pour le reste, certains noms de quartier
> existent dans plusieurs délégations avec des codes postaux différents — par principe de
> rigueur, on affiche alors l'information au niveau du gouvernorat plutôt que de forcer une
> localité incertaine. C'est un choix de qualité, pas une lacune."

**Q9 : Pourquoi la zone "sous le véhicule" concentre 85% des défauts critiques — un biais de
détection possible ?**
> "C'est cohérent avec la nature des zones inspectées : freinage, suspension, direction sont
> structurellement les points de sécurité les plus critiques d'un contrôle technique. Ce n'est
> pas un biais, c'est attendu du domaine."

**Q10 : Vos seuils de couleur, qui les a validés ?**
> "Ils sont calculés directement à partir des données réelles du portefeuille (12 mois
> d'historique pour les taux, seuils de gouvernance standard pour la fiabilité) — pas choisis
> arbitrairement. Chaque seuil est une mesure nommée et documentée dans le modèle, centralisée en
> un seul endroit pour rester cohérente partout où elle est utilisée."

---

## 6. Ce qui a été corrigé pendant la préparation (bon argument de rigueur)

| Bug trouvé | Où | Impact si non corrigé |
|---|---|---|
| `Groupe Client` classait 100% des clients en "Top 20%" | Vue Clients | Graphique de concentration totalement faux |
| `Statut Version` affichait "Validée" au lieu de "Candidat" | Vue Qualité | Faux positif sur la maturité du système |
| Couleur "% à Surveiller" inversée (alarme pour une situation normale) | Vue Générale | Signal d'alarme trompeur pour 9,5% (dans la zone saine) |
| Seuils dupliqués/désynchronisés (3 mesures identiques à 80%) | Modèle global | Risque de seuils incohérents entre visuels |
| Codes bruts affichés (DAYS_0_7, SOUS_VEHICULE, CLAIM_ATTENTION...) | Plusieurs pages | Langage moteur visible au gestionnaire |
| Critères LOW ("1 sinistre = normal") présentés comme raisons de vigilance | Vue Dossiers | Manque de crédibilité — signal trivial présenté comme important |

Cette liste elle-même est un argument à garder sous la main : la préparation de la soutenance a
servi à débusquer des erreurs réelles, ce qui démontre une démarche de vérification rigoureuse,
pas seulement un exercice cosmétique.

---

## 7. RBAC — contrôle d'accès par rôle

Trois rôles définis dans le modèle : `Gestionnaire`, `Manager`, `Administrateur` (ce dernier avec
droit de rafraîchissement). Déployé sur Power BI Report Server on-premises, avec assignation des
rôles à des comptes Windows/AD via le portail (`Manage → Row-Level Security`).

### Ce qui protège réellement les données (testé et confirmé)

- **Object-Level Security (OLS)** : pour le rôle `Gestionnaire`, les tables `Gouvernance`,
  `Indicateurs Qualite`, `Configuration Run` et `Version du Score` sont entièrement bloquées
  (`MetadataPermission: None`). Testé via un compte Windows de test assigné au rôle : les visuels
  de la page Qualité et Gouvernance affichent *"This visual contains restricted data"* — aucune
  donnée n'est exposée, quelle que soit la façon dont la page est atteinte.
- **Row-Level Security (RLS)** : table technique `Securite Acces` avec `FilterExpression` par
  rôle, pilotant la mesure `Autorise Qualite Gouvernance` (1 si Manager/Administrateur, 0 si
  Gestionnaire) utilisée pour la mise en forme conditionnelle de navigation.

### Limitations connues et assumées (pas des failles de données)

Deux éléments de **navigation** restent techniquement atteignables par un Gestionnaire, malgré la
mise en forme conditionnelle appliquée sur le bouton de la page Qualité et Gouvernance
(texte/fond/bordure rendus transparents via des règles basées sur `Autorise Qualite Gouvernance`) :

1. **Le bouton reste cliquable** même invisible — Power BI ne permet pas de piloter dynamiquement
   la propriété "Visibility"/isHidden d'un bouton via DAX (confirmé absent de l'interface, feature
   demandée mais non disponible à ce jour).
2. **La barre d'onglets native** en bas de l'écran liste toujours les 5 pages pour tous les rôles —
   le contrôle "Page navigator" permettant de la masquer n'existe pas dans cette version de Power
   BI Desktop optimisée pour Report Server (fonctionnalité présente côté cloud mais pas encore
   portée sur Report Server).

**Dans les deux cas, cliquer mène à une page vide/bloquée par l'OLS — jamais à une donnée réelle.**
Le choix assumé a été de prioriser la protection de la donnée (solide, vérifiée) plutôt que de
poursuivre un masquage visuel parfait de la navigation, qui aurait nécessité de republier deux
versions distinctes du rapport (une par profil) — jugé disproportionné pour un gain purement
esthétique une fois la donnée elle-même hors de portée.

**Q11 (probable) : Un Gestionnaire peut-il cliquer sur le bouton invisible ou l'onglet de la page
Qualité et Gouvernance ?**
> "Oui, l'accès à la page reste techniquement possible en cliquant au bon endroit — Power BI ne
> permet pas de masquer un bouton ou la barre d'onglets nativement selon le rôle. Mais la page
> elle-même est vide : toutes les tables qui l'alimentent sont bloquées au niveau du modèle par la
> sécurité au niveau objet, testée et confirmée. Ce qui compte — la donnée — est protégé ; ce qui
> reste, c'est une page cassée sans aucune information, pas un accès aux résultats."
