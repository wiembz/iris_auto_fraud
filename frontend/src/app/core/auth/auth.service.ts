import { Injectable, signal } from '@angular/core';
import {
  IRIS_ROLE_HOME_ROUTE,
  IRIS_ROLE_LABELS,
  IrisRole,
  IrisUserContext
} from '../models/user-role.model';

const SESSION_KEY = 'iris.session.v1';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly userSignal = signal<IrisUserContext | null>(restoreSession());
  readonly currentUser = this.userSignal.asReadonly();

  signIn(role: IrisRole, email?: string): IrisUserContext {
    const normalizedEmail = email?.trim().toLowerCase();
    const displayName = normalizedEmail ? this.displayNameFromEmail(normalizedEmail) : 'Utilisateur IRIS';
    const user: IrisUserContext = {
      displayName,
      email: normalizedEmail,
      role,
      roleLabel: IRIS_ROLE_LABELS[role]
    };
    this.userSignal.set(user);
    try {
      sessionStorage.setItem(SESSION_KEY, JSON.stringify(user));
    } catch {
      // stockage indisponible : la session reste valable pour l onglet courant
    }
    return user;
  }

  signOut(): void {
    this.userSignal.set(null);
    try {
      sessionStorage.removeItem(SESSION_KEY);
    } catch {
      // rien a nettoyer si le stockage est indisponible
    }
  }

  isAuthenticated(): boolean {
    return this.userSignal() !== null;
  }

  homeRouteFor(role: IrisRole): string {
    return IRIS_ROLE_HOME_ROUTE[role];
  }

  private displayNameFromEmail(email: string): string {
    const localPart = email.split('@')[0] ?? 'utilisateur';
    return localPart
      .split(/[._-]+/)
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ') || 'Utilisateur IRIS';
  }
}

function restoreSession(): IrisUserContext | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as IrisUserContext;
    if (!parsed?.role || !IRIS_ROLE_LABELS[parsed.role]) {
      return null;
    }
    return { ...parsed, roleLabel: IRIS_ROLE_LABELS[parsed.role] };
  } catch {
    return null;
  }
}
