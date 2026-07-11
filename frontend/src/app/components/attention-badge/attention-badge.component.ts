import { Component, Input } from '@angular/core';

@Component({
  selector: 'app-attention-badge',
  imports: [],
  template: `<span class="iris-badge" [class]="badgeClass">{{ label }}</span>`,
  styles: []
})
export class AttentionBadgeComponent {
  @Input({ required: true }) label = '';
  @Input() type: 'attention' | 'confidence' = 'attention';

  get badgeClass(): string {
    if (this.type === 'confidence') {
      return 'iris-badge--info';
    }

    const normalized = this.label.toLowerCase();
    if (normalized.includes('prioritaire')) {
      return 'iris-badge--high';
    }
    if (normalized.includes('renforce')) {
      return 'iris-badge--medium';
    }
    if (normalized.includes('verifier')) {
      return 'iris-badge--low';
    }
    return 'iris-badge--positive';
  }
}
