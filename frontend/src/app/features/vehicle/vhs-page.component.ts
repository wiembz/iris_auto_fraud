import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { Subject, Subscription, debounceTime } from 'rxjs';
import {
  IrisApiService,
  VhsDecision,
  VhsInspectionDetail,
  VhsOverviewResponse,
  VhsPenaltyItem,
  VhsVehicleItem
} from '../../core/services/iris-api.service';

type ScoreTone = 'ok' | 'low' | 'medium' | 'high';

interface DecisionChip {
  value: string;
  label: string;
  count: number | null;
  averageScore: number | null;
  tone: ScoreTone | 'muted';
  active: boolean;
}

interface ZoneBar {
  zone: string;
  label: string;
  totalPenalty: number;
  criticalCount: number;
  sharePct: number;
}

interface ScoreBandBar {
  label: string;
  vehicles: number;
  sharePct: number;
  tone: ScoreTone;
}

interface PenaltyZoneGroup {
  zone: string;
  label: string;
  totalPenalty: number;
  penalties: VhsPenaltyItem[];
}

const DECISION_LABELS: Record<VhsDecision, string> = {
  OK: 'Bon etat',
  DEGRADE: 'Etat degrade',
  CRITIQUE: 'Etat critique',
  IMMOBILISE: 'Immobilise'
};

const DECISION_TONES: Record<VhsDecision, ScoreTone> = {
  OK: 'ok',
  DEGRADE: 'medium',
  CRITIQUE: 'high',
  IMMOBILISE: 'high'
};

const ZONE_LABELS: Record<string, string> = {
  TOUR_DU_VEHICULE: 'Tour du vehicule',
  SOUS_CAPOT: 'Sous le capot',
  SOUS_VEHICULE: 'Sous le vehicule',
  INTERIEUR: 'Interieur',
  ENTRETIEN: 'Entretien',
  NO_DOCUMENTED_ANOMALY: 'Sans anomalie documentee'
};

const STATUS_LABELS: Record<string, string> = {
  OK: 'Bon etat',
  WORN: 'Use',
  WORN_STRONG: 'Fortement use',
  BROKEN: 'Defaillant',
  REPAIRED: 'Repare',
  UNKNOWN: 'Non evalue'
};

@Component({
  selector: 'app-vhs-page',
  standalone: true,
  templateUrl: './vhs-page.component.html',
  styleUrl: './vhs-page.component.scss'
})
export class VhsPageComponent implements OnInit, OnDestroy {
  private readonly api = inject(IrisApiService);
  private overviewSubscription?: Subscription;
  private vehiclesSubscription?: Subscription;
  private detailSubscription?: Subscription;
  private searchSubscription?: Subscription;
  private readonly searchInput$ = new Subject<string>();

  readonly loading = signal(true);
  readonly listLoading = signal(false);
  readonly errorMessage = signal<string | null>(null);
  readonly overview = signal<VhsOverviewResponse | null>(null);
  readonly vehicles = signal<VhsVehicleItem[]>([]);
  readonly decisionFilter = signal<string>('');
  readonly searchTerm = signal<string>('');

  readonly expandedSk = signal<number | null>(null);
  readonly detail = signal<VhsInspectionDetail | null>(null);
  readonly detailLoading = signal(false);

  readonly decisionChips = computed<DecisionChip[]>(() => {
    const overview = this.overview();
    const active = this.decisionFilter();
    const findDecision = (value: VhsDecision) =>
      overview?.decision_distribution.find((item) => item.decision === value);
    const chips: DecisionChip[] = [
      {
        value: '',
        label: 'Tous les vehicules',
        count: overview?.total_vehicles ?? null,
        averageScore: overview?.average_score ?? null,
        tone: 'muted',
        active: active === ''
      }
    ];
    (['OK', 'DEGRADE', 'CRITIQUE', 'IMMOBILISE'] as VhsDecision[]).forEach((decision) => {
      const item = findDecision(decision);
      chips.push({
        value: decision,
        label: DECISION_LABELS[decision],
        count: item?.vehicles ?? (overview ? 0 : null),
        averageScore: item?.average_score ?? null,
        tone: DECISION_TONES[decision],
        active: active === decision
      });
    });
    return chips;
  });

  readonly zoneBars = computed<ZoneBar[]>(() => {
    const zones = this.overview()?.zone_penalties ?? [];
    const max = Math.max(...zones.map((z) => z.total_penalty), 1);
    return zones.map((zone) => ({
      zone: zone.zone_controle,
      label: this.zoneLabel(zone.zone_controle),
      totalPenalty: zone.total_penalty,
      criticalCount: zone.critical_count,
      sharePct: Math.max(4, Math.round((zone.total_penalty / max) * 100))
    }));
  });

  readonly scoreBandBars = computed<ScoreBandBar[]>(() => {
    const bands = this.overview()?.score_bands ?? [];
    const byStart = new Map(bands.map((band) => [band.band_start, band.vehicles]));
    const max = Math.max(...bands.map((band) => band.vehicles), 1);
    return [0, 20, 40, 60, 80].map((start) => {
      const vehicles = byStart.get(start) ?? 0;
      const end = start === 80 ? 100 : start + 19;
      return {
        label: `${start}-${end}`,
        vehicles,
        sharePct: Math.max(3, Math.round((vehicles / max) * 100)),
        tone: this.scoreTone(start + 10)
      };
    });
  });

