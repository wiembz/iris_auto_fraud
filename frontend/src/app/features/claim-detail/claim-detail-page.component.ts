import { Component } from '@angular/core';

@Component({
  selector: 'app-claim-detail-page',
  template: `
    <p class="iris-eyebrow">Detail dossier</p>
    <h1 class="page-title">Revue dossier</h1>
    <div class="iris-empty-state">
      <span class="iris-empty-state__icon">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M22 11.1V16a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="m22 4-10 9-3-3"/></svg>
      </span>
      <div class="iris-empty-state__title">La revue dossier sera bientot disponible</div>
      <p class="iris-empty-state__text">
        Cette page recevra le resume dossier, les signaux d'attention, la chronologie,
        le contexte post-inspection et l'indicateur d'atypicite statistique candidat.
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
export class ClaimDetailPageComponent {}
