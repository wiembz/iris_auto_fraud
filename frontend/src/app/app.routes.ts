import { Routes } from '@angular/router';
import { AppLayoutComponent } from './layouts/app-layout/app-layout.component';
import { PublicLayoutComponent } from './layouts/public-layout/public-layout.component';
import { authGuard } from './core/guards/auth.guard';
import { guestGuard } from './core/guards/guest.guard';
import { homeRedirectGuard } from './core/guards/home-redirect.guard';
import { roleGuard } from './core/guards/role.guard';
import { IRIS_ROUTE_ROLES } from './core/models/user-role.model';

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
        canActivate: [guestGuard],
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
      { path: '', pathMatch: 'full', canActivate: [homeRedirectGuard], children: [] },
      {
        path: 'dashboard',
        canActivate: [roleGuard],
        data: { roles: IRIS_ROUTE_ROLES['dashboard'] },
        loadComponent: () =>
          import('./features/dashboard/dashboard-page/dashboard-page.component').then(
            (m) => m.DashboardPageComponent
          )
      },
      {
        path: 'claims',
        canActivate: [roleGuard],
        data: { roles: IRIS_ROUTE_ROLES['claims'] },
        loadComponent: () =>
          import('./features/worklist/worklist-page/worklist-page.component').then(
            (m) => m.WorklistPageComponent
          )
      },
      {
        path: 'claims/:claimSk',
        canActivate: [roleGuard],
        data: { roles: IRIS_ROUTE_ROLES['claims'] },
        loadComponent: () =>
          import('./features/claim-detail/claim-detail-page.component').then(
            (m) => m.ClaimDetailPageComponent
          )
      },
      {
        path: 'vehicle',
        canActivate: [roleGuard],
        data: { roles: IRIS_ROUTE_ROLES['vehicle'] },
        loadComponent: () =>
          import('./features/vehicle/vhs-page.component').then((m) => m.VhsPageComponent)
      },
      {
        path: 'analytics',
        canActivate: [roleGuard],
        data: { roles: IRIS_ROUTE_ROLES['analytics'] },
        loadComponent: () =>
          import('./features/analytics/analytics-page.component').then(
            (m) => m.AnalyticsPageComponent
          )
      },
      {
        path: 'feedback',
        canActivate: [roleGuard],
        data: { roles: IRIS_ROUTE_ROLES['feedback'] },
        loadComponent: () =>
          import('./features/feedback/validations-page.component').then(
            (m) => m.ValidationsPageComponent
          )
      },
      {
        path: 'assignments',
        canActivate: [roleGuard],
        data: { roles: IRIS_ROUTE_ROLES['assignments'] },
        loadComponent: () =>
          import('./features/assignments/assignments-page.component').then(
            (m) => m.AssignmentsPageComponent
          )
      },
      {
        path: 'audit',
        canActivate: [roleGuard],
        data: { roles: IRIS_ROUTE_ROLES['audit'] },
        loadComponent: () =>
          import('./features/audit/audit-page.component').then((m) => m.AuditPageComponent)
      },
      {
        path: 'administration',
        canActivate: [roleGuard],
        data: { roles: IRIS_ROUTE_ROLES['administration'] },
        loadComponent: () =>
          import('./features/administration/administration-page.component').then(
            (m) => m.AdministrationPageComponent
          )
      }
    ]
  },
  { path: '**', redirectTo: '' }
];
