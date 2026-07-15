import { Component } from '@angular/core';
import { FormsModule, NgForm } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AuthService } from '../../core/auth/auth.service';
import { IRIS_ROLE_LABELS, IrisRole } from '../../core/models/user-role.model';
import { IrisEyeSceneComponent } from '../landing/sections/iris-eye-scene.component';
import { IrisLogoComponent } from '../../shared/ui/iris-logo.component';

@Component({
  selector: 'app-login-page',
  imports: [FormsModule, RouterLink, IrisEyeSceneComponent, IrisLogoComponent],
  templateUrl: './login-page.component.html',
  styleUrl: './login-page.component.scss'
})
export class LoginPageComponent {
  readonly allowedDomain = '@bnaassurance.com';
  readonly roleOptions: Array<{ role: IrisRole; title: string; description: string }> = [
    {
      role: 'gestionnaire',
      title: IRIS_ROLE_LABELS.gestionnaire,
      description: 'Consulter et analyser les dossiers à examiner.'
    },
    {
      role: 'responsable',
      title: IRIS_ROLE_LABELS.responsable,
      description: 'Suivre les volumes et organiser la revue métier.'
    },
    {
      role: 'manager',
      title: IRIS_ROLE_LABELS.manager,
      description: 'Piloter les indicateurs et les validations.'
    },
    {
      role: 'administrateur',
      title: IRIS_ROLE_LABELS.administrateur,
      description: 'Gérer les paramètres de la plateforme.'
    }
  ];

  email = '';
  selectedRole: IrisRole = 'gestionnaire';
  attemptedSubmit = false;

  constructor(
    private readonly auth: AuthService,
    private readonly router: Router
  ) {}

  get normalizedEmail(): string {
    return this.email.trim().toLowerCase();
  }

  get isBnaEmail(): boolean {
    return this.normalizedEmail.endsWith(this.allowedDomain) && this.normalizedEmail.length > this.allowedDomain.length;
  }

  get domainErrorVisible(): boolean {
    return this.attemptedSubmit || this.email.trim().length > 0;
  }

  selectRole(role: IrisRole): void {
    this.selectedRole = role;
  }

  signIn(form: NgForm): void {
    this.attemptedSubmit = true;
    if (form.invalid || !this.isBnaEmail) {
      form.control.markAllAsTouched();
      return;
    }

    const user = this.auth.signIn(this.selectedRole, this.normalizedEmail);
    void this.router.navigateByUrl(this.auth.homeRouteFor(user.role));
  }
}
