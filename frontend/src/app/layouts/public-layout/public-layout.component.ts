import { CommonModule, DOCUMENT } from '@angular/common';
import { Component, Inject } from '@angular/core';
import { RouterLink, RouterOutlet } from '@angular/router';

@Component({
  selector: 'app-public-layout',
  imports: [CommonModule, RouterLink, RouterOutlet],
  templateUrl: './public-layout.component.html',
  styleUrl: './public-layout.component.scss'
})
export class PublicLayoutComponent {
  theme: 'light' | 'dark' = 'light';

  readonly navLinks = [
    { label: 'Valeur', fragment: 'valeur' },
    { label: 'Fonctionnement', fragment: 'fonctionnement' },
    { label: 'Modules', fragment: 'modules' },
    { label: 'Gouvernance', fragment: 'gouvernance' }
  ];

  constructor(@Inject(DOCUMENT) private readonly documentRef: Document) {
    this.applyTheme();
  }

  toggleTheme(): void {
    this.theme = this.theme === 'light' ? 'dark' : 'light';
    this.applyTheme();
  }

  private applyTheme(): void {
    this.documentRef.documentElement.setAttribute('data-theme', this.theme);
    this.documentRef.documentElement.setAttribute('data-accent', 'teal');
  }
}
