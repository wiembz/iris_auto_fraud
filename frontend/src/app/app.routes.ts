import { Routes } from '@angular/router';
import { LoginPageComponent } from './features/auth/login-page.component';
import { ClaimDetailPageComponent } from './features/claim-detail/claim-detail-page.component';
import { AppPlaceholderPageComponent } from './features/dashboard/app-placeholder-page.component';
import { DashboardPageComponent } from './features/dashboard/dashboard-page.component';
import { LandingPageComponent } from './features/landing/landing-page.component';
import { WorklistPageComponent } from './features/worklist/worklist-page.component';
import { AppLayoutComponent } from './layouts/app-layout/app-layout.component';
import { PublicLayoutComponent } from './layouts/public-layout/public-layout.component';
import { authGuard } from './core/guards/auth.guard';

export const routes: Routes = [
  {
    path: '',
    component: PublicLayoutComponent,
    children: [
      { path: '', component: LandingPageComponent },
      { path: 'login', component: LoginPageComponent }
    ]
  },
  {
    path: 'app',
    component: AppLayoutComponent,
    canActivate: [authGuard],
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
      { path: 'dashboard', component: DashboardPageComponent },
      { path: 'claims', component: WorklistPageComponent },
      { path: 'claims/:claimRootId', component: ClaimDetailPageComponent },
      {
        path: 'vehicle',
        component: AppPlaceholderPageComponent,
        data: { title: 'Vehicule et VHS' }
      },
      {
        path: 'signals',
        component: AppPlaceholderPageComponent,
        data: { title: 'Signaux et explications' }
      },
      {
        path: 'checklist',
        component: AppPlaceholderPageComponent,
        data: { title: 'Checklist' }
      },
      {
        path: 'feedback',
        component: AppPlaceholderPageComponent,
        data: { title: 'Validation metier' }
      },
      {
        path: 'assignments',
        component: AppPlaceholderPageComponent,
        data: { title: 'Affectations' }
      },
      {
        path: 'audit',
        component: AppPlaceholderPageComponent,
        data: { title: 'Audit' }
      },
      {
        path: 'administration',
        component: AppPlaceholderPageComponent,
        data: { title: 'Administration' }
      }
    ]
  },
  { path: '**', redirectTo: '' }
];
