import { HttpInterceptorFn } from '@angular/common/http';

export const readonlyApiInterceptor: HttpInterceptorFn = (request, next) => {
  return next(request.clone({
    setHeaders: {
      'X-IRIS-Client-Mode': 'read-only'
    }
  }));
};
