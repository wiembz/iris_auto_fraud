import { Component, Input } from '@angular/core';
import { WorklistViewMode } from '../../../core/models/claim-summary.model';

@Component({
  selector: 'app-worklist-summary',
  standalone: true,
  templateUrl: './worklist-summary.component.html',
  styleUrl: './worklist-summary.component.scss'
})
export class WorklistSummaryComponent {
  @Input() total = 0;
  @Input() page = 1;
  @Input() pageSize = 25;
  @Input() visibleCount = 0;
  @Input() activeFilterCount = 0;
  @Input() viewMode: WorklistViewMode = 'comfortable';
  @Input() totalIsExact = true;

  get totalLabel(): string {
    if (this.totalIsExact) {
      return this.total.toLocaleString('fr-FR');
    }
    return this.total > 0 ? `> ${(this.total - 1).toLocaleString('fr-FR')}` : '0';
  }

  get firstRow(): number {
    return this.total === 0 ? 0 : (this.page - 1) * this.pageSize + 1;
  }

  get lastRow(): number {
    return Math.min(this.page * this.pageSize, this.total);
  }
}


