# 50 questions qu'un expert BI peut poser — et les réponses

> Préparation de soutenance technique — spécialité Business Intelligence.
> Chaque réponse est ancrée dans les chiffres et décisions réels du projet (mesures du 15/07/2026).
> Règle d'or à l'oral : jamais « ça nous semblait bien » — toujours *donnée + objectif métier*.

---

## Thème 1 — Choix des KPI

**Q1. Pourquoi afficher 686 dossiers prioritaires plutôt que le nombre total de signaux ?**
Parce que le gestionnaire travaille au niveau du dossier, pas au niveau du signal. Plusieurs signaux
(522 420 au total) peuvent concerner un même dossier. Le KPI doit représenter la charge réelle de
travail : 686 dossiers à examiner, pas 522 420 lignes à lire.

**Q2. Pourquoi le score médian plutôt que la moyenne ?**
La distribution est très asymétrique : 52 % des dossiers scorent sous 10, quelques centaines dépassent 75.
La médiane (8/100) représente le comportement typique du portefeuille et n'est pas tirée vers le haut
par les valeurs extrêmes — qui sont précisément celles qu'on isole par ailleurs.

**Q3. Pourquoi afficher l'exposition financière ?**
La direction ne raisonne pas en nombre de dossiers mais en dinars : 64,9 M TND d'exposition sur les
niveaux sous vigilance justifient l'allocation de ressources. C'est la traduction du score en langage budgétaire.

**Q4. Pourquoi un KPI « % confiance haute » sur la page exécutive ?**
Parce qu'un chiffre présenté sans sa fiabilité invite à la sur-confiance. 80,2 % des dossiers sont scorés
sur données complètes ; le management le sait avant de tirer des conclusions. C'est un KPI d'honnêteté algorithmique.

**Q5. Pourquoi ne pas afficher un « taux de fraude détectée » ?**
Parce qu'il n'existe pas : sans vérité terrain labellisée, ce chiffre serait une invention. IRIS mesure un
*taux de ciblage* (0,3 % prioritaire), pas un taux de détection. L'assumer est une force académique.

**Q6. Pourquoi avoir limité la page exécutive à 5 KPI ?**
Un tableau de bord décisionnel met en évidence les indicateurs actionnables ; trop de KPI augmentent la
charge cognitive et ralentissent la décision. Les cinq répondent aux cinq questions du management :
volume, priorité, charge, sélectivité, montant.

**Q7. Ces KPI sont-ils actionnables ou seulement descriptifs ?**
Chacun déclenche une action : % haute attention → dimensionner l'équipe de revue ; exposition → arbitrer
les ressources ; % confiance → lancer un chantier qualité sur les segments fragiles ; prioritaires → alimenter
la worklist du jour.

---

## Thème 2 — Choix des seuils

**Q8. Pourquoi les seuils 25 / 50 / 75 pour les niveaux d'attention ?**
Ils proviennent d'un calibrage sur la distribution réelle des scores et d'un objectif métier de charge de
travail. Le code est explicite : 0-24 analyse standard, 25-49 points à vérifier, 50-74 examen renforcé,
75-100 examen prioritaire. L'objectif n'était pas de répartir uniformément mais de produire une file
réaliste : 0,3 % de prioritaires.

**Q9. Pourquoi seulement 0,3 % de dossiers prioritaires ? Ce n'est pas trop peu ?**
C'est voulu. Si 20 % des dossiers étaient prioritaires, la plateforme perdrait toute valeur opérationnelle :
personne ne peut examiner 44 000 dossiers en profondeur. 686 dossiers sur 221 574, c'est ~3 dossiers/jour
ouvré pour un gestionnaire sur un an — une charge compatible avec une revue approfondie. Un score qui
signale tout ne signale rien.

**Q10. Pourquoi les plafonds de famille 25/20/20/15 points ?**
Pour qu'aucune famille de règles ne puisse à elle seule rendre un dossier prioritaire : atteindre 75 exige
la convergence d'au moins trois familles. C'est un choix anti-faux-positifs : la récurrence client seule,
même extrême, plafonne à 25 points.

**Q11. Pourquoi le seuil « score < 70 → DÉGRADÉ » du VHS ?**
Il est cohérent avec la philosophie d'échelle documentée du VHS (90+ excellent, 70-85 bon état, en dessous :
réparations nécessaires) et validé par les invariants d'audit : aucun véhicule sans anomalie ne descend
sous 70 dans le run V4.

**Q12. Ces seuils sont-ils figés ?**
Non : ils vivent dans un catalogue de règles JSON versionné (score_version), pas dans le code. Les changer
crée une nouvelle version comparée à l'ancienne — jamais un écrasement. Statut actuel : candidats, en
attente de validation métier BNA, et affichés comme tels.

