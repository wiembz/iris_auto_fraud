import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';
import { AuthService } from '../../../core/auth/auth.service';
import { ClaimListItem, IrisApiService, SummaryResponse } from '../../../core/services/iris-api.service';
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
}

interface CapabilityTile {
  title: string;
  text: string;
  status: 'available' | 'waiting-data';
  label: string;
}

interface DashboardPanel {
  title: string;
  metric: number | string;
  helper: string;
  status: 'available' | 'waiting-data';
  label: string;
}

interface TimelinePoint {
  label: string;
  value: number | string;
  helper: string;
  status: 'available' | 'waiting-data';
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
    RecentClaimsComponent
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
  readonly attentionRows = signal<AttentionChartRow[]>([]);
  readonly confidenceRows = signal<AttentionChartRow[]>([]);
  readonly managerKpis = signal<DashboardKpi[]>([]);
  readonly handlerKpis = signal<DashboardKpi[]>([]);
  readonly workloadRows = signal<WorkloadRow[]>([]);
  readonly governanceRows = signal<WorkloadRow[]>([]);
  readonly managerReadinessPanels = signal<DashboardPanel[]>([]);
  readonly handlerReadinessPanels = signal<DashboardPanel[]>([]);
  readonly signalFamilyRows = signal<WorkloadRow[]>([]);
  readonly trendPoints = signal<TimelinePoint[]>([]);
  readonly topClaims = signal<ClaimListItem[]>([]);
  readonly capabilityTiles = signal<CapabilityTile[]>([]);
  readonly heatmapCells = Array.from({ length: 12 }, (_, index) => index);

  readonly user = this.auth.currentUser;
  readonly isHandlerDashboard = computed(() => this.user()?.role === 'gestionnaire');
  readonly dashboardTitle = computed(() =>
    this.isHandlerDashboard() ? 'Tableau de bord gestionnaire' : 'Tableau de bord pilotage'
  );
  readonly dashboardSubtitle = computed(() =>
    this.isHandlerDashboard()
      ? 'Espace de revue pret pour les tests humains : priorites, raisons, confiance et actions de consultation.'
      : 'Cockpit de pilotage pret pour les tests humains : volumes, niveaux, qualite, signaux et besoins backend visibles.'
  );

  ngOnInit(): void {
    this.subscription = this.api.getSummary(DEFAULT_SCORE_VERSION).subscribe({
      next: (summary) => this.applySummary(summary),
      error: () => {
        this.errorMessage.set('Le resume IRIS est indisponible. Verifiez que l API Flask read-only est demarree.');
        this.loading.set(false);
      }
    });
  }

