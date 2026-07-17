import { Routes } from '@angular/router';
import { AppLayoutComponent } from './layouts/app-layout/app-layout.component';
import { PublicLayoutComponent } from './layouts/public-layout/public-layout.component';
import { authGuard } from './core/guards/auth.guard';

export const routes: Routes = [
  {
    path: '',
    component: PublicLayoutComponent,
    children: [
      {
        path: '',
        loadComponent: () =>
          import('./features/landing/landing-page.component').then((m) => m.LandingPageComponent)
      },
      {
        path: 'login',
        loadComponent: () =>
          import('./features/auth/login-page.component').then((m) => m.LoginPageComponent)
      }
    ]
  },
  {
    path: 'app',
    component: AppLayoutComponent,
    canActivate: [authGuard],
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
      {
        path: 'dashboard',
        loadComponent: () =>
          import('./features/dashboard/dashboard-page/dashboard-page.component').then(
            (m) => m.DashboardPageComponent
          )
      },
      {
        path: 'claims',
        loadComponent: () =>
          import('./features/worklist/worklist-page/worklist-page.component').then(
            (m) => m.WorklistPageComponent
          )
      },
      {
        path: 'claims/:claimSk',
        loadComponent: () =>
          import('./features/claim-detail/claim-detail-page.component').then(
            (m) => m.ClaimDetailPageComponent
          )
      },
      {
        path: 'vehicle',
        loadComponent: () =>
          import('./features/vehicle/vhs-page.component').then((m) => m.VhsPageComponent)
      },
      {
        path: 'analytics',
        loadComponent: () =>
          import('./features/analytics/analytics-page.component').then(
            (m) => m.AnalyticsPageComponent
          )
      },
      {
        path: 'feedback',
        loadComponent: () =>
          import('./features/feedback/validations-page.component').then(
            (m) => m.ValidationsPageComponent
          )
      },
      {
        path: 'assignments',
        loadComponent: () =>
          import('./features/assignments/assignments-page.component').then(
            (m) => m.AssignmentsPageComponent
          )
      },
      {
        path: 'audit',
        loadComponent: () =>
          import('./features/audit/audit-page.component').then((m) => m.AuditPageComponent)
      },
      {
        path: 'administration',
        loadComponent: () =>
          import('./features/administration/administration-page.component').then(
            (m) => m.AdministrationPageComponent
          )
      }
    ]
  },
  { path: '**', redirectTo: '' }
];
