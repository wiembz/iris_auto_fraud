import { HttpInterceptorFn } from '@angular/common/http';

// La plateforme est en lecture seule sur le DWH/mart : la seule ecriture
// autorisee est la decision humaine (POST /claims/:id/decision), tracee en
// audit trail append-only. Cet en-tete documente cette distinction cote
// backend/logs sans jamais bloquer la requete.
export const readonlyApiInterceptor: HttpInterceptorFn = (request, next) => {
  const mode = request.method === 'GET' ? 'read-only' : 'decision-write';
  return next(request.clone({
    setHeaders: {
      'X-IRIS-Client-Mode': mode
    }
  }));
};
