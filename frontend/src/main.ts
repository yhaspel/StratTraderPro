import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { AppComponent } from './app/app.component';

// Sentry browser SDK. DSN + environment + release come from the runtime config
// nginx injects into `window.STP_CONFIG` (see docker/nginx.conf.template). An
// empty DSN disables Sentry, which is the local-dev / no-nginx default.
import * as Sentry from '@sentry/angular';

const stpConfig = (window as unknown as {
  STP_CONFIG?: { sentryDsn?: string; sentryEnvironment?: string; release?: string };
}).STP_CONFIG ?? {};

Sentry.init({
  dsn: stpConfig.sentryDsn || '', // empty = disabled
  integrations: [Sentry.browserTracingIntegration()],
  tracesSampleRate: 0.1,
  environment: stpConfig.sentryEnvironment || 'development',
  release: stpConfig.release || undefined,
});

bootstrapApplication(AppComponent, appConfig).catch((err) =>
  console.error(err)
);
