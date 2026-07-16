import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { IrisApiService, PowerbiGovernanceComponent } from '../../core/services/iris-api.service';

/**
 * URL du rapport publie sur Power BI Report Server (on-premises).
 * Laisser vide tant que la publication n'est pas faite : la page affiche
 * alors l'etat "publication a venir" au lieu d'un lien mort.
 */
const REPORT_SERVER_URL = '';

interface ReportPage {
  code: string;
  title: string;
  question: string;
  audience: string;
  visuals: string[];
}

const COMPONENT_LABELS: Record<string, string> = {
  CLAIM_ATTENTION: 'Score d attention sinistres',
  ML_ANOMALY: 'Signal d atypicite ML',
  POST_INSPECTION: 'Signaux post-inspection',
  VHS: 'Sante vehicule (VHS)'
};

@Component({
  selector: 'app-analytics-page',
  standalone: true,
  templateUrl: './analytics-page.component.html',
  styleUrl: './analytics-page.component.scss'
})
export class AnalyticsPageComponent implements OnInit, OnDestroy {
  private readonly api = inject(IrisApiService);
  private governanceSubscription?: Subscription;

  readonly reportUrl = REPORT_SERVER_URL;
  readonly governance = signal<PowerbiGovernanceComponent[]>([]);
  readonly governanceLoading = signal(true);

  readonly reportPages: ReportPage[] = [
    {
      code: 'P1',
      title: 'Vue executive',
      question: 'Ou en est le portefeuille ?',
      audience: 'Management',
      visuals: ['Distribution du score 0-100', 'Niveaux d attention', 'Tendance mensuelle', 'Repartition par garantie']
    },
    {
      code: 'P2',
      title: 'Signaux & priorisation',
      question: 'Pourquoi et quels dossiers ?',
      audience: 'Analystes',
      visuals: ['Contribution par famille de regles', 'Taux d activation par regle', 'Score x montant', 'Convergence ML x metier']
    },
    {
      code: 'P3',
      title: 'Clients & recurrence',
      question: 'Qui concentre l activite ?',
      audience: 'Management, analystes',
      visuals: ['Distribution des sinistres par client', 'Pareto de concentration', 'Anciennete au sinistre', 'Mono vs multisinistres']
    },
    {
      code: 'P4',
      title: 'Vehicule & inspections',
      question: 'Que dit le contexte technique ?',
      audience: 'Analystes',
      visuals: ['Pareto des defauts constates', 'Systeme x gravite', 'Distribution du score VHS', 'Delais inspection vers sinistre']
    },
    {
      code: 'P5',
      title: 'Qualite & gouvernance',
      question: 'Peut-on se fier a ces chiffres ?',
      audience: 'Equipe data, jury',
      visuals: ['Niveaux de confiance par segment', 'Evaluabilite des familles', 'Version, run et catalogue de regles', 'Etat de validation des regles']
    }
  ];

  ngOnInit(): void {
    this.governanceSubscription = this.api.getPowerbiGovernance().subscribe({
      next: (res) => {
        this.governance.set(res.components);
        this.governanceLoading.set(false);
      },
      error: () => {
        this.governance.set([]);
        this.governanceLoading.set(false);
      }
    });
  }

  ngOnDestroy(): void {
    this.governanceSubscription?.unsubscribe();
  }

  componentLabel(component: string): string {
    return COMPONENT_LABELS[component] ?? component;
  }

  shortRun(runId: string): string {
    const match = runId.match(/(\d{8}_\d{6})$/);
    if (!match) {
      return runId;
    }
    const raw = match[1];
    return `${raw.slice(6, 8)}/${raw.slice(4, 6)}/${raw.slice(0, 4)}`;
  }

  formatRows(count: number): string {
    return Number(count ?? 0).toLocaleString('fr-FR');
  }
}
