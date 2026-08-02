import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../auth/auth.service';

/**
 * Resolves the bare "/app" path to the signed-in user's actual home route
 * instead of a hardcoded redirectTo: 'dashboard' -- the dashboard is
 * responsable/administrateur only, so an analyste hitting "/app" used to be
 * bounced into a page not meant for them (before roleGuard also caught it).
 */
export const homeRedirectGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const user = auth.currentUser();

  if (!user) {
    return router.createUrlTree(['/login']);
  }
  return router.createUrlTree([auth.homeRouteFor(user.role)]);
};
