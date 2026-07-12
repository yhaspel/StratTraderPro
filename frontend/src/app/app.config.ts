import { ApplicationConfig, APP_INITIALIZER } from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient, withInterceptors, HttpClient } from '@angular/common/http';
import { TranslateModule, TranslateLoader, MissingTranslationHandler } from '@ngx-translate/core';
import { TranslateHttpLoader } from '@ngx-translate/http-loader';
import { importProvidersFrom } from '@angular/core';

import { routes } from './app.routes';
import { authInterceptor } from './core/interceptors/auth.interceptor';
import { refreshInterceptor } from './core/interceptors/refresh.interceptor';
import { errorInterceptor } from './core/interceptors/error.interceptor';
import { AuthFacade } from './abstraction/facades/auth.facade';
import { AppMissingTranslationHandler } from './core/i18n/missing-translation.handler';

export function httpLoaderFactory(http: HttpClient): TranslateHttpLoader {
  return new TranslateHttpLoader(http, './assets/i18n/', '.json');
}

function initAuth(facade: AuthFacade) {
  return () => facade.initSession();
}

export const appConfig: ApplicationConfig = {
  providers: [
    provideRouter(routes),
    provideHttpClient(withInterceptors([authInterceptor, refreshInterceptor, errorInterceptor])),
    importProvidersFrom(
      TranslateModule.forRoot({
        defaultLanguage: 'en',
        useDefaultLang: true,
        missingTranslationHandler: {
          provide: MissingTranslationHandler,
          useClass: AppMissingTranslationHandler,
        },
        loader: {
          provide: TranslateLoader,
          useFactory: httpLoaderFactory,
          deps: [HttpClient],
        },
      })
    ),
    {
      provide: APP_INITIALIZER,
      useFactory: initAuth,
      deps: [AuthFacade],
      multi: true,
    },
  ],
};
