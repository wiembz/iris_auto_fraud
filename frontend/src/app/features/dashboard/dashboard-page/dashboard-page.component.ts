import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';
import { AuthService } from '../../../core/auth/auth.service';
import {
  ClaimDecisionRecord,
  ClaimDecisionValue,
  ClaimListItem,
  IrisApiService,
  SummaryResponse
} from '../../../core/services/iris-api.service';
import { AttentionChartComponent, AttentionChartRow, AttentionTone } from '../components/attention-chart/attention-chart.component';
import { KpiCardComponent } from '../components/kpi-card/kpi-card.component';
import { RecentClaimsComponent } from '../components/recent-claims/recent-claims.component';
import { WorkloadChartComponent, WorkloadRow } from '../components/workload-chart/workload-chart.component';

interface DashboardKpi {
  label: string;
  value: number | string;
  suffix?: string;
  helper: string;
  tone: 'primary' | 'high' | 'medium' | 'low' | 'ok' | 'muted';
  status?: 'available' | 'pending';
  // Une carte sans action n est qu un chiffre mort : chaque KPI du cockpit
  // ouvre la file de travail deja filtree sur ce qu il represente.
  link?: string;
  queryParams?: Record<string, string>;
  lead?: boolean;
}

const DEFAULT_SCORE_VERSION = 'IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE';

@Component({
  selector: 'app-dashboard-page',
  standalone: true,
  imports: [
    RouterLink,
    DatePipe,
    KpiCardComponent,
    AttentionChartComponent,
    WorkloadChartComponent,
    RecentClaimsComponent
  ],
  templateUrl: './dashboard-page.component.html',
  styleUrl: './dashboard-page.component.scss'
})
export class DashboardPageComponent implements OnInit, OnDestroy {
  private readonly api = inject(IrisApiService);
  private readonly auth = inject(AuthService);
  private readonly subscriptions = new Subscription();

  readonly loading = signal(true);
  readonly errorMessage = signal<string | null>(null);
  readonly summary = signal<SummaryResponse | null>(null);
  readonly attentionRows = signal<AttentionChartRow[]>([]);
  readonly managerKpis = signal<DashboardKpi[]>([]);
  readonly handlerKpis = signal<DashboardKpi[]>([]);
  readonly workloadRows = signal<WorkloadRow[]>([]);
  readonly signalFamilyRows = signal<WorkloadRow[]>([]);
  readonly topClaims = signal<ClaimListItem[]>([]);
  readonly recentDecisions = signal<ClaimDecisionRecord[]>([]);
  readonly priorityAlertCount = signal(0);
  readonly activityCollapsed = signal(false);

  toggleActivityCollapsed(): void {
    this.activityCollapsed.set(!this.activityCollapsed());
  }

  readonly user = this.auth.currentUser;
  readonly isHandlerDashboard = computed(() => this.user()?.role === 'analyste');
  readonly dashboardTitle = computed(() =>
    this.isHandlerDashboard() ? 'Tableau de bord analyste' : 'Tableau de bord pilotage'
  );
  readonly dashboardSubtitle = computed(() =>
    this.isHandlerDashboard()
      ? 'Vos priorites du jour : les dossiers a examiner, les raisons en clair et la confiance associee.'
      : 'Ce qui exige votre attention maintenant, ou se trouve le retard, et l activite de l equipe.'
  );

  ngOnInit(): void {
    this.subscriptions.add(
      this.api.getSummary(DEFAULT_SCORE_VERSION).subscribe({
        next: (summary) => this.applySummary(summary),
        error: () => this.onLoadError()
      })
    );

    if (!this.isHandlerDashboard()) {
      // getPortfolioInsights() est desactive cote frontend : la requete SQL
      // backend (get_portfolio_insights) est connue pour rester active des
      // heures sur ce jeu de donnees (bug non corrige). Un timeout RxJS cote
      // client n annule pas la requete cote serveur -- elle continue a tourner
      // et sature la base (observe plusieurs fois : bloque /vhs/vehicles).
      // Ne plus l appeler du tout est la seule mitigation fiable avant que la
      // requete elle-meme soit corrigee. La vue pilotage reutilise signalFamilyRows
      // (deja alimente par /summary pour les deux roles) a la place du graphique
      // de tendance qui dependait de cette requete.
      this.subscriptions.add(
        this.api.getDecisionsFeed(undefined, 8).subscribe({
          next: (decisions) => this.recentDecisions.set(decisions.items),
          error: () => this.recentDecisions.set([])
        })
      );
    }
  }

