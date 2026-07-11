import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';

@Component({
  selector: 'app-landing-page',
  imports: [CommonModule, RouterLink],
  templateUrl: './landing-page.component.html',
  styleUrl: './landing-page.component.scss'
})
export class LandingPageComponent {
  readonly businessIssues = [
    {
      title: 'Donnees dispersees',
      text: 'Les informations utiles au dossier sont souvent reparties entre plusieurs vues et historiques.'
    },
    {
      title: 'Priorisation manuelle',
      text: 'Les equipes doivent identifier rapidement les dossiers qui meritent une verification complementaire.'
    },
    {
      title: 'Explications a formaliser',
      text: 'Les raisons d attention doivent etre lisibles, tracables et partageables avec les equipes metier.'
    }
  ];

  readonly capabilities = [
    'Centralisation du dossier',
    'Priorisation explicable',
    'Historique client et vehicule',
    'Contexte VHS',
    'Comparaison dossiers similaires',
    'Checklist intelligente',
    'Tracabilite humaine'
  ];

  readonly steps = [
    { title: 'Rassembler', text: 'Regrouper les donnees utiles au dossier sinistre automobile.' },
    { title: 'Analyser', text: 'Evaluer les signaux disponibles sans produire de conclusion automatique.' },
    { title: 'Expliquer', text: 'Restituer les raisons principales en langage metier clair.' },
    { title: 'Accompagner', text: 'Aider le gestionnaire a preparer sa verification et sa decision.' }
  ];

  readonly modules = [
    { title: 'Claim Attention', text: 'Priorisation explicable des dossiers a examiner.' },
    { title: 'Vehicle Health Score', text: 'Contexte technique vehicule issu des controles disponibles.' },
    { title: 'Post-inspection', text: 'Lecture temporelle entre inspection, sinistre et contexte vehicule.' },
    { title: 'Atypicite statistique', text: 'Signal candidat separe, exprime en percentile et non en preuve.' },
    { title: 'Qualite des donnees', text: 'Affichage des limites, champs manquants et niveaux de confiance.' },
    { title: 'Pilotage', text: 'Synthese globale conservee pour le reporting et la revue metier.' }
  ];

  readonly principles = [
    'Explicabilite',
    'Tracabilite',
    'Decision humaine'
  ];
}
