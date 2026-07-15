import { Component, Input } from '@angular/core';
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

  reasonsFor(claim: ClaimListItem): string[] {
    return [claim.main_reason_1, claim.main_reason_2, claim.main_reason_3].filter(
      (reason): reason is string => !!reason
    );
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
