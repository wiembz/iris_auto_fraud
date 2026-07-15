# Interpretation academique du benchmark ML

## Decision pipeline

Les resultats ne changent pas la decision du pipeline ML. Ils confirment Isolation Forest comme modele candidat principal pour le signal d'atypicite statistique IRIS.

## Justification simple

- Isolation Forest couvre 381,893 dossiers dans le run de reference.
- Le top 5% Isolation Forest recouvre 31.8% des dossiers a attention metier elevee disponibles dans ce run.
- Le score est calibre en percentile, donc lisible pour un gestionnaire.
- Le modele est deja integre dans le mart ML candidat et gouverne par signal_run_id/signal_version.
- Local Outlier Factor, One-Class SVM et Robust Covariance apportent des points de comparaison utiles, mais restent exploratoires car ils ont ete evalues sur echantillon et presentent des contraintes operationnelles ou d'interpretation plus fortes.

## Limite academique importante

Sans labels humains confirmes, le benchmark ne prouve pas qu'un modele detecte une conclusion automatique. Il compare des signaux d'atypicite statistique et leur coherence avec les signaux metier IRIS.

## Formulation recommandee

Isolation Forest reste le modele candidat principal pour produire un signal d'atypicite statistique dans IRIS, car il offre le meilleur compromis observe entre couverture, integration operationnelle, calibration, explicabilite et alignement avec les signaux metier.