  ngOnDestroy(): void {
    this.subscriptions.unsubscribe();
  }

  private onLoadError(): void {
    this.errorMessage.set('Le resume IRIS est momentanement indisponible. Reessayez dans quelques instants.');
    this.loading.set(false);
  }

  private applySummary(summary: SummaryResponse): void {
    const total = Math.max(summary.total_claims, 1);
    const attentionRows = summary.attention_distribution.map((item) => ({
      label: item.attention_level,
      count: item.claims,
      share: (item.claims / total) * 100,
      tone: this.toneFor(item.attention_level)
    }));

    const confidenceTotal = Math.max(
      summary.confidence_distribution.reduce((sum, item) => sum + item.claims, 0),
      1
    );
    const confidenceRows = summary.confidence_distribution.map((item) => ({
      label: this.confidenceLabel(item.confidence_level),
      count: item.claims,
      share: (item.claims / confidenceTotal) * 100,
      tone: this.confidenceTone(item.confidence_level)
    }));

    const priorityCount = this.countByTone(attentionRows, 'high');
    const reinforcedCount = this.countByTone(attentionRows, 'medium');
    const reviewCount = priorityCount + reinforcedCount + this.countByTone(attentionRows, 'low');
    const highConfidenceShare = Math.round(confidenceRows.find((row) => row.tone === 'ok')?.share ?? 0);
    const topClaims = summary.top_claims.slice(0, 8);

    this.handlerKpis.set([
      {
        label: 'Dossiers a examiner',
        value: reviewCount,
        helper: 'prioritaires, renforces ou a verifier',
        tone: 'high'
      },
      {
        label: 'Examen prioritaire',
        value: priorityCount,
        helper: 'dossiers au niveau le plus fort',
        tone: 'high',
        lead: true
      },
      {
        label: 'Examen renforce',
        value: reinforcedCount,
        helper: 'dossiers a suivre de pres',
        tone: 'medium'
      },
      {
        label: 'Confiance elevee',
        value: highConfidenceShare,
        suffix: '%',
        helper: 'part des dossiers les mieux documentes',
        tone: 'ok'
      }
    ]);

    const maxAttention = Math.max(...attentionRows.map((row) => row.count), 1);
    this.workloadRows.set(
      attentionRows.slice(0, 4).map((row) => ({
        label: row.label,
        value: row.count,
        share: (row.count / maxAttention) * 100,
        helper: 'charge de revue par niveau',
        status: 'available' as const
      }))
    );

    this.signalFamilyRows.set(
      this.buildReasonRows(topClaims).length
        ? this.buildReasonRows(topClaims)
        : [
            {
              label: 'Aucune raison a afficher pour le moment',
              value: 0,
              share: 0,
              helper: 'les raisons apparaissent des qu un dossier prioritaire est disponible',
              status: 'available'
            }
          ]
    );

    this.attentionRows.set(attentionRows);
    this.topClaims.set(topClaims);
    if (!this.isHandlerDashboard()) {
      this.updateManagerKpis();
    }
    this.summary.set(summary);
    this.errorMessage.set(null);
    this.loading.set(false);
  }

