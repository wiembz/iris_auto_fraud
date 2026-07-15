import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';
import { AuthService } from '../../core/auth/auth.service';
import { ClaimDecisionRecord, ClaimDecisionValue, IrisApiService } from '../../core/services/iris-api.service';

const DECISION_LABELS: Record<ClaimDecisionValue, string> = {
  SUSPICION_CONFIRMED: 'Suspicion confirmee',
  CONFORME: 'Dossier conforme',
  A_COMPLETER: 'A completer'
};

@Component({
  selector: 'app-validations-page',
  standalone: true,
  imports: [RouterLink, DatePipe],
  templateUrl: './validations-page.component.html',
  styleUrl: './validations-page.component.scss'
})
export class ValidationsPageComponent implements OnInit, OnDestroy {
  private readonly api = inject(IrisApiService);
  private readonly auth = inject(AuthService);
  private subscription?: Subscription;

  readonly user = this.auth.currentUser;
  readonly isPersonalView = computed(() => this.user()?.role === 'gestionnaire');
  readonly pageTitle = computed(() => (this.isPersonalView() ? 'Mes validations' : 'Validations de l equipe'));
  readonly pageSubtitle = computed(() =>
    this.isPersonalView()
      ? 'Retrouvez l historique de vos decisions sur les dossiers examines.'
      : 'Suivi des decisions prises sur les dossiers prioritaires, tous gestionnaires confondus.'
  );

  readonly loading = signal(true);
  readonly errorMessage = signal<string | null>(null);
  readonly items = signal<ClaimDecisionRecord[]>([]);

  // Le flux liste chaque decision (y compris celles corrigees depuis), mais
  // les compteurs ne doivent refleter que le statut ACTUEL de chaque dossier :
  // sans deduplication, un dossier corrige (Conforme -> Suspicion confirmee)
  // compterait a tort dans les deux categories. Items deja ordonnes par
  // decided_at DESC par le backend -> la premiere occurrence par claim_sk
  // est la plus recente.
  readonly latestPerClaim = computed(() => {
    const seen = new Set<number>();
    const latest: ClaimDecisionRecord[] = [];
    for (const item of this.items()) {
      if (!seen.has(item.claim_sk)) {
        seen.add(item.claim_sk);
        latest.push(item);
      }
    }
    return latest;
  });

  readonly counts = computed(() => {
    const current = this.latestPerClaim();
    return {
      total: current.length,
      suspicion: current.filter((item) => item.decision === 'SUSPICION_CONFIRMED').length,
      conforme: current.filter((item) => item.decision === 'CONFORME').length,
      aCompleter: current.filter((item) => item.decision === 'A_COMPLETER').length
    };
  });

  ngOnInit(): void {
    const email = this.isPersonalView() ? this.user()?.email : undefined;
    this.subscription = this.api.getDecisionsFeed(email, 100).subscribe({
      next: (res) => {
        this.items.set(res.items);
        this.loading.set(false);
      },
      error: () => {
        this.errorMessage.set('Les validations sont momentanement indisponibles. Reessayez dans quelques instants.');
        this.loading.set(false);
      }
    });
  }

  ngOnDestroy(): void {
    this.subscription?.unsubscribe();
  }

  decisionLabel(value: ClaimDecisionValue): string {
    return DECISION_LABELS[value] ?? value;
  }

  correctionNote(item: ClaimDecisionRecord): string | null {
    if (!item.corrects_decision_id) {
      return null;
    }
    const previous = item.corrected_decision_value ? this.decisionLabel(item.corrected_decision_value) : 'une decision precedente';
    return `Correction : ${previous} -> ${this.decisionLabel(item.decision)}`;
  }
}
