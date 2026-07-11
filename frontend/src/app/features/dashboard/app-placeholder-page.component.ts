import { Component, inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';

@Component({
  selector: 'app-placeholder-page',
  template: `
    <p class="iris-eyebrow">Module a cadrer</p>
    <h1 class="page-title">{{ title }}</h1>
    <div class="iris-empty-state">
      <span class="iris-empty-state__icon">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 1 1-4 0v-.1A1.6 1.6 0 0 0 6.8 19l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 4.6 15H4.5a2 2 0 1 1 0-4h.1A1.6 1.6 0 0 0 6 8.3l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.6 1.6 0 0 0 11 4.6V4.5a2 2 0 1 1 4 0v.1A1.6 1.6 0 0 0 17.7 6l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0 1.1 2.7h.1a2 2 0 1 1 0 4h-.4z"/></svg>
      </span>
      <div class="iris-empty-state__title">Module reserve dans la navigation</div>
      <p class="iris-empty-state__text">
        Son contenu sera implemente apres validation du parcours metier et des donnees
        exposees par l'API read-only.
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
export class AppPlaceholderPageComponent {
  private readonly route = inject(ActivatedRoute);
  readonly title = this.route.snapshot.data['title'] ?? 'Module IRIS';
}