  private updateManagerKpis(): void {
    const priorityClaims = this.countByTone(this.attentionRows(), 'high');
    const reinforcedClaims = this.countByTone(this.attentionRows(), 'medium');
    const toVerifyClaims = this.countByTone(this.attentionRows(), 'low');
    const reviewCount = priorityClaims + reinforcedClaims + toVerifyClaims;

    // Cockpit volontairement limite a ces 4 cartes : "SLA depasse" et "En
    // attente de decision" affichaient ~367 463 (quasi tout le portefeuille)
    // car une seule decision a jamais ete enregistree sur 367 464 dossiers
    // dans ce jeu de donnees historique. Pas un bug de seuil. A reactiver
    // une fois l affectation reelle et un vrai flux de decision en place
    // (decision confirmee avec Wiem).
    this.managerKpis.set([
      {
        label: 'Signales',
        value: reviewCount,
        helper: 'prioritaires, renforces ou a verifier',
        tone: 'primary',
        link: '/app/claims',
        queryParams: { attentionLevel: '', sortBy: 'attention_score', sortDirection: 'desc' }
      },
      {
        label: 'Prioritaires',
        value: priorityClaims,
        helper: 'dossiers au niveau le plus fort',
        tone: 'high',
        link: '/app/claims',
        queryParams: { attentionLevel: 'Examen prioritaire suggere' },
        lead: true
      },
      {
        label: 'Renforces',
        value: reinforcedClaims,
        helper: 'dossiers a suivre de pres',
        tone: 'medium',
        link: '/app/claims',
        queryParams: { attentionLevel: 'Examen renforce suggere' }
      },
      {
        label: 'Points a verifier',
        value: toVerifyClaims,
        helper: 'signaux faibles a confirmer',
        tone: 'low',
        link: '/app/claims',
        queryParams: { attentionLevel: 'Points a verifier' }
      }
    ]);
    this.priorityAlertCount.set(priorityClaims);
  }

  private toneFor(level: string): AttentionTone {
    const normalized = this.normalize(level);
    if (normalized.includes('priorit')) {
      return 'high';
    }
    if (normalized.includes('renforc')) {
      return 'medium';
    }
    if (normalized.includes('verif')) {
      return 'low';
    }
    return 'ok';
  }

  private confidenceLabel(level: string): string {
    const normalized = this.normalize(level ?? '');
    if (normalized.includes('high') || normalized.includes('eleve')) {
      return 'Confiance elevee';
    }
    if (normalized.includes('medium') || normalized.includes('moy')) {
      return 'Confiance moyenne';
    }
    if (normalized.includes('low') || normalized.includes('limit')) {
      return 'Confiance limitee';
    }
    return level;
  }

  private confidenceTone(level: string): AttentionTone {
    const normalized = this.normalize(level);
    if (normalized.includes('eleve') || normalized.includes('high')) {
      return 'ok';
    }
    if (normalized.includes('moy') || normalized.includes('medium')) {
      return 'medium';
    }
    if (normalized.includes('limit') || normalized.includes('low')) {
      return 'low';
    }
    return 'muted';
  }

  private countByTone(rows: AttentionChartRow[], tone: AttentionTone): number {
    return rows.filter((row) => row.tone === tone).reduce((sum, row) => sum + row.count, 0);
  }

  private buildReasonRows(claims: ClaimListItem[]): WorkloadRow[] {
    const counts = new Map<string, number>();

    for (const claim of claims) {
      const reasons = [claim.main_reason_1, claim.main_reason_2, claim.main_reason_3].filter(Boolean) as string[];
      for (const reason of reasons) {
        counts.set(reason, (counts.get(reason) ?? 0) + 1);
      }
    }

    const max = Math.max(...counts.values(), 1);
    return [...counts.entries()]
      .sort((left, right) => right[1] - left[1])
      .slice(0, 6)
      .map(([label, count]) => ({
        label,
        value: count,
        share: (count / max) * 100,
        helper: 'raison observee dans les dossiers prioritaires affiches',
        status: 'available' as const
      }));
  }

  private formatAmountShort(value: number): string {
    if (!Number.isFinite(value)) {
      return '0 TND';
    }
    if (value >= 1_000_000) {
      return `${(value / 1_000_000).toLocaleString('fr-FR', { maximumFractionDigits: 1 })} M TND`;
    }
    if (value >= 1_000) {
      return `${(value / 1_000).toLocaleString('fr-FR', { maximumFractionDigits: 0 })} k TND`;
    }
    return `${Math.round(value).toLocaleString('fr-FR')} TND`;
  }

  decisionLabel(decision: ClaimDecisionValue): string {
    switch (decision) {
      case 'SUSPICION_CONFIRMED':
        return 'Fraude';
      case 'CONFORME':
        return 'Non fraude';
      case 'A_COMPLETER':
        return 'Incomplet';
      default:
        return decision;
    }
  }

  decisionTone(decision: ClaimDecisionValue): 'high' | 'ok' | 'medium' {
    if (decision === 'SUSPICION_CONFIRMED') {
      return 'high';
    }
    if (decision === 'CONFORME') {
      return 'ok';
    }
    return 'medium';
  }

  private normalize(value: string): string {
    return value
      .toLowerCase()
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '');
  }
}
