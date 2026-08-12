import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import {
  IRIS_ROLE_HOME_ROUTE,
  IRIS_ROLE_LABELS,
  IrisRole,
  IrisUserContext
} from '../models/user-role.model';
import { API_BASE_URL } from '../config/api.config';

const SESSION_KEY = 'iris.session.v1';

interface ResolveRoleResponse {
  email: string;
  role: IrisRole;
}

/** Thrown when the backend rejects the email (unknown, wrong domain, or bad role config). */
export class RoleResolutionError extends Error {}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly apiBaseUrl = API_BASE_URL;
  private readonly userSignal = signal<IrisUserContext | null>(restoreSession());
  readonly currentUser = this.userSignal.asReadonly();

  /**
   * Resolves the role for this email server-side (backend/services/auth_service.py) and
   * opens the session. The frontend can no longer decide its own role.
   */
  async signIn(email: string): Promise<IrisUserContext> {
    let resolved: ResolveRoleResponse;
    try {
      resolved = await firstValueFrom(
        this.http.post<ResolveRoleResponse>(`${this.apiBaseUrl}/auth/resolve-role`, { email })
      );
    } catch (error: any) {
      const message = error?.error?.message ?? "Impossible de verifier cette adresse email.";
      throw new RoleResolutionError(message);
    }

    const displayName = this.displayNameFromEmail(resolved.email);
    const user: IrisUserContext = {
      displayName,
      email: resolved.email,
      role: resolved.role,
      roleLabel: IRIS_ROLE_LABELS[resolved.role]
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
