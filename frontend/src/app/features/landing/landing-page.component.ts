import {
  AfterViewInit,
  Component,
  ElementRef,
  OnDestroy,
  ViewChild,
  signal
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { IrisLogoComponent } from '../../shared/ui/iris-logo.component';
import { LpRevealDirective } from './reveal.directive';
import { IrisEyeSceneComponent } from './sections/iris-eye-scene.component';

interface WorkflowStep {
  label: string;
  title: string;
  text: string;
  mock: 'login' | 'dashboard' | 'worklist' | 'review' | 'decision';
}

@Component({
  selector: 'app-landing-page',
  imports: [RouterLink, IrisEyeSceneComponent, IrisLogoComponent, LpRevealDirective],
  templateUrl: './landing-page.component.html',
  styleUrl: './landing-page.component.scss'
})
export class LandingPageComponent implements AfterViewInit, OnDestroy {
  @ViewChild('statsBand') private readonly statsBand?: ElementRef<HTMLElement>;

  /* ---- Hero ---- */
  readonly heroChips = [
    { title: 'Vision 360°', text: 'Tout le dossier réuni en un seul écran' },
    { title: 'Priorisation intelligente', text: 'Les dossiers clés remontent d’eux-mêmes' },
    { title: 'Décision humaine', text: 'Vos experts gardent toujours la main' }
  ];

  /* ---- Bandeau défilant ---- */
  readonly marqueeItems = [
    'Vision 360° du dossier',
    'Priorisation intelligente',
    'Signaux expliqués',
    'Historique client & véhicule',
    'Vehicle Health Score',
    'Checklist guidée',
    'Analyse comparative',
    'Traçabilité complète'
  ];

  /* ---- Pourquoi IRIS ---- */
  readonly valueCards = [
    {
      index: '01',
      title: 'Tout le dossier, en un regard',
      text: 'Client, contrat, véhicule, garanties, historique : IRIS réunit l’information dispersée en une vision unique et immédiate.'
    },
    {
      index: '02',
      title: 'Les priorités deviennent évidentes',
      text: 'Chaque dossier reçoit un niveau d’attention clair. Vos équipes savent instantanément où concentrer leur expertise.'
    },
    {
      index: '03',
      title: 'Des signaux qui s’expliquent',
      text: 'Pas de boîte noire : chaque alerte est accompagnée de ses raisons, exprimées en langage métier compréhensible.'
    },
    {
      index: '04',
      title: 'Du temps rendu à l’expertise',
      text: 'Moins de recherche manuelle, plus d’analyse à valeur ajoutée. La technologie travaille, vos experts décident.'
    }
  ];

  /* ---- Parcours ---- */
  readonly steps: WorkflowStep[] = [
    {
      label: 'Connexion',
      title: 'Un espace pensé pour chaque profil',
      text: 'Gestionnaire, superviseur, auditeur : chacun se connecte à un environnement adapté à son rôle et à ses responsabilités.',
      mock: 'login'
    },
    {
      label: 'Vue d’ensemble',
      title: 'L’essentiel révélé en un instant',
      text: 'Dès l’ouverture, le dashboard donne la mesure : volumes en cours, niveaux de priorité, tendances de l’activité.',
      mock: 'dashboard'
    },
    {
      label: 'Priorisation',
      title: 'Les dossiers clés remontent d’eux-mêmes',
      text: 'IRIS classe les dossiers selon leur niveau d’attention. L’effort se concentre là où il compte vraiment.',
      mock: 'worklist'
    },
    {
      label: 'Revue guidée',
      title: 'Analyser avec tout le contexte',
      text: 'Signaux expliqués, historique complet, checklist intelligente : tout est réuni pour une analyse sereine et rapide.',
      mock: 'review'
    },
    {
      label: 'Décision',
      title: 'Une décision humaine, documentée',
      text: 'La décision finale appartient à vos experts. Elle est motivée, enregistrée et traçable de bout en bout.',
      mock: 'decision'
    }
  ];

  /* ---- Modules ---- */
  readonly modules = [
    {
      code: 'Priorisation',
      tone: 'primary',
      title: 'Claim Attention',
      text: 'Chaque dossier reçoit un niveau d’attention accompagné de ses raisons. La file de travail s’ordonne d’elle-même.'
    },
    {
      code: 'Véhicule',
      tone: 'deep',
      title: 'Vehicle Health Score',
      text: 'L’état de santé du véhicule résumé en un score clair, construit à partir de son historique technique.'
    },
    {
      code: 'Comparaison',
      tone: 'aqua',
      title: 'Analyse comparative',
      text: 'Chaque dossier est mis en perspective avec des dossiers similaires pour révéler ce qui sort de l’ordinaire.'
    },
    {
      code: 'IA',
      tone: 'violet',
      title: 'Détection d’atypies',
      text: 'L’intelligence artificielle repère les configurations inhabituelles que l’œil humain ne peut pas voir seul.'
    },
    {
      code: 'Chronologie',
      tone: 'gold',
      title: 'Lecture temporelle',
      text: 'Inspection, sinistre, déclarations : les enchaînements dans le temps sont mis en lumière automatiquement.'
    },
    {
      code: 'Revue',
      tone: 'neutral',
      title: 'Checklist intelligente',
      text: 'Une revue guidée, adaptée au dossier, pour une analyse complète sans rien laisser au hasard.'
    }
  ];

  /* ---- Repères chiffrés ---- */
  readonly stats = [
    { target: 360, suffix: '°', label: 'de vision sur chaque dossier sinistre' },
    { target: 6, suffix: '', label: 'modules intelligents complémentaires' },
    { target: 4, suffix: '', label: 'profils métier, un espace dédié chacun' },
    { target: 100, suffix: '%', label: 'des décisions prises par vos experts' }
  ];

  /* ---- Confiance ---- */
  readonly pillars = [
    {
      title: 'Explicable',
      text: 'Chaque signal, chaque niveau d’attention vient avec ses raisons. Vos équipes comprennent toujours pourquoi.'
    },
    {
      title: 'Traçable',
      text: 'Chaque revue, chaque décision laisse une trace claire. L’activité est défendable à tout moment.'
    },
    {
      title: 'Maîtrisé',
      text: 'IRIS éclaire, recommande, accompagne — mais ne décide jamais à la place de vos experts.'
    }
  ];

  readonly activeStep = signal(0);
  readonly autoplay = signal(true);
  readonly statValues = signal<number[]>(this.stats.map(() => 0));

  private stepTimer?: ReturnType<typeof setInterval>;
  private statsObserver?: IntersectionObserver;
  private statsStarted = false;

  ngAfterViewInit(): void {
    this.startAutoplay();
    this.observeStats();
  }

  ngOnDestroy(): void {
    if (this.stepTimer) {
      clearInterval(this.stepTimer);
    }
    this.statsObserver?.disconnect();
  }

  selectStep(index: number): void {
    this.activeStep.set(index);
    this.autoplay.set(false);
    if (this.stepTimer) {
      clearInterval(this.stepTimer);
      this.stepTimer = undefined;
    }
  }

  private startAutoplay(): void {
    const reducedMotion =
      typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reducedMotion) {
      this.autoplay.set(false);
      return;
    }

    this.stepTimer = setInterval(() => {
      this.activeStep.set((this.activeStep() + 1) % this.steps.length);
    }, 4600);
  }

  private observeStats(): void {
    const host = this.statsBand?.nativeElement;
    if (!host || typeof IntersectionObserver === 'undefined') {
      this.statValues.set(this.stats.map((stat) => stat.target));
      return;
    }

    this.statsObserver = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting) && !this.statsStarted) {
          this.statsStarted = true;
          this.animateStats();
          this.statsObserver?.disconnect();
        }
      },
      { threshold: 0.3 }
    );

    this.statsObserver.observe(host);
  }

  private animateStats(): void {
    const duration = 1400;
    const start = performance.now();
    const easeOut = (t: number): number => 1 - Math.pow(1 - t, 3);

    const tick = (now: number): void => {
      const progress = Math.min((now - start) / duration, 1);
      this.statValues.set(this.stats.map((stat) => Math.round(stat.target * easeOut(progress))));
      if (progress < 1) {
        requestAnimationFrame(tick);
      }
    };

    requestAnimationFrame(tick);
  }

  /* Effet "spotlight" : le halo suit le curseur sur les cartes. */
  onSpotlightMove(event: MouseEvent): void {
    const card = event.currentTarget as HTMLElement;
    const rect = card.getBoundingClientRect();
    card.style.setProperty('--mx', `${event.clientX - rect.left}px`);
    card.style.setProperty('--my', `${event.clientY - rect.top}px`);
  }
}
