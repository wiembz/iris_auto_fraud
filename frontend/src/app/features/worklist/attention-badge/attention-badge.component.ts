import { Component, Input, computed } from '@angular/core';

@Component({
  selector: 'app-attention-badge',
  standalone: true,
  templateUrl: './attention-badge.component.html',
  styleUrl: './attention-badge.component.scss'
})
export class AttentionBadgeComponent {
  @Input({ required: true }) label = '';
  @Input() variant: 'attention' | 'confidence' | 'status' = 'attention';

  readonly tone = computed(() => this.resolveTone(this.label));

  private resolveTone(value: string): string {
    const normalized = value
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '');

    if (normalized.includes('priorit') || normalized.includes('fort') || normalized.includes('high') || normalized.includes('suspicion')) {
      return 'high';
    }
    if (normalized.includes('renforc') || normalized.includes('moy') || normalized.includes('medium') || normalized.includes('completer')) {
      return 'medium';
    }
    if (normalized.includes('verif') || normalized.includes('limit') || normalized.includes('low')) {
      return 'low';
    }
    if (normalized.includes('eleve') || normalized.includes('ok') || normalized.includes('standard') || normalized.includes('conforme')) {
      return 'ok';
    }
    return 'muted';
  }
}
