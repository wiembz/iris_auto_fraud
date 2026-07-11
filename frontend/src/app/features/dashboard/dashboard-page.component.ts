import { Component } from '@angular/core';

@Component({
  selector: 'app-dashboard-page',
  template: `
    <p class="iris-eyebrow">Vue generale</p>
    <h1 class="page-title">Socle de consultation IRIS</h1>
    <div class="iris-empty-state">
      <span class="iris-empty-state__icon">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/></svg>
      </span>
      <div class="iris-empty-state__title">La synthese sera bientot disponible</div>
      <p class="iris-empty-state__text">
        Cette zone accueillera la synthese des dossiers a examiner, les volumes par niveau
        d'attention et les indicateurs de confiance. Le template est pret, les donnees metier
        seront branchees dans une phase separee.
      </p>
    </div>
  `,
  styles: [`
    .page-title {
      margin: 0 0 18px;
      color: var(--iris-text);
      font-family: var(--iris-font-display);
      font-size: 30px;
      line-height: 1.12;
    }
  `]
})
export class DashboardPageComponent {}
