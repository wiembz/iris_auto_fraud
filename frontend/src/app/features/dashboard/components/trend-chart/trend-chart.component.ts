import { Component, Input, computed, signal } from '@angular/core';

export interface TrendPoint {
  month: string;
  claims: number;
  priorityClaims: number;
}

interface TrendColumn {
  key: string;
  monthLabel: string;
  claims: number;
  priorityClaims: number;
  volumeSharePct: number;
  priorityDotPct: number;
}

const MONTH_LABELS = ['Jan', 'Fev', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Aout', 'Sep', 'Oct', 'Nov', 'Dec'];

@Component({
  selector: 'app-trend-chart',
  standalone: true,
  templateUrl: './trend-chart.component.html',
  styleUrl: './trend-chart.component.scss'
})
export class TrendChartComponent {
  @Input() title = 'Tendance';
  @Input() subtitle = '';
  @Input() set points(value: TrendPoint[]) {
    this._points.set(value ?? []);
  }

  readonly hoveredKey = signal<string | null>(null);
  private readonly _points = signal<TrendPoint[]>([]);

  readonly columns = computed<TrendColumn[]>(() => {
    const rows = this._points();
    const maxClaims = Math.max(...rows.map((r) => r.claims), 1);
    const maxPriority = Math.max(...rows.map((r) => r.priorityClaims), 1);
    return rows.map((row) => ({
      key: row.month,
      monthLabel: this.monthLabel(row.month),
      claims: row.claims,
      priorityClaims: row.priorityClaims,
      volumeSharePct: Math.max(4, Math.round((row.claims / maxClaims) * 100)),
      priorityDotPct: Math.max(6, Math.round((row.priorityClaims / maxPriority) * 100))
    }));
  });

  readonly totalClaims = computed(() => this._points().reduce((sum, r) => sum + r.claims, 0));
  readonly totalPriority = computed(() => this._points().reduce((sum, r) => sum + r.priorityClaims, 0));

  hover(key: string | null): void {
    this.hoveredKey.set(key);
  }

  private monthLabel(month: string): string {
    const date = new Date(month);
    if (Number.isNaN(date.getTime())) {
      return month;
    }
    return MONTH_LABELS[date.getMonth()];
  }
}
