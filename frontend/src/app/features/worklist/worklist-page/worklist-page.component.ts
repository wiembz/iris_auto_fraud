import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { ClaimSummary, SortDirection, WorklistFilters } from '../../../core/models/claim-summary.model';
import { AttentionDistributionItem, ClaimListItem, IrisApiService } from '../../../core/services/iris-api.service';
import { ClaimTableComponent, WorklistSortChange } from '../claim-table/claim-table.component';
import { WorklistFiltersComponent } from '../worklist-filters/worklist-filters.component';

const DEFAULT_SCORE_VERSION = 'IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE';
const STORAGE_KEY = 'iris.worklist.filters.v1';

interface TriageChip {
  value: string;
  label: string;
  count: number | null;
  tone: 'high' | 'medium' | 'low' | 'ok' | 'muted';
  active: boolean;
}

@Component({
  selector: 'app-worklist-page',
  standalone: true,
  imports: [ClaimTableComponent, WorklistFiltersComponent],
  templateUrl: './worklist-page.component.html',
  styleUrl: './worklist-page.component.scss'
})
export class WorklistPageComponent implements OnInit, OnDestroy {
  private readonly api = inject(IrisApiService);
  private subscription?: Subscription;
  private summarySubscription?: Subscription;

  readonly loading = signal(true);
  readonly errorMessage = signal<string | null>(null);
  readonly claims = signal<ClaimSummary[]>([]);
  readonly total = signal(0);
  readonly scoreRunId = signal<string | null>(null);
  readonly hasNextPage = signal(false);
  readonly totalIsExact = signal(false);
  readonly filters = signal<WorklistFilters>(this.loadFilters());
  readonly attentionDistribution = signal<AttentionDistributionItem[]>([]);

  // Triage en un clic : les niveaux d attention avec leurs volumes reels,
  // directement branches sur le filtre Attention de la liste.
  readonly triageChips = computed<TriageChip[]>(() => {
    const distribution = this.attentionDistribution();
    const activeLevel = this.filters().attentionLevel ?? '';
    const countFor = (level: string): number | null => {
      if (!distribution.length) {
        return null;
      }
      return distribution.find((item) => item.attention_level === level)?.claims ?? 0;
    };
    const totalCount = distribution.length
      ? distribution.reduce((sum, item) => sum + item.claims, 0)
      : null;
    return [
      { value: '', label: 'Tous les dossiers', count: totalCount, tone: 'muted', active: activeLevel === '' },
      { value: 'Examen prioritaire suggere', label: 'Examen prioritaire', count: countFor('Examen prioritaire suggere'), tone: 'high', active: activeLevel === 'Examen prioritaire suggere' },
      { value: 'Examen renforce suggere', label: 'Examen renforce', count: countFor('Examen renforce suggere'), tone: 'medium', active: activeLevel === 'Examen renforce suggere' },
      { value: 'Points a verifier', label: 'Points a verifier', count: countFor('Points a verifier'), tone: 'low', active: activeLevel === 'Points a verifier' },
      { value: 'Analyse standard', label: 'Analyse standard', count: countFor('Analyse standard'), tone: 'ok', active: activeLevel === 'Analyse standard' }
    ];
  });

  ngOnInit(): void {
    this.loadClaims();
    this.summarySubscription = this.api.getSummary(DEFAULT_SCORE_VERSION).subscribe({
      next: (summary) => this.attentionDistribution.set(summary.attention_distribution),
      error: () => {
        // Non bloquant : les puces affichent '—' si le resume est indisponible.
      }
    });
  }

  ngOnDestroy(): void {
    this.subscription?.unsubscribe();
    this.summarySubscription?.unsubscribe();
  }

  applyTriage(level: string): void {
    this.updateFilters({ attentionLevel: level || undefined, page: 1 });
  }

  updateFilters(partial: Partial<WorklistFilters>): void {
    const next = { ...this.filters(), ...this.cleanFilterPatch(partial) };
    this.filters.set(next);
    this.persistFilters(next);
    this.loadClaims();
  }

  resetFilters(): void {
    const next = this.defaultFilters();
    this.filters.set(next);
    this.persistFilters(next);
    this.loadClaims();
  }

  updatePage(page: number): void {
    this.updateFilters({ page });
  }

  updateSort(change: WorklistSortChange): void {
    this.updateFilters({ ...change, page: 1 });
  }

  activeFilterCount(): number {
    const filters = this.filters();
    const values = [
      filters.search,
      filters.attentionLevel,
      filters.confidenceLevel,
      filters.validationStatus,
      filters.hasMl ? 'ml' : '',
      filters.hasPostInspection ? 'post' : ''
    ];
    return values.filter(Boolean).length;
  }

