import { DOCUMENT } from '@angular/common';
import { Component, Inject, computed, inject } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { AuthService } from '../../core/auth/auth.service';
import { IrisLogoComponent } from '../../shared/ui/iris-logo.component';

interface AppNavItem {
  label: string;
  route: string;
  roles?: string[];
  /* Traits SVG (stroke) de l'icone, viewBox 24x24. */
  icon: string[];
}

@Component({
  selector: 'app-app-layout',
  imports: [RouterLink, RouterLinkActive, RouterOutlet, IrisLogoComponent],
  templateUrl: './app-layout.component.html',
  styleUrl: './app-layout.component.scss'
})
export class AppLayoutComponent {
  theme: 'light' | 'dark' = 'light';

  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  readonly user = this.auth.currentUser;

  readonly navItems: AppNavItem[] = [
    {
      label: 'Vue générale',
      route: '/app/dashboard',
      roles: ['responsable', 'manager', 'administrateur'],
      icon: ['M3 3h7v7H3z', 'M14 3h7v7h-7z', 'M14 14h7v7h-7z', 'M3 14h7v7H3z']
    },
    {
      label: 'File de travail',
      route: '/app/claims',
      roles: ['gestionnaire', 'responsable', 'manager'],
      icon: ['M8 6h13', 'M8 12h13', 'M8 18h13', 'M3.5 6h.01', 'M3.5 12h.01', 'M3.5 18h.01']
    },
    {
      label: 'Véhicule & VHS',
      route: '/app/vehicle',
      roles: ['gestionnaire', 'responsable', 'manager'],
      icon: [
        'M5 16.5 6.6 11a2 2 0 0 1 1.9-1.5h7a2 2 0 0 1 1.9 1.5L19 16.5',
        'M4 16.5h16v3a1 1 0 0 1-1 1h-1.5a1 1 0 0 1-1-1v-1h-9v1a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z',
        'M7.5 13.5h.01',
        'M16.5 13.5h.01'
      ]
    },
    {
      label: 'Signaux & explications',
      route: '/app/signals',
      roles: ['gestionnaire', 'responsable', 'manager'],
      icon: ['M22 12h-4l-3 9L9 3l-3 9H2']
    },
    {
      label: 'Checklist',
      route: '/app/checklist',
      roles: ['gestionnaire', 'responsable'],
      icon: ['m9 11 3 3L22 4', 'M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11']
    },
    {
      label: 'Validation métier',
      route: '/app/feedback',
      roles: ['gestionnaire', 'responsable', 'manager'],
      icon: [
        'M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3z',
        'M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3'
      ]
    },
    {
      label: 'Affectations',
      route: '/app/assignments',
      roles: ['responsable', 'manager'],
      icon: [
        'M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2',
        'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8',
        'M23 21v-2a4 4 0 0 0-3-3.87',
        'M16 3.13a4 4 0 0 1 0 7.75'
      ]
    },
    {
      label: 'Audit',
      route: '/app/audit',
      roles: ['manager', 'administrateur'],
      icon: ['M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z', 'm9 12 2 2 4-4']
    },
    {
      label: 'Administration',
      route: '/app/administration',
      roles: ['administrateur'],
      icon: ['M4 21v-7', 'M4 10V3', 'M12 21v-9', 'M12 8V3', 'M20 21v-5', 'M20 12V3', 'M1 14h6', 'M9 8h6', 'M17 16h6']
    }
  ];

  readonly visibleNavItems = computed(() => {
    const user = this.user();
    if (!user) {
      return [];
    }
    return this.navItems.filter((item) => !item.roles || item.roles.includes(user.role));
  });

  readonly firstName = computed(() => {
    const user = this.user();
    if (!user) {
      return '';
    }
    return user.displayName.split(' ')[0] ?? user.displayName;
  });

  constructor(@Inject(DOCUMENT) private readonly documentRef: Document) {
    this.applyTheme();
  }

  toggleTheme(): void {
    this.theme = this.theme === 'light' ? 'dark' : 'light';
    this.applyTheme();
  }

  signOut(): void {
    this.auth.signOut();
    void this.router.navigateByUrl('/');
  }

  userInitials(): string {
    const user = this.user();
    if (!user) {
      return 'IR';
    }
    return user.displayName
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