**Q13. Comment avez-vous validé les seuils sans labels ?**
Par la distribution obtenue (charge humainement traitable), par des échantillons revus métier, par les
invariants d'audit automatisés, et par la boucle de validation humaine qui accumule les labels pour un
recalibrage futur supervisé.

---

## Thème 3 — Choix des couleurs

**Q14. Pourquoi rouge / orange / ocre / gris-bleu ?**
Les couleurs ne représentent pas une accusation mais un niveau de priorité croissante : gris-bleu #8FA6BC
(standard) → ocre #E8B54D (à vérifier) → orange #D97B29 (renforcé) → rouge brique #B3392F (prioritaire).
La montée chromatique traduit la montée d'attention, sans vert « innocent » ni rouge vif « coupable ».

**Q15. Pourquoi le bleu pour la confiance ?**
Pour ne jamais mélanger deux concepts différents : l'attention (ce que le dossier mérite) et la confiance
(ce que valent les données). Une échelle bleue séparée (#2C6E8F) évite qu'un dossier « confiance limitée »
soit lu comme « suspect ».

**Q16. Votre palette est-elle accessible aux daltoniens ?**
Oui, c'est un critère de la spec : la progression joue sur la luminosité et la saturation autant que sur la
teinte, et chaque visuel double la couleur d'un libellé ou d'une valeur — la couleur n'est jamais le seul
porteur d'information.

**Q17. Pourquoi pas de vert ?**
Le vert dirait « conforme / innocent » — une conclusion que le système ne tire jamais. « Analyse standard »
n'est pas un verdict d'innocence, c'est une priorité basse. Le gris-bleu neutre le dit correctement.

---

## Thème 4 — Choix des visuels

**Q18. Pourquoi un histogramme pour les scores et pas un pie chart ?**
L'histogramme montre la *forme* de la distribution — l'asymétrie est l'information clé (52 % sous 10 points,
une traîne fine vers 90). Un camembert masque totalement cette forme, et avec des parts de 78 % contre
0,3 %, il serait illisible.

**Q19. Pourquoi un Pareto (clients, défauts checkpoints) ?**
Parce que le management veut identifier rapidement les quelques causes qui expliquent la majorité du
phénomène : quels clients concentrent le montant, quels points de contrôle concentrent les défauts.
Le Pareto répond en un regard à « où concentrer l'effort ? ».

**Q20. Pourquoi une courbe temporelle ?**
Pour détecter une dérive : si la part de haute attention monte de mois en mois, c'est soit un phénomène
réel, soit une dérive du score — dans les deux cas il faut le voir. La moyenne mobile 3 mois lisse la
saisonnalité.

**Q21. Pourquoi un scatter score × montant ?**
Pour croiser deux priorités en un visuel : un dossier à score 80 et 500 TND n'a pas le même enjeu qu'un
score 80 à 50 000 TND. Le quadrant haut-droit (hauts scores × hauts montants) est la cible de revue
immédiate — et le point d'entrée du drill-through.

**Q22. Pourquoi une matrice (évaluabilité, confiance par garantie) ?**
Pour comparer simultanément plusieurs dimensions sans multiplier les graphiques : garantie × niveau de
confiance en une lecture. C'est le visuel du croisement, là où les barres ne portent qu'un axe.

**Q23. Pourquoi un waterfall sur la page détail dossier ?**
C'est le visuel signature de l'explicabilité : il décompose le score en contributions par famille, plafonds
visibles, jusqu'au total. Le gestionnaire voit littéralement d'où viennent les 67 points — et cette égalité
détail = score est garantie par des tests.

**Q24. Pourquoi jamais de jauge ?**
Une jauge met en scène un indicateur isolé contre une cible — or aucune cible métier n'est validée (quel
serait le « bon » % de haute attention ?). Elle consomme beaucoup d'espace pour une seule valeur et
interdit la comparaison entre catégories ou périodes. Cartes KPI et histogrammes font mieux à moindre coût.

**Q25. Pourquoi jamais de camembert ?**
Dès que les parts sont déséquilibrées (78 % / 17 % / 4,7 % / 0,3 %) ou nombreuses, l'œil ne compare plus
les angles. Les barres horizontales donnent la même information, comparable et étiquetable. C'est une
règle écrite de la spec, pas une préférence.

**Q26. Pourquoi pas de carte géographique ?**
Discipline de gouvernance : le référentiel géographique (dim_geo) n'a pas encore passé son audit de
qualité (décision « GEO_READY » en attente). Afficher une carte sur des données non fiabilisées produirait
des conclusions fausses avec l'autorité visuelle d'une carte. La page est documentée comme extension.

---

## Thème 5 — Choix des pages et du storytelling

