import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Subscription, forkJoin } from 'rxjs';
import { AuthService } from '../../../core/auth/auth.service';
import {
  ClaimListItem,
  IrisApiService,
  PortfolioInsightsResponse,
  SummaryResponse
} from '../../../core/services/iris-api.service';
import { AttentionChartComponent, AttentionChartRow, AttentionTone } from '../components/attention-chart/attention-chart.component';
import { KpiCardComponent } from '../components/kpi-card/kpi-card.component';
import { RecentClaimsComponent } from '../components/recent-claims/recent-claims.component';
import { TrendChartComponent, TrendPoint } from '../components/trend-chart/trend-chart.component';
import { WorkloadChartComponent, WorkloadRow } from '../components/workload-chart/workload-chart.component';

interface DashboardKpi {
  label: string;
  value: number | string;
  suffix?: string;
  helper: string;
  tone: 'primary' | 'high' | 'medium' | 'low' | 'ok' | 'muted';
  status?: 'available' | 'pending';
}

const DEFAULT_SCORE_VERSION = 'IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE';

@Component({
  selector: 'app-dashboard-page',
  standalone: true,
  imports: [
    RouterLink,
    KpiCardComponent,
    AttentionChartComponent,
    WorkloadChartComponent,
    RecentClaimsComponent,
    TrendChartComponent
  ],
  templateUrl: './dashboard-page.component.html',
  styleUrl: './dashboard-page.component.scss'
})
export class DashboardPageComponent implements OnInit, OnDestroy {
  private readonly api = inject(IrisApiService);
  private readonly auth = inject(AuthService);
  private subscription?: Subscription;

  readonly loading = signal(true);
  readonly errorMessage = signal<string | null>(null);
  readonly summary = signal<SummaryResponse | null>(null);
  readonly insights = signal<PortfolioInsightsResponse | null>(null);
  readonly attentionRows = signal<AttentionChartRow[]>([]);
  readonly confidenceRows = signal<AttentionChartRow[]>([]);
  readonly managerKpis = signal<DashboardKpi[]>([]);
  readonly handlerKpis = signal<DashboardKpi[]>([]);
  readonly workloadRows = signal<WorkloadRow[]>([]);
  readonly financialExposureRows = signal<WorkloadRow[]>([]);
  readonly guaranteeRows = signal<WorkloadRow[]>([]);
  readonly reasonRows = signal<WorkloadRow[]>([]);
  readonly validationRows = signal<WorkloadRow[]>([]);
  readonly trendPoints = signal<TrendPoint[]>([]);
  readonly signalFamilyRows = signal<WorkloadRow[]>([]);
  readonly topClaims = signal<ClaimListItem[]>([]);

  readonly user = this.auth.currentUser;
  readonly isHandlerDashboard = computed(() => this.user()?.role === 'gestionnaire');
  readonly dashboardTitle = computed(() =>
    this.isHandlerDashboard() ? 'Tableau de bord gestionnaire' : 'Tableau de bord pilotage'
  );
  readonly dashboardSubtitle = computed(() =>
    this.isHandlerDashboard()
      ? 'Vos priorites du jour : les dossiers a examiner, les raisons en clair et la confiance associee.'
      : 'Volumes, exposition financiere, tendance et avancement de la revue humaine sur l ensemble du portefeuille.'
  );

  ngOnInit(): void {
    if (this.isHandlerDashboard()) {
      this.subscription = this.api.getSummary(DEFAULT_SCORE_VERSION).subscribe({
        next: (summary) => this.applySummary(summary),
        error: () => this.onLoadError()
      });
      return;
    }

    this.subscription = forkJoin({
      summary: this.api.getSummary(DEFAULT_SCORE_VERSION),
      insights: this.api.getPortfolioInsights(DEFAULT_SCORE_VERSION)
    }).subscribe({
      next: ({ summary, insights }) => {
        this.applySummary(summary);
        this.applyInsights(insights);
      },
      error: () => this.onLoadError()
    });
  }

  ngOnDestroy(): void {
    this.subscription?.unsubscribe();
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
        tone: 'high'
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
    this.confidenceRows.set(confidenceRows);
    this.topClaims.set(topClaims);
    this.summary.set(summary);
    this.errorMessage.set(null);
    this.loading.set(false);
  }

