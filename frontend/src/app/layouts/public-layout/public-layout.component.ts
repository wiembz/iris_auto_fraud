import { CommonModule, DOCUMENT } from '@angular/common';
import { Component, Inject } from '@angular/core';
import { RouterLink, RouterOutlet } from '@angular/router';
import { IrisLogoComponent } from '../../shared/ui/iris-logo.component';

@Component({
  selector: 'app-public-layout',
  imports: [CommonModule, RouterLink, RouterOutlet, IrisLogoComponent],
  templateUrl: './public-layout.component.html',
  styleUrl: './public-layout.component.scss'
})
export class PublicLayoutComponent {
  theme: 'light' | 'dark' = 'light';
  isMenuOpen = false;

  readonly navLinks = [
    { label: 'Pourquoi IRIS', fragment: 'valeur' },
    { label: 'Le parcours', fragment: 'parcours' },
    { label: 'Modules', fragment: 'modules' },
    { label: 'Confiance', fragment: 'confiance' }
  ];

  constructor(@Inject(DOCUMENT) private readonly documentRef: Document) {
    this.applyTheme();
  }

  toggleTheme(): void {
    this.theme = this.theme === 'light' ? 'dark' : 'light';
    this.applyTheme();
  }

  toggleMenu(): void {
    this.isMenuOpen = !this.isMenuOpen;
  }

  closeMenu(): void {
    this.isMenuOpen = false;
  }

  private applyTheme(): void {
    this.documentRef.documentElement.setAttribute('data-theme', this.theme);
    this.documentRef.documentElement.setAttribute('data-accent', 'teal');
  }
}
