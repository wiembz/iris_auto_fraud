import { Component, Input } from '@angular/core';

export interface WorkloadRow {
  label: string;
  value: number | string;
  share: number;
  helper?: string;
  status?: 'available' | 'pending';
}

@Component({
  selector: 'app-workload-chart',
  standalone: true,
  templateUrl: './workload-chart.component.html',
  styleUrl: './workload-chart.component.scss'
})
export class WorkloadChartComponent {
  @Input() title = 'Charge de revue';
  @Input() subtitle = 'Vue operationnelle des elements suivis';
  @Input() rows: WorkloadRow[] = [];

  formatValue(value: number | string): string {
    return typeof value === 'number' ? value.toLocaleString('fr-FR') : value;
  }
}
