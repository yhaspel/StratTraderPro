import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { AppComponent } from './app/app.component';

// Sentry browser SDK (skeleton — DSN injected at build time)
import * as Sentry from '@sentry/angular';

Sentry.init({
  dsn: '', // Set via environment at build; empty = disabled
  integrations: [Sentry.browserTracingIntegration()],
  tracesSampleRate: 0.1,
  environment: 'development',
});

bootstrapApplication(AppComponent, appConfig).catch((err) =>
  console.error(err)
);
