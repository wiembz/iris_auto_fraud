import { Component, EventEmitter, Input, Output } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ClaimSummary, SortDirection, WorklistViewMode } from '../../../core/models/claim-summary.model';
import { AttentionBadgeComponent } from '../attention-badge/attention-badge.component';

export interface WorklistSortChange {
  sortBy: string;
  sortDirection: SortDirection;
}

const OPERATIONAL_STATUS_LABELS: Record<string, string> = {
  NOUVEAU: 'Nouveau',
  AFFECTE: 'Affecte',
  EN_COURS: 'En cours',
  EN_ATTENTE_PIECES: 'En attente de pieces',
  PRET_POUR_DECISION: 'Pret pour decision',
  TRANSMIS_INVESTIGATION: 'Transmis a l investigation',
  RETOUR_INVESTIGATION: 'Retour investigation',
  CLOTURE: 'Cloture'
};

@Component({
  selector: 'app-claim-table',
  standalone: true,
  imports: [RouterLink, AttentionBadgeComponent],
  templateUrl: './claim-table.component.html',
  styleUrl: './claim-table.component.scss'
})
export class ClaimTableComponent {
  @Input() claims: ClaimSummary[] = [];
  @Input() loading = false;
  @Input() errorMessage: string | null = null;
  @Input() total = 0;
  @Input() totalIsExact = false;
  @Input() page = 1;
  @Input() pageSize = 25;
  @Input() sortBy = 'attention_score';
  @Input() sortDirection: SortDirection = 'desc';
  @Input() viewMode: WorklistViewMode = 'comfortable';
  @Input() hasNextPage = false;

  @Output() pageChange = new EventEmitter<number>();
  @Output() sortChange = new EventEmitter<WorklistSortChange>();

  readonly skeletonRows = Array.from({ length: 8 }, (_, index) => index);

  get totalPages(): number {
    return Math.max(Math.ceil(this.total / this.pageSize), this.page);
  }

  get canGoNext(): boolean {
    return this.hasNextPage;
  }

  changeSort(column: string): void {
    this.sortChange.emit({
      sortBy: column,
      sortDirection: this.sortBy === column && this.sortDirection === 'desc' ? 'asc' : 'desc'
    });
  }

  previousPage(): void {
    if (this.page > 1) {
      this.pageChange.emit(this.page - 1);
    }
  }

  nextPage(): void {
    if (this.canGoNext) {
      this.pageChange.emit(this.page + 1);
    }
  }

  sortMarker(column: string): string {
    if (this.sortBy !== column) {
      return '';
    }
    return this.sortDirection === 'asc' ? '↑' : '↓';
  }

  displayText(value: string | null | undefined): string {
    return value && value.trim() ? value : '—';
  }

  operationalStatusLabel(claim: ClaimSummary): string {
    return claim.operational_status
      ? OPERATIONAL_STATUS_LABELS[claim.operational_status] ?? claim.operational_status
      : '—';
  }

  displayDate(value: string | null | undefined): string {
    if (!value) {
      return '—';
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return date.toLocaleDateString('fr-FR');
  }

  displayAmount(value: number | null): string {
    return value === null ? '—' : `${value.toLocaleString('fr-FR')} TND`;
  }

  displayAge(value: number | null | undefined, claimDate?: string | null): string {
    const days = this.resolveAgeDays(value, claimDate);
    return days === null ? '—' : `${days.toLocaleString('fr-FR')} j`;
  }

  // Seuils provisoires (30 / 90 j) en l absence de SLA de traitement valide
  // formellement par le metier — a ajuster des que ce seuil sera confirme.
  ageTone(claim: ClaimSummary): 'ok' | 'warn' | 'crit' {
    const days = this.resolveAgeDays(claim.age_days, claim.claim_date);
    if (days === null) {
      return 'ok';
    }
    if (days > 90) {
      return 'crit';
    }
    if (days > 30) {
      return 'warn';
    }
    return 'ok';
  }

  private resolveAgeDays(value: number | null | undefined, claimDate?: string | null): number | null {
    let days = value ?? null;
    if (days === null && claimDate) {
      const date = new Date(claimDate);
      if (!Number.isNaN(date.getTime())) {
        days = Math.max(0, Math.floor((Date.now() - date.getTime()) / 86_400_000));
      }
    }
    return days;
  }

  signalOriginTitle(claim: ClaimSummary): string {
    const origins: string[] = [];
    if (claim.has_post_inspection_signal) {
      origins.push('Post-inspection');
    }
    if (claim.has_ml_signal) {
      origins.push('Atypicite statistique');
    }
    return origins.length ? `Origine des signaux : ${origins.join(', ')}` : '';
  }
}