  private loadClaims(): void {
    this.subscription?.unsubscribe();
    this.loading.set(true);
    this.errorMessage.set(null);

    const filters = this.filters();
    this.subscription = this.api.getClaims(filters).subscribe({
      next: (response) => {
        this.claims.set(response.items.map((item) => this.toClaimSummary(item)));
        this.total.set(response.total);
        this.hasNextPage.set(Boolean(response.has_next));
        this.totalIsExact.set(Boolean(response.total_is_exact));
        this.scoreRunId.set(response.score_run_id);
        this.loading.set(false);
      },
      error: () => {
        this.claims.set([]);
        this.total.set(0);
        this.hasNextPage.set(false);
        this.totalIsExact.set(false);
        this.errorMessage.set('La file de travail est momentanement indisponible. Reessayez dans quelques instants.');
        this.loading.set(false);
      }
    });
  }

  private toClaimSummary(item: ClaimListItem): ClaimSummary {
    return {
      claim_sk: item.claim_sk,
      claim_root_id: item.claim_root_id || item.claim_business_id || `DOSSIER-${item.claim_sk}`,
      claim_business_id: item.claim_business_id,
      claim_date: item.claim_date ?? null,
      client_label: item.client_label ?? null,
      vehicle_label: item.vehicle_label ?? null,
      agency_label: item.agency_label ?? null,
      region_label: item.region_label ?? null,
      claim_amount: this.toNumberOrNull(item.claim_amount),
      attention_score: item.attention_score,
      attention_level: item.attention_level,
      attention_tone: this.attentionTone(item.attention_level),
      main_reason: item.main_reason_1 ?? item.main_reason_2 ?? item.main_reason_3 ?? null,
      confidence_level: this.confidenceLabel(item.confidence_level),
      confidence_tone: this.confidenceTone(item.confidence_level),
      assignee_label: item.assignee_label ?? null,
      workflow_status: this.validationStatusLabel(item.validation_status),
      age_days: this.toNumberOrNull(item.age_days),
      guarantee_label: item.guarantee_label ?? item.code_garantie ?? null,
      claim_type_label: item.claim_type_label ?? null,
      business_validation_status: item.business_validation_status ?? null,
      has_ml_signal: Boolean(item.has_ml_signal),
      has_post_inspection_signal: Boolean(item.has_post_inspection_signal),
      score_version: item.score_version,
      score_run_id: item.score_run_id,
      created_at: item.created_at
    };
  }

  private attentionTone(level: string): ClaimSummary['attention_tone'] {
    const normalized = this.normalize(level);
    if (normalized.includes('priorit')) {
      return 'priority';
    }
    if (normalized.includes('renforc')) {
      return 'reinforced';
    }
    if (normalized.includes('verif')) {
      return 'review';
    }
    if (normalized.includes('standard')) {
      return 'standard';
    }
    return 'unknown';
  }

  private confidenceTone(level: string): ClaimSummary['confidence_tone'] {
    const normalized = this.normalize(level);
    if (normalized.includes('eleve') || normalized.includes('high')) {
      return 'high';
    }
    if (normalized.includes('moy') || normalized.includes('medium')) {
      return 'medium';
    }
    if (normalized.includes('limit') || normalized.includes('low')) {
      return 'limited';
    }
    return 'unknown';
  }

  private normalize(value: string): string {
    return value.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
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

  private validationStatusLabel(value: string | null | undefined): string {
    switch (value) {
      case 'SUSPICION_CONFIRMED':
        return 'Suspicion confirmee';
      case 'CONFORME':
        return 'Conforme';
      case 'A_COMPLETER':
        return 'A completer';
      default:
        return 'Non revu';
    }
  }

  private toNumberOrNull(value: number | string | null | undefined): number | null {
    if (value === null || value === undefined || value === '') {
      return null;
    }
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  private defaultFilters(): WorklistFilters {
    return {
      scoreVersion: DEFAULT_SCORE_VERSION,
      includeTotal: false,
      page: 1,
      pageSize: 25,
      sortBy: 'attention_score',
      sortDirection: 'desc',
      viewMode: 'comfortable'
    };
  }

  private loadFilters(): WorklistFilters {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? { ...this.defaultFilters(), ...JSON.parse(raw) } : this.defaultFilters();
    } catch {
      return this.defaultFilters();
    }
  }

  private persistFilters(filters: WorklistFilters): void {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(filters));
  }

  private cleanFilterPatch(partial: Partial<WorklistFilters>): Partial<WorklistFilters> {
    const cleaned: Partial<WorklistFilters> = {};
    for (const [key, value] of Object.entries(partial) as [keyof WorklistFilters, WorklistFilters[keyof WorklistFilters]][]) {
      cleaned[key] = value === '' ? undefined : value as never;
    }
    return cleaned;
  }
}

