import { CommonModule, DOCUMENT } from '@angular/common';
import { Component, Inject, computed, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { AuthService } from '../../core/auth/auth.service';
import { IrisNavigationItem } from '../../core/models/navigation.model';

@Component({
  selector: 'app-app-layout',
  imports: [CommonModule, RouterLink, RouterLinkActive, RouterOutlet],
  templateUrl: './app-layout.component.html',
  styleUrl: './app-layout.component.scss'
})
export class AppLayoutComponent {
  theme: 'light' | 'dark' = 'light';

  private readonly auth = inject(AuthService);
  readonly user = this.auth.currentUser;

  readonly navItems: IrisNavigationItem[] = [
    { label: 'Vue generale', route: '/app/dashboard', roles: ['responsable', 'manager', 'administrateur'] },
    { label: 'File de travail', route: '/app/claims', roles: ['gestionnaire', 'responsable', 'manager'] },
    { label: 'Vehicule et VHS', route: '/app/vehicle', roles: ['gestionnaire', 'responsable', 'manager'] },
    { label: 'Signaux et explications', route: '/app/signals', roles: ['gestionnaire', 'responsable', 'manager'] },
    { label: 'Checklist', route: '/app/checklist', roles: ['gestionnaire', 'responsable'] },
    { label: 'Validation metier', route: '/app/feedback', roles: ['responsable', 'manager'] },
    { label: 'Affectations', route: '/app/assignments', roles: ['responsable', 'manager'] },
    { label: 'Audit', route: '/app/audit', roles: ['manager', 'administrateur'] },
    { label: 'Administration', route: '/app/administration', roles: ['administrateur'] }
  ];

  readonly visibleNavItems = computed(() => {
    const user = this.user();
    if (!user) {
      return [];
    }
    return this.navItems.filter((item) => !item.roles || item.roles.includes(user.role));
  });

  constructor(@Inject(DOCUMENT) private readonly documentRef: Document) {
    this.applyTheme();
  }

  toggleTheme(): void {
    this.theme = this.theme === 'light' ? 'dark' : 'light';
    this.applyTheme();
  }

  userInitials(): string {
    const user = this.user();
    if (!user) {
      return 'IR';
    }
    return user.roleLabel
      .split(' ')
      .map((part) => part.charAt(0))
      .join('')
      .slice(0, 2)
      .toUpperCase();
  }

  private applyTheme(): void {
    this.documentRef.documentElement.setAttribute('data-theme', this.theme);
    this.documentRef.documentElement.setAttribute('data-accent', 'teal');
  }
}

