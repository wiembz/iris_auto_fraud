import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Subscription, forkJoin } from 'rxjs';
import {
  ClaimDecisionRecord,
  ClaimListItem,
  IrisApiService
} from '../../core/services/iris-api.service';

interface ReviewerActivity {
  email: string;
  displayName: string;
  initials: string;
  total: number;
  confirmed: number;
  conforme: number;
  aCompleter: number;
  corrections: number;
  lastActivity: string | null;
}

const SCORE_VERSION = 'IRIS_CLAIM_ATTENTION_HYBRID_ML_V1_CANDIDATE';

@Component({
  selector: 'app-assignments-page',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './assignments-page.component.html',
  styleUrl: './assignments-page.component.scss'
})
export class AssignmentsPageComponent implements OnInit, OnDestroy {
  private readonly api = inject(IrisApiService);
  private subscription?: Subscription;

  readonly loading = signal(true);
  readonly errorMessage = signal<string | null>(null);

  readonly priorityQueue = signal<ClaimListItem[]>([]);
  readonly priorityTotal = signal<number | null>(null);
  readonly reinforcedTotal = signal<number | null>(null);
  readonly decisions = signal<ClaimDecisionRecord[]>([]);

  readonly reviewers = computed<ReviewerActivity[]>(() => {
    const byEmail = new Map<string, ReviewerActivity>();
    for (const decision of this.decisions()) {
      const email = decision.reviewer_email;
      const current = byEmail.get(email) ?? {
        email,
        displayName: this.nameFromEmail(email),
        initials: this.initialsFromEmail(email),
        total: 0,
        confirmed: 0,
        conforme: 0,
        aCompleter: 0,
        corrections: 0,
        lastActivity: null
      };
      current.total += 1;
      if (decision.decision === 'SUSPICION_CONFIRMED') {
        current.confirmed += 1;
      } else if (decision.decision === 'CONFORME') {
        current.conforme += 1;
      } else {
        current.aCompleter += 1;
      }
      if (decision.corrects_decision_id) {
        current.corrections += 1;
      }
      if (!current.lastActivity || decision.decided_at > current.lastActivity) {
        current.lastActivity = decision.decided_at;
      }
      byEmail.set(email, current);
    }
    return [...byEmail.values()].sort((a, b) => b.total - a.total);
  });

  readonly decisionsTotal = computed(() => this.decisions().length);
  readonly maxReviewerTotal = computed(() =>
    Math.max(...this.reviewers().map((r) => r.total), 1)
  );

  ngOnInit(): void {
    this.subscription = forkJoin({
      priority: this.api.getClaims({
        scoreVersion: SCORE_VERSION,
        attentionLevel: 'Examen prioritaire suggere',
        validationStatus: 'NONE',
        pageSize: 8,
        includeTotal: true
      }),
      reinforced: this.api.getClaims({
        scoreVersion: SCORE_VERSION,
        attentionLevel: 'Examen renforce suggere',
        validationStatus: 'NONE',
        pageSize: 1,
        includeTotal: true
      }),
      decisions: this.api.getDecisionsFeed(undefined, 200)
    }).subscribe({
      next: ({ priority, reinforced, decisions }) => {
        this.priorityQueue.set(priority.items ?? []);
        this.priorityTotal.set(priority.total ?? null);
        this.reinforcedTotal.set(reinforced.total ?? null);
        this.decisions.set(decisions.items ?? []);
        this.loading.set(false);
      },
      error: () => {
        this.errorMessage.set(
          "Les donnees d'organisation sont momentanement indisponibles. Reessayez dans quelques instants."
        );
        this.loading.set(false);
      }
    });
  }

  ngOnDestroy(): void {
    this.subscription?.unsubscribe();
  }

  formatCount(value: number | null): string {
    return value === null ? '—' : value.toLocaleString('fr-FR');
  }

  formatAmount(value: number | string | null | undefined): string {
    const amount = Number(value ?? 0);
    if (!Number.isFinite(amount) || amount === 0) {
      return '—';
    }
    return `${Math.round(amount).toLocaleString('fr-FR')} TND`;
  }

  formatDate(value: string | null | undefined): string {
    if (!value) {
      return '—';
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return '—';
    }
    return date.toLocaleDateString('fr-FR');
  }

  roundScore(score: number | string | null | undefined): number {
    return Math.round(Number(score ?? 0));
  }

  reviewerShare(reviewer: ReviewerActivity): number {
    return Math.max(6, Math.round((reviewer.total / this.maxReviewerTotal()) * 100));
  }

  private nameFromEmail(email: string): string {
    const local = email.split('@')[0] ?? email;
    return local
      .split(/[._-]/)
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ');
  }

  private initialsFromEmail(email: string): string {
    const parts = (email.split('@')[0] ?? email).split(/[._-]/).filter(Boolean);
    return parts
      .slice(0, 2)
      .map((part) => part.charAt(0).toUpperCase())
      .join('') || 'IR';
  }
}