  // Le score est plancher a 0 des que les penalites cumulees depassent les
  // 100 points de l echelle : le total des penalites reste alors le seul
  // indicateur qui differencie un vehicule tres degrade d une epave.
  readonly detailTotalPenalty = computed(() => {
    const penalties = this.detail()?.penalties ?? [];
    return Math.round(penalties.reduce((sum, p) => sum + (Number(p.penalty_applied) || 0), 0) * 10) / 10;
  });

  readonly detailIsSaturated = computed(() => {
    const d = this.detail();
    return !!d && Number(d.vhs_final_score) === 0 && this.detailTotalPenalty() >= 100;
  });

  readonly detailZoneGroups = computed<PenaltyZoneGroup[]>(() => {
    const penalties = this.detail()?.penalties ?? [];
    const groups = new Map<string, PenaltyZoneGroup>();
    for (const penalty of penalties) {
      const zone = penalty.zone_controle ?? 'AUTRE';
      const group = groups.get(zone) ?? {
        zone,
        label: this.zoneLabel(zone),
        totalPenalty: 0,
        penalties: []
      };
      group.penalties.push(penalty);
      group.totalPenalty += Number(penalty.penalty_applied) || 0;
      groups.set(zone, group);
    }
    return [...groups.values()].sort((a, b) => b.totalPenalty - a.totalPenalty);
  });

  ngOnInit(): void {
    this.overviewSubscription = this.api.getVhsOverview().subscribe({
      next: (overview) => {
        this.overview.set(overview);
        this.loading.set(false);
      },
      error: () => {
        this.errorMessage.set('La sante des vehicules est momentanement indisponible. Reessayez dans quelques instants.');
        this.loading.set(false);
      }
    });
    this.loadVehicles();
    this.searchSubscription = this.searchInput$.pipe(debounceTime(400)).subscribe((term) => {
      this.searchTerm.set(term);
      this.loadVehicles();
    });
  }

  ngOnDestroy(): void {
    this.overviewSubscription?.unsubscribe();
    this.vehiclesSubscription?.unsubscribe();
    this.detailSubscription?.unsubscribe();
    this.searchSubscription?.unsubscribe();
  }

  applyDecisionFilter(value: string): void {
    this.decisionFilter.set(value);
    this.loadVehicles();
  }

  private loadVehicles(): void {
    this.vehiclesSubscription?.unsubscribe();
    this.listLoading.set(true);
    this.expandedSk.set(null);
    this.detail.set(null);
    this.vehiclesSubscription = this.api
      .getVhsVehicles(this.decisionFilter() || undefined, this.searchTerm() || undefined)
      .subscribe({
        next: (res) => {
          this.vehicles.set(res.items);
          this.listLoading.set(false);
        },
        error: () => {
          this.vehicles.set([]);
          this.listLoading.set(false);
        }
      });
  }

  onSearchInput(event: Event): void {
    this.searchInput$.next((event.target as HTMLInputElement).value.trim());
  }

  toggleDetail(vehicle: VhsVehicleItem): void {
    if (this.expandedSk() === vehicle.vhs_score_sk) {
      this.expandedSk.set(null);
      this.detail.set(null);
      return;
    }
    this.expandedSk.set(vehicle.vhs_score_sk);
    this.detail.set(null);
    this.detailLoading.set(true);
    this.detailSubscription?.unsubscribe();
    this.detailSubscription = this.api.getVhsInspectionDetail(vehicle.vhs_score_sk).subscribe({
      next: (detail) => {
        this.detail.set(detail);
        this.detailLoading.set(false);
      },
      error: () => {
        this.detailLoading.set(false);
      }
    });
  }

  scoreTone(score: number | null | undefined): ScoreTone {
    const value = Number(score ?? 0);
    if (value >= 80) {
      return 'ok';
    }
    if (value >= 60) {
      return 'low';
    }
    if (value >= 40) {
      return 'medium';
    }
    return 'high';
  }

  gaugeOffset(score: number | null | undefined): number {
    const circumference = 2 * Math.PI * 54 * 0.75;
    const clamped = Math.max(0, Math.min(100, Number(score ?? 0)));
    return circumference * (1 - clamped / 100);
  }

  decisionLabel(decision: VhsDecision): string {
    return DECISION_LABELS[decision] ?? decision;
  }

  decisionTone(decision: VhsDecision): ScoreTone {
    return DECISION_TONES[decision] ?? 'medium';
  }

  zoneLabel(zone: string | null | undefined): string {
    if (!zone) {
      return 'Autre';
    }
    return ZONE_LABELS[zone] ?? zone.toLowerCase().replace(/_/g, ' ');
  }

  statusLabel(status: string | null | undefined): string {
    if (!status) {
      return '—';
    }
    return STATUS_LABELS[status] ?? status;
  }

  inspectionDate(dateSk: number | null | undefined): string {
    if (!dateSk || dateSk <= 0) {
      return '—';
    }
    const raw = String(dateSk);
    return `${raw.slice(6, 8)}/${raw.slice(4, 6)}/${raw.slice(0, 4)}`;
  }

  formatKm(km: number | null | undefined): string {
    if (km === null || km === undefined || !Number.isFinite(Number(km))) {
      return '—';
    }
    return `${Math.round(Number(km)).toLocaleString('fr-FR')} km`;
  }

  roundScore(score: number | null | undefined): number {
    return Math.round(Number(score ?? 0));
  }
}
