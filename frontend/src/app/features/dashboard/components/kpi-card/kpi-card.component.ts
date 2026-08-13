import { Component, Input, inject } from '@angular/core';
import { Router } from '@angular/router';

export type DashboardKpiTone = 'primary' | 'high' | 'medium' | 'low' | 'ok' | 'muted';

@Component({
  selector: 'app-kpi-card',
  standalone: true,
  templateUrl: './kpi-card.component.html',
  styleUrl: './kpi-card.component.scss'
})
export class KpiCardComponent {
  private readonly router = inject(Router);

  @Input({ required: true }) label = '';
  @Input({ required: true }) value: number | string = '';
  @Input() suffix = '';
  @Input() helper = '';
  @Input() tone: DashboardKpiTone = 'primary';
  @Input() status: 'available' | 'pending' = 'available';
  // Une carte KPI sans action possible n est qu un chiffre mort : chaque
  // carte du cockpit doit pouvoir ouvrir la file deja filtree correspondante.
  @Input() link?: string;
  @Input() queryParams?: Record<string, string>;
  // Une seule tuile "lead" par cockpit : celle qui repond le plus directement
  // a "de quoi dois-je m occuper maintenant ?" recoit un poids visuel plus
  // fort que le reste de la grille, qui passe en rang secondaire.
  @Input() lead = false;

  formattedValue(): string {
    if (typeof this.value === 'number') {
      return `${this.value.toLocaleString('fr-FR')}${this.suffix}`;
    }
    return `${this.value}${this.suffix}`;
  }

  open(): void {
    if (!this.link) {
      return;
    }
    void this.router.navigate([this.link], this.queryParams ? { queryParams: this.queryParams } : {});
  }

  onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      this.open();
    }
  }
}