  ngOnDestroy(): void {
    this.subscription?.unsubscribe();
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
      label: item.confidence_level,
      count: item.claims,
      share: (item.claims / confidenceTotal) * 100,
      tone: this.confidenceTone(item.confidence_level)
    }));

    const priorityCount = this.countByTone(attentionRows, 'high');
    const reinforcedCount = this.countByTone(attentionRows, 'medium');
    const reviewCount = priorityCount + reinforcedCount + this.countByTone(attentionRows, 'low');
    const highConfidenceShare = Math.round(confidenceRows.find((row) => row.tone === 'ok')?.share ?? 0);
    const topClaims = summary.top_claims.slice(0, 8);
    const mlCount = topClaims.filter((claim) => claim.has_ml_signal).length;
    const postInspectionCount = topClaims.filter((claim) => claim.has_post_inspection_signal).length;
    const reasonCounts = this.buildReasonRows(topClaims);

    this.managerKpis.set([
      {
        label: 'Dossiers analyses',
        value: summary.total_claims,
        helper: 'volume couvert par le run affiche',
        tone: 'primary'
      },
      {
        label: 'Attention prioritaire',
        value: priorityCount,
        helper: 'dossiers au niveau le plus fort',
        tone: 'high'
      },
      {
        label: 'Revue renforcee',
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

    this.handlerKpis.set([
      {
        label: 'Dossiers a examiner',
        value: reviewCount,
        helper: 'prioritaires, renforces ou a verifier',
        tone: 'high'
      },
      {
        label: 'Acces rapide',
        value: topClaims.length,
        helper: 'dossiers visibles dans la liste prioritaire',
        tone: 'primary'
      },
      {
        label: 'Pieces en attente',
        value: 'Pret UI',
        helper: 'donnees backend pieces/documents attendues',
        tone: 'muted',
        status: 'pending'
      },
      {
        label: 'Echeances proches',
        value: 'Pret UI',
        helper: 'dates de traitement metier attendues',
        tone: 'muted',
        status: 'pending'
      }
    ]);

    const maxAttention = Math.max(...attentionRows.map((row) => row.count), 1);
    this.workloadRows.set([
      ...attentionRows.slice(0, 4).map((row) => ({
        label: row.label,
        value: row.count,
        share: (row.count / maxAttention) * 100,
        helper: 'charge de revue par niveau',
        status: 'available' as const
      })),
      {
        label: 'Validations a completer',
        value: 'Pret UI',
        share: 0,
        helper: 'module feedback metier attendu',
        status: 'pending'
      }
    ]);

    this.governanceRows.set([
      {
        label: 'Signal ML disponible dans la liste prioritaire',
        value: mlCount,
        share: topClaims.length ? (mlCount / topClaims.length) * 100 : 0,
        helper: 'signal complementaire, separe du jugement metier',
        status: 'available'
      },
      {
        label: 'Signal post-inspection disponible',
        value: postInspectionCount,
        share: topClaims.length ? (postInspectionCount / topClaims.length) * 100 : 0,
        helper: 'contexte temporel a consulter si present',
        status: 'available'
      },
      {
        label: 'Montants et agences',
        value: 'Pret UI',
        share: 0,
        helper: 'endpoint de pilotage dedie attendu',
        status: 'pending'
      },
      {
        label: 'Tendance temporelle',
        value: 'Pret UI',
        share: 0,
        helper: 'endpoint temporel attendu apres validation du grain dossier',
        status: 'pending'
      }
    ]);

    this.signalFamilyRows.set(
      reasonCounts.length
        ? reasonCounts
        : [
            {
              label: 'Distribution des familles de signaux',
              value: 'Pret UI',
              share: 0,
              helper: 'endpoint agrege des familles attendu',
              status: 'pending'
            }
          ]
    );

    this.handlerReadinessPanels.set([
      {
        title: 'File de travail',
        metric: topClaims.length,
        helper: 'dossiers accessibles depuis le resume courant',
        status: 'available',
        label: 'Disponible'
      },
      {
        title: 'Pieces et documents',
        metric: 'Pret UI',
        helper: 'liste de pieces attendues, sans ecriture depuis Angular',
        status: 'waiting-data',
        label: 'Donnees attendues'
      },
      {
        title: 'Echeances',
        metric: 'Pret UI',
        helper: 'priorisation calendaire a brancher sur le backend',
        status: 'waiting-data',
        label: 'Donnees attendues'
      }
    ]);

    this.managerReadinessPanels.set([
      {
        title: 'Volumes et niveaux',
        metric: summary.total_claims,
        helper: 'branche sur le resume read-only',
        status: 'available',
        label: 'Disponible'
      },
      {
        title: 'Charge par equipe',
        metric: 'Pret UI',
        helper: 'necessite un endpoint affectations/equipes',
        status: 'waiting-data',
        label: 'Donnees attendues'
      },
      {
        title: 'Agences et regions',
        metric: 'Pret UI',
        helper: 'a afficher apres consolidation GEO et endpoint agrege',
        status: 'waiting-data',
        label: 'Donnees attendues'
      },
      {
        title: 'Tendance temporelle',
        metric: 'Pret UI',
        helper: 'courbe prete, serie temporelle attendue',
        status: 'waiting-data',
        label: 'Donnees attendues'
      }
    ]);

    this.trendPoints.set([
      {
        label: '7 jours',
        value: 'Pret UI',
        helper: 'serie backend attendue',
        status: 'waiting-data'
      },
      {
        label: '30 jours',
        value: 'Pret UI',
        helper: 'serie backend attendue',
        status: 'waiting-data'
      },
      {
        label: '90 jours',
        value: 'Pret UI',
        helper: 'serie backend attendue',
        status: 'waiting-data'
      }
    ]);

    this.capabilityTiles.set([
      {
        title: 'Heatmap agence / periode',
        text: 'Structure visuelle prete pour afficher une matrice agence-periode lorsque l endpoint sera disponible.',
        status: 'waiting-data',
        label: 'Donnees attendues'
      },
      {
        title: 'Carte GEO',
        text: 'A afficher seulement lorsque le lot GEO est valide comme suffisamment fiable.',
        status: 'waiting-data',
        label: 'Decision GEO attendue'
      },
      {
        title: 'Radar multi-dimensions',
        text: 'Reserve aux comparaisons coherentes entre dimensions metier validees, sans usage decoratif.',
        status: 'waiting-data',
        label: 'Cadrage attendu'
      }
    ]);

    this.attentionRows.set(attentionRows);
    this.confidenceRows.set(confidenceRows);
    this.topClaims.set(topClaims);
    this.summary.set(summary);
    this.errorMessage.set(null);
    this.loading.set(false);
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

  private normalize(value: string): string {
    return value
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '');
  }
}
