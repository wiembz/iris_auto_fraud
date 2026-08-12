import { Component, Input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ClaimListItem } from '../../../../core/services/iris-api.service';

@Component({
  selector: 'app-recent-claims',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './recent-claims.component.html',
  styleUrl: './recent-claims.component.scss'
})
export class RecentClaimsComponent {
  @Input() title = 'Dossiers a examiner';
  @Input() subtitle = 'Dossiers remontes par la derniere analyse disponible';
  @Input() claims: ClaimListItem[] = [];
  // Volume reel de dossiers signales, distinct des quelques lignes affichees
  // ici : sert de badge d alerte pour signaler l ampleur au premier coup d oeil.
  @Input() alertCount: number | null = null;

  readonly collapsed = signal(false);

  toggleCollapsed(): void {
    this.collapsed.set(!this.collapsed());
  }

  reasonsFor(claim: ClaimListItem): string[] {
    return [claim.main_reason_1, claim.main_reason_2, claim.main_reason_3].filter(
      (reason): reason is string => !!reason
    );
  }

  mainReason(claim: ClaimListItem): string {
    return this.reasonsFor(claim)[0] ?? 'Raison principale non renseignee';
  }

  extraReasonsCount(claim: ClaimListItem): number {
    return Math.max(this.reasonsFor(claim).length - 1, 0);
  }

  toneFor(level: string): 'high' | 'medium' | 'low' | 'ok' {
    const normalized = level
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '');
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

  claimRoute(claim: ClaimListItem): number {
    return claim.claim_sk;
  }

  confidenceLabel(level: string): string {
    const normalized = (level ?? '').toLowerCase();
    if (normalized.includes('high') || normalized.includes('elev')) {
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
}
