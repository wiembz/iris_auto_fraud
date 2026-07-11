import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AuthService } from '../../core/auth/auth.service';
import { IrisRole } from '../../core/models/user-role.model';

@Component({
  selector: 'app-login-page',
  imports: [FormsModule, RouterLink],
  templateUrl: './login-page.component.html',
  styleUrl: './login-page.component.scss'
})
export class LoginPageComponent {
  selectedRole: IrisRole = 'gestionnaire';

  constructor(
    private readonly auth: AuthService,
    private readonly router: Router
  ) {}

  signIn(): void {
    const user = this.auth.signIn(this.selectedRole);
    void this.router.navigateByUrl(this.auth.homeRouteFor(user.role));
  }
}