**Q27. Pourquoi cet ordre P1 → P5 ?**
C'est un parcours d'analyse décisionnel, pas une succession de graphiques : (1) comprendre le portefeuille,
(2) comprendre pourquoi certains dossiers sont prioritaires, (3) identifier les populations concernées,
(4) analyser le contexte technique véhicule, (5) vérifier la qualité des données avant de décider.
Chaque page répond à UNE question qu'un utilisateur réel se pose.

**Q28. Pourquoi une page qualité/gouvernance visible, et pas cachée en annexe ?**
Parce que « peut-on se fier à ces chiffres ? » est la dernière question avant toute décision. C'est la page
qui différencie un système gouverné d'un prototype : versions, runs, état de validation des règles,
% confiance. On la montre au jury avec fierté, pas en s'excusant.

**Q29. Pourquoi une page masquée pour le détail dossier ?**
Parce que le grain sinistre × garantie n'a de sens qu'en contexte d'investigation, jamais en navigation
libre. Le drill-through depuis P1/P2 garantit qu'on y arrive toujours *depuis* une question (« ce point
du scatter, c'est quoi ? ») — et la page reste sans aucune action, la fiche actionnable vit dans Angular.

**Q30. Pourquoi 5 pages et pas 10 ?**
Règle de dimensionnement écrite : une page = une question réelle et récurrente. La profondeur vient des
interactions (drill-through, tooltips, slicers), pas de la multiplication des pages. Les extensions
(géographie, revue humaine) sont documentées avec leur condition d'activation.

**Q31. Pourquoi séparer Power BI et l'application Angular ? N'est-ce pas redondant ?**
Non : mêmes données, métiers différents. Angular = agir sur UN dossier (worklist, revue, décision auditée) ;
Power BI = comprendre le portefeuille (cohortes, tendances, gouvernance). Règles anti-duplication écrites :
aucun bouton d'action dans Power BI, aucune fiche individuelle dans Power BI, aucune analytique de
portefeuille recalculée dans Angular.

---

## Thème 6 — Choix DAX et modèle