  private applyInsights(insights: PortfolioInsightsResponse): void {
    this.insights.set(insights);

    const totalExposure = insights.financial_exposure.reduce((sum, item) => sum + item.total_amount, 0);
    const priorityExposure =
      insights.financial_exposure.find((item) => this.toneFor(item.attention_level) === 'high')?.total_amount ?? 0;
    const priorityClaims =
      insights.financial_exposure.find((item) => this.toneFor(item.attention_level) === 'high')?.claims ?? 0;
    const coverage = insights.validation_coverage;
    const coverageShare = coverage && coverage.total_claims
      ? Math.round((coverage.decided_claims / coverage.total_claims) * 100)
      : 0;

    this.managerKpis.set([
      {
        label: 'Dossiers analyses',
        value: coverage?.total_claims ?? 0,
        helper: 'volume couvert par la derniere analyse',
        tone: 'primary'
      },
      {
        label: 'Exposition financiere totale',
        value: this.formatAmountShort(totalExposure),
        helper: 'montant cumule des dossiers analyses',
        tone: 'primary'
      },
      {
        label: 'Examen prioritaire',
        value: priorityClaims,
        helper: `${this.formatAmountShort(priorityExposure)} en jeu sur ces dossiers`,
        tone: 'high'
      },
      {
        label: 'Couverture de la revue',
        value: coverageShare,
        suffix: '%',
        helper: `${coverage?.decided_claims ?? 0} dossier(s) avec une decision humaine enregistree`,
        tone: coverageShare > 0 ? 'ok' : 'muted',
        status: coverageShare > 0 ? 'available' : 'pending'
      }
    ]);

    const maxExposure = Math.max(...insights.financial_exposure.map((i) => i.total_amount), 1);
    this.financialExposureRows.set(
      insights.financial_exposure.map((item) => ({
        label: item.attention_level,
        value: this.formatAmountShort(item.total_amount),
        share: (item.total_amount / maxExposure) * 100,
        helper: `${item.claims.toLocaleString('fr-FR')} dossier(s) - moyenne ${this.formatAmountShort(item.avg_amount)}`,
        status: 'available' as const
      }))
    );

    const maxGuaranteeClaims = Math.max(...insights.guarantee_breakdown.map((i) => i.priority_claims), 1);
    this.guaranteeRows.set(
      insights.guarantee_breakdown.map((item) => ({
        label: item.code_garantie,
        value: item.priority_claims,
        share: (item.priority_claims / maxGuaranteeClaims) * 100,
        helper: `${item.claims.toLocaleString('fr-FR')} dossiers - ${this.formatAmountShort(item.total_amount)} au total`,
        status: 'available' as const
      }))
    );

    const maxReason = Math.max(...insights.reason_distribution.map((i) => i.claims), 1);
    this.reasonRows.set(
      insights.reason_distribution.map((item) => ({
        label: item.reason,
        value: item.claims,
        share: (item.claims / maxReason) * 100,
        helper: 'sur l ensemble du portefeuille analyse',
        status: 'available' as const
      }))
    );

    if (coverage) {
      const nonReviewed = Math.max(coverage.total_claims - coverage.decided_claims, 0);
      const maxValidation = Math.max(
        coverage.suspicion_confirmed,
        coverage.conforme,
        coverage.a_completer,
        nonReviewed,
        1
      );
      this.validationRows.set([
        {
          label: 'Suspicion confirmee',
          value: coverage.suspicion_confirmed,
          share: (coverage.suspicion_confirmed / maxValidation) * 100,
          helper: 'necessite une investigation ou un refus documente',
          status: 'available'
        },
        {
          label: 'Conforme',
          value: coverage.conforme,
          share: (coverage.conforme / maxValidation) * 100,
          helper: 'aucune anomalie retenue apres verification',
          status: 'available'
        },
        {
          label: 'A completer',
          value: coverage.a_completer,
          share: (coverage.a_completer / maxValidation) * 100,
          helper: 'elements manquants pour trancher',
          status: 'available'
        },
        {
          label: 'Non revu',
          value: nonReviewed,
          share: (nonReviewed / maxValidation) * 100,
          helper: 'en attente d une decision humaine',
          status: nonReviewed > 0 ? 'pending' : 'available'
        }
      ]);
    }

    this.trendPoints.set(
      insights.monthly_trend.map((point) => ({
        month: point.month,
        claims: point.claims,
        priorityClaims: point.priority_claims
      }))
    );
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

  private normalize(value: string): string {
    return value
      .toLowerCase()
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '');
  }
}
