import { Component } from '@angular/core';

@Component({
  selector: 'app-worklist-page',
  template: `
    <p class="iris-eyebrow">Dossiers a examiner</p>
    <h1 class="page-title">File de travail metier</h1>
    <div class="iris-empty-state">
      <span class="iris-empty-state__icon">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 2 2 7l10 5 10-5-10-5z"/><path d="m2 17 10 5 10-5M2 12l10 5 10-5"/></svg>
      </span>
      <div class="iris-empty-state__title">La file de travail sera bientot disponible</div>
      <p class="iris-empty-state__text">
        La table des dossiers sera construite apres validation du template. Elle affichera
        les dossiers priorises, les raisons principales et la confiance des donnees.
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
export class WorklistPageComponent {}
