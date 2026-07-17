import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Subscription, forkJoin } from 'rxjs';
import {
  ClaimDecisionRecord,
  ClaimDecisionValue,
  IrisApiService,
  PowerbiGovernanceComponent
} from '../../core/services/iris-api.service';

const DECISION_LABELS: Record<ClaimDecisionValue, string> = {
  SUSPICION_CONFIRMED: 'Suspicion confirmee',
  CONFORME: 'Conforme',
  A_COMPLETER: 'A completer'
};

const DECISION_TONES: Record<ClaimDecisionValue, string> = {
  SUSPICION_CONFIRMED: 'high',
  CONFORME: 'ok',
  A_COMPLETER: 'medium'
};

const COMPONENT_LABELS: Record<string, string> = {
  CLAIM_ATTENTION: 'Score d attention',
  ML_ANOMALY: 'Atypicite ML',
  POST_INSPECTION: 'Post-inspection',
  VHS: 'Sante vehicule (VHS)'
};

@Component({
  selector: 'app-audit-page',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './audit-page.component.html',
  styleUrl: './audit-page.component.scss'
})
export class AuditPageComponent implements OnInit, OnDestroy {
  private readonly api = inject(IrisApiService);
  private subscription?: Subscription;

  readonly loading = signal(true);
  readonly errorMessage = signal<string | null>(null);
  readonly decisions = signal<ClaimDecisionRecord[]>([]);
  readonly governance = signal<PowerbiGovernanceComponent[]>([]);
  readonly decisionFilter = signal<string>('');

  readonly filteredDecisions = computed(() => {
    const filter = this.decisionFilter();
    const items = this.decisions();
    if (!filter) {
      return items;
    }
    if (filter === 'CORRECTIONS') {
      return items.filter((item) => !!item.corrects_decision_id);
    }
    return items.filter((item) => item.decision === filter);
  });

  readonly totalDecisions = computed(() => this.decisions().length);
  readonly totalCorrections = computed(
    () => this.decisions().filter((item) => !!item.corrects_decision_id).length
  );
  readonly distinctClaims = computed(
    () => new Set(this.decisions().map((item) => item.claim_sk)).size
  );
  readonly distinctReviewers = computed(
    () => new Set(this.decisions().map((item) => item.reviewer_email)).size
  );

  readonly filterChips = computed(() => [
    { value: '', label: 'Tout le journal', count: this.totalDecisions() },
    {
      value: 'SUSPICION_CONFIRMED',
      label: 'Suspicions confirmees',
      count: this.decisions().filter((d) => d.decision === 'SUSPICION_CONFIRMED').length
    },
    {
      value: 'CONFORME',
      label: 'Conformes',
      count: this.decisions().filter((d) => d.decision === 'CONFORME').length
    },
    {
      value: 'A_COMPLETER',
      label: 'A completer',
      count: this.decisions().filter((d) => d.decision === 'A_COMPLETER').length
    },
    { value: 'CORRECTIONS', label: 'Corrections', count: this.totalCorrections() }
  ]);

  ngOnInit(): void {
    this.subscription = forkJoin({
      decisions: this.api.getDecisionsFeed(undefined, 200),
      governance: this.api.getPowerbiGovernance()
    }).subscribe({
      next: ({ decisions, governance }) => {
        this.decisions.set(decisions.items ?? []);
        this.governance.set(governance.components ?? []);
        this.loading.set(false);
      },
      error: () => {
        this.errorMessage.set(
          'Le journal d audit est momentanement indisponible. Reessayez dans quelques instants.'
        );
        this.loading.set(false);
      }
    });
  }

  ngOnDestroy(): void {
    this.subscription?.unsubscribe();
  }

  applyFilter(value: string): void {
    this.decisionFilter.set(value);
  }

  decisionLabel(value: ClaimDecisionValue | null | undefined): string {
    return value ? DECISION_LABELS[value] ?? value : '—';
  }

  decisionTone(value: ClaimDecisionValue): string {
    return DECISION_TONES[value] ?? 'muted';
  }

  componentLabel(component: string): string {
    return COMPONENT_LABELS[component] ?? component;
  }

  formatDateTime(value: string | null | undefined): string {
    if (!value) {
      return '—';
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return '—';
    }
    return `${date.toLocaleDateString('fr-FR')} a ${date.toLocaleTimeString('fr-FR', {
      hour: '2-digit',
      minute: '2-digit'
    })}`;
  }

  formatRows(count: number): string {
    return Number(count ?? 0).toLocaleString('fr-FR');
  }

  shortRun(runId: string): string {
    const match = runId.match(/(\d{8})_\d{6}$/);
    if (!match) {
      return runId;
    }
    const raw = match[1];
    return `${raw.slice(6, 8)}/${raw.slice(4, 6)}/${raw.slice(0, 4)}`;
  }
}
