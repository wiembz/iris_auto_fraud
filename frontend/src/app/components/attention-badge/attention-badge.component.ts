import { Component, Input } from '@angular/core';

@Component({
  selector: 'app-attention-badge',
  imports: [],
  template: `<span class="badge" [class]="badgeClass">{{ label }}</span>`,
  styles: [`
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 1.7rem;
      padding: 0.25rem 0.6rem;
      border-radius: 999px;
      font-size: 0.78rem;
      font-weight: 700;
      white-space: nowrap;
      border: 1px solid transparent;
    }

    .standard {
      color: #355240;
      background: #e8f3eb;
      border-color: #bddbc7;
    }

    .check {
      color: #66510a;
      background: #fff3c4;
      border-color: #ead071;
    }

    .review {
      color: #7a3b14;
      background: #ffe0c2;
      border-color: #f0a86d;
    }

    .priority {
      color: #7f1d1d;
      background: #ffe0e0;
      border-color: #f2a0a0;
    }

    .confidence {
      color: #24445c;
      background: #e4f0f7;
      border-color: #accde1;
    }
  `]
})
export class AttentionBadgeComponent {
  @Input({ required: true }) label = '';
  @Input() type: 'attention' | 'confidence' = 'attention';

  get badgeClass(): string {
    if (this.type === 'confidence') {
      return 'confidence';
    }

    const normalized = this.label.toLowerCase();
    if (normalized.includes('prioritaire')) {
      return 'priority';
    }
    if (normalized.includes('renforce')) {
      return 'review';
    }
    if (normalized.includes('verifier')) {
      return 'check';
    }
    return 'standard';
  }
}
