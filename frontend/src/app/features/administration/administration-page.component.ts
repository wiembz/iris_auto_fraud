import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { AuthService } from '../../core/auth/auth.service';
import {
  IrisApiService,
  PowerbiGovernanceComponent
} from '../../core/services/iris-api.service';

interface AccessRow {
  space: string;
  gestionnaire: boolean;
  responsable: boolean;
  manager: boolean;
  administrateur: boolean;
}

const COMPONENT_LABELS: Record<string, string> = {
  CLAIM_ATTENTION: 'Score d attention sinistres',
  ML_ANOMALY: 'Signal d atypicite ML',
  POST_INSPECTION: 'Signaux post-inspection',
  VHS: 'Sante vehicule (VHS)'
};

@Component({
  selector: 'app-administration-page',
  standalone: true,
  templateUrl: './administration-page.component.html',
  styleUrl: './administration-page.component.scss'
})
export class AdministrationPageComponent implements OnInit, OnDestroy {
  private readonly api = inject(IrisApiService);
  private readonly auth = inject(AuthService);
  private governanceSubscription?: Subscription;
  private healthSubscription?: Subscription;

  readonly user = this.auth.currentUser;

  readonly governance = signal<PowerbiGovernanceComponent[]>([]);
  readonly governanceLoading = signal(true);
  readonly apiStatus = signal<'checking' | 'up' | 'down'>('checking');
  readonly apiLatencyMs = signal<number | null>(null);

  readonly totalRows = computed(() =>
    this.governance().reduce((sum, item) => sum + Number(item.row_count ?? 0), 0)
  );

  readonly accessMatrix: AccessRow[] = [
    { space: 'Vue generale', gestionnaire: false, responsable: true, manager: true, administrateur: true },
    { space: 'File de travail & revue de dossier', gestionnaire: true, responsable: true, manager: true, administrateur: false },
    { space: 'Vehicule & VHS', gestionnaire: true, responsable: true, manager: true, administrateur: false },
    { space: 'Analytique Power BI', gestionnaire: false, responsable: true, manager: true, administrateur: true },
    { space: 'Validation metier', gestionnaire: true, responsable: true, manager: true, administrateur: false },
    { space: 'Affectations', gestionnaire: false, responsable: true, manager: true, administrateur: false },
    { space: 'Audit', gestionnaire: false, responsable: false, manager: true, administrateur: true },
    { space: 'Administration', gestionnaire: false, responsable: false, manager: false, administrateur: true }
  ];

  ngOnInit(): void {
    const startedAt = performance.now();
    this.healthSubscription = this.api.getSummary().subscribe({
      next: () => {
        this.apiLatencyMs.set(Math.round(performance.now() - startedAt));
        this.apiStatus.set('up');
      },
      error: () => {
        this.apiStatus.set('down');
      }
    });
    this.governanceSubscription = this.api.getPowerbiGovernance().subscribe({
      next: (res) => {
        this.governance.set(res.components ?? []);
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
    this.healthSubscription?.unsubscribe();
  }

  componentLabel(component: string): string {
    return COMPONENT_LABELS[component] ?? component;
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
