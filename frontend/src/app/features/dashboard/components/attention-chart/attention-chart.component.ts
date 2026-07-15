import { Component, Input } from '@angular/core';

export type AttentionTone = 'high' | 'medium' | 'low' | 'ok' | 'muted';

export interface AttentionChartRow {
  label: string;
  count: number;
  share: number;
  tone: AttentionTone;
}

@Component({
  selector: 'app-attention-chart',
  standalone: true,
  templateUrl: './attention-chart.component.html',
  styleUrl: './attention-chart.component.scss'
})
export class AttentionChartComponent {
  @Input() title = 'Niveaux d attention';
  @Input() subtitle = 'Repartition des dossiers selon le dernier run disponible';
  @Input() rows: AttentionChartRow[] = [];
  @Input() mode: 'bars' | 'stacked' = 'bars';
}
