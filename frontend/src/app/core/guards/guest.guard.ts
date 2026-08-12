import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../auth/auth.service';

/** Sends an already-authenticated user straight to their space instead of showing the login form again. */
export const guestGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const user = auth.currentUser();

  if (user) {
    return router.createUrlTree([auth.homeRouteFor(user.role)]);
  }
  return true;
};
