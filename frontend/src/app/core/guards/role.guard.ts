import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../auth/auth.service';
import { IrisRole } from '../models/user-role.model';

/**
 * Blocks a route unless the signed-in user's role is in route.data['roles'].
 * Without this, the "roles" arrays in app-layout's navItems only hid the
 * sidebar link -- anyone authenticated could still open any /app/* URL
 * directly (e.g. an analyste typing /app/administration in the address bar).
 * A mismatch redirects to the user's own home route instead of a blank page.
 */
export const roleGuard: CanActivateFn = (route) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const allowedRoles = route.data['roles'] as IrisRole[] | undefined;
  const user = auth.currentUser();

  if (!user) {
    return router.createUrlTree(['/login']);
  }
  if (!allowedRoles || allowedRoles.includes(user.role)) {
    return true;
  }
  return router.createUrlTree([auth.homeRouteFor(user.role)]);
};
