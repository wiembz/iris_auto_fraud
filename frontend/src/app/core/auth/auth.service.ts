import { Injectable, signal } from '@angular/core';
import {
  IRIS_ROLE_HOME_ROUTE,
  IRIS_ROLE_LABELS,
  IrisRole,
  IrisUserContext
} from '../models/user-role.model';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly userSignal = signal<IrisUserContext | null>(null);
  readonly currentUser = this.userSignal.asReadonly();

  signIn(role: IrisRole): IrisUserContext {
    const user: IrisUserContext = {
      displayName: 'Utilisateur IRIS',
      role,
      roleLabel: IRIS_ROLE_LABELS[role]
    };
    this.userSignal.set(user);
    return user;
  }

  signOut(): void {
    this.userSignal.set(null);
  }

  isAuthenticated(): boolean {
    return this.userSignal() !== null;
  }

  homeRouteFor(role: IrisRole): string {
    return IRIS_ROLE_HOME_ROUTE[role];
  }
}