**Q32. Pourquoi DIVIDE et pas l'opérateur « / » ?**
DIVIDE gère nativement la division par zéro (renvoie BLANK au lieu d'une erreur) : sur un filtre qui vide
le dénominateur (ex. une garantie sans dossier), le visuel reste propre. C'est une règle de robustesse
systématique du modèle.

**Q33. Pourquoi DISTINCTCOUNT sur claim_root_id ?**
Parce que la table est au grain sinistre × garantie : un dossier à 3 garanties y apparaît 3 fois.
DISTINCTCOUNT compte chaque dossier une fois — COUNT gonflerait les KPI de +66 % (367 464 lignes pour
221 574 dossiers).

**Q34. Pourquoi MEDIAN plutôt qu'AVERAGE dans la mesure Score Median ?**
Même argument que le KPI : distribution asymétrique, la moyenne (12,4) surestime le comportement typique
(médiane 8). La mesure DAX incarne le choix statistique.

**Q35. Pourquoi une table de mesures dédiée (_Mesures) ?**
Hygiène de modèle : toutes les mesures rangées au même endroit, découvrables, au lieu d'être éparpillées
dans les tables. Facilite la revue et la maintenance.

**Q36. Pourquoi le mode Import et pas DirectQuery ?**
Les vues powerbi_v sont légères et pré-agrégées ; l'Import donne des performances constantes et permet la
planification d'actualisation côté Report Server. DirectQuery n'apporterait que de la latence — il se
justifie pour du temps réel, ce que le scoring par runs n'est pas.

**Q37. Pourquoi un schéma en étoile côté Power BI alors que le DWH est en constellation ?**
Chaque outil à son grain : Power BI reçoit une étoile simple (v_dossier_attention au centre, dimensions
autour) taillée pour l'analyse au grain dossier. La constellation complète vit dans le DWH ; la vue fait
l'adaptation. Un modèle Power BI complexe serait lent et source d'erreurs DAX.

**Q38. Pourquoi la version de score est-elle verrouillée dans une vue SQL et pas dans un filtre ?**
Parce qu'un filtre se déclique. La version est un choix de gouvernance, pas un axe d'analyse : la verrouiller
côté SQL (v_score_version_config) garantit qu'aucun utilisateur ne peut mélanger deux versions, et le
changement de version est un acte tracé en base — identique à la version servie par l'application.

**Q39. Que se passe-t-il si deux runs coexistent pour une même version ?**
La vue v_current_run résout automatiquement le run le plus récent (MAX lexicographique sur le run_id
horodaté). Jamais d'agrégation multi-runs : c'est structurellement impossible dans les vues.

---

## Thème 7 — Filtres et interactions

**Q40. Pourquoi ces slicers (période, garantie, niveau d'attention, confiance) ?**
Ce sont les quatre axes d'analyse réels des responsables sinistres : quand (période), quoi (garantie),
quelle priorité (niveau), quelle fiabilité (confiance). Pas de slicer région tant que GEO_READY n'est pas
validé — cohérence avec la gouvernance.

**Q41. Pourquoi un panneau de slicers synchronisé entre les pages ?**
Pour que le parcours P1 → P5 conserve le contexte : si j'analyse la garantie CAS sur avril, chaque page
répond dans ce même périmètre. Des filtres indépendants par page casseraient le storytelling.

**Q42. Pourquoi le drill-through plutôt que des visuels détaillés partout ?**
Pour respecter les grains : les pages agrégées restent agrégées, le détail n'apparaît que sur demande
explicite, en contexte. C'est aussi une protection cognitive — on ne noie pas le management dans les lignes.

**Q43. Pourquoi des tooltips personnalisés ?**
Pour donner la profondeur sans charger le visuel : survoler une barre donne nb dossiers + score médian +
famille dominante. L'information de second niveau est à un survol, pas dans un 7e graphique.

---

## Thème 8 — Grain, agrégation, modélisation

**Q44. Pourquoi le grain dossier dans les visuels et pas sinistre × garantie ?**
Parce que l'unité de travail et de décision est le dossier. Le grain fin (367 464 lignes) sert le calcul et
l'audit ; le grain dossier (221 574) sert le pilotage. Règle écrite : jamais les deux grains dans un même
visuel — la seule page au grain fin est la page masquée.

**Q45. Pourquoi MAX pour agréger les garanties d'un dossier ?**
Un dossier vaut sa garantie la plus préoccupante. SUM créerait un bonus mécanique multi-garanties (biais
structurel), AVG diluerait un signal fort parmi des garanties saines. MAX est borné, monotone, explicable
en une phrase — décision tracée en ADR et testée.

**Q46. Pourquoi exclure client_sk = 0 des cohortes clients ?**
Ce sont les clients non identifiés (effet migration 2019) : les inclure fabriquerait un « client » géant
fictif qui écraserait tous les Pareto. On les exclut ET on affiche leur taux (0,004 %) en KPI — le périmètre
est documenté, pas caché.

**Q47. Pourquoi le rapport lit-il des vues et jamais les tables mart/dwh ?**
Contrat d'interface : les vues powerbi_v sont le seul point de contact, en lecture seule. On peut refactorer
le mart sans casser le rapport, la sécurité se gère sur un schéma unique, et la logique de grain/version est
implémentée une fois, en SQL, testée — pas dupliquée dans chaque visuel.

---

## Thème 9 — Aide à la décision et déontologie

**Q48. Votre dashboard peut-il accuser quelqu'un de fraude ?**
Non, par construction : aucun visuel ne mentionne le mot fraude, les libellés viennent des tables mart
(testés non accusatoires), le bandeau « Aide à l'analyse — la décision finale reste sous la responsabilité
du gestionnaire » est permanent, et Power BI n'a aucun bouton d'action. Le système suggère une attention,
l'humain décide.

**Q49. Comment garantissez-vous que le dashboard et l'application racontent les mêmes chiffres ?**
Même source (mart), même version de score verrouillée aux deux extrémités (backend/config.py et
v_score_version_config — alignées), même règle d'agrégation dossier (implémentée en SQL, testée). L'espace
analytique de l'application affiche d'ailleurs la gouvernance en direct : versions, runs, volumétries.

**Q50. Si le jury vous demande LA décision BI dont vous êtes la plus fière ?**
Le niveau de confiance affiché par dossier. C'est contre-intuitif commercialement (on montre ses faiblesses)
mais c'est ce qui rend tout le reste crédible : 80,2 % de confiance haute est un chiffre qu'on peut défendre
devant un auditeur, parce que les 19,8 % restants sont mesurés, expliqués et visibles — pas cachés.

---

## Bonus — les 5 pièges classiques à l'oral

1. **« Pourquoi 70 / 75 / 25 ? »** → jamais « ça semblait bien » ; toujours : calibrage sur distribution réelle
   + objectif de charge de travail + statut candidat en attente de validation BNA.
2. **« Votre ML détecte la fraude ? »** → non : il détecte l'*atypicité statistique*, signal parallèle calibré
   en percentile, jamais une probabilité de fraude ni une décision.
3. **« Pourquoi pas plus de visuels/pages ? »** → la profondeur vient des interactions, pas de l'accumulation ;
   une page = une question réelle.
4. **« Et si les données sont fausses ? »** → c'est prévu : audit bloquant au chargement, niveau de confiance
   par dossier, page P5 dédiée, KPI de périmètre (client inconnu, migration 2019).
5. **« Qu'est-ce qui empêche de modifier une décision a posteriori ? »** → un trigger PostgreSQL rejette
   physiquement UPDATE/DELETE ; les corrections sont de nouvelles lignes liées — démontrable en live.
