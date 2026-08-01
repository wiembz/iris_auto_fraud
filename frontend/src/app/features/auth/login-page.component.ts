import { Component, signal } from '@angular/core';
import { FormsModule, NgForm } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AuthService, RoleResolutionError } from '../../core/auth/auth.service';
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

  email = '';
  attemptedSubmit = false;
  // Signaux (et non simples champs) : cette appli tourne sans zone.js, donc un
  // etat mis a jour apres un `await` (resolution du role cote backend) ne
  // declenche un rendu que via un signal, pas via une simple mutation de champ.
  readonly signingIn = signal(false);
  readonly roleError = signal<string | null>(null);

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

  async signIn(form: NgForm): Promise<void> {
    this.attemptedSubmit = true;
    this.roleError.set(null);
    if (form.invalid || !this.isBnaEmail) {
      form.control.markAllAsTouched();
      return;
    }

    this.signingIn.set(true);
    try {
      const user = await this.auth.signIn(this.normalizedEmail);
      void this.router.navigateByUrl(this.auth.homeRouteFor(user.role));
    } catch (error) {
      this.roleError.set(
        error instanceof RoleResolutionError
          ? error.message
          : "Impossible de verifier cette adresse email pour le moment."
      );
    } finally {
      this.signingIn.set(false);
    }
  }
}
