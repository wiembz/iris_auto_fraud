import { Component, Input } from '@angular/core';

export type DashboardKpiTone = 'primary' | 'high' | 'medium' | 'low' | 'ok' | 'muted';

@Component({
  selector: 'app-kpi-card',
  standalone: true,
  templateUrl: './kpi-card.component.html',
  styleUrl: './kpi-card.component.scss'
})
export class KpiCardComponent {
  @Input({ required: true }) label = '';
  @Input({ required: true }) value: number | string = '';
  @Input() suffix = '';
  @Input() helper = '';
  @Input() tone: DashboardKpiTone = 'primary';
  @Input() status: 'available' | 'pending' = 'available';

  formattedValue(): string {
    if (typeof this.value === 'number') {
      return `${this.value.toLocaleString('fr-FR')}${this.suffix}`;
    }
    return `${this.value}${this.suffix}`;
  }
}
