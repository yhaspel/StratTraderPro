import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { AppComponent } from './app/app.component';

// Sentry browser SDK. DSN + environment + release come from the runtime config
// nginx injects into `window.STP_CONFIG` (see docker/nginx.conf.template). An
// empty DSN disables Sentry, which is the local-dev / no-nginx default.
//
// BUG-004: values are read through `runtimeValue()`, which treats a leftover
// `${SENTRY_DSN}` placeholder as unset. Sentry.init() does NOT throw on a
// malformed DSN — it silently no-ops — so without this, a missing entry in
// NGINX_ENVSUBST_FILTER produces an integration that looks live and reports
// nothing. Bootstrap runs before DI exists, hence the plain helper rather than
// ConfigService.
import * as Sentry from '@sentry/angular';
import { readRuntimeConfig, runtimeValue } from './app/core/runtime-config';

const stpConfig = readRuntimeConfig();
const sentryDsn = runtimeValue(stpConfig.sentryDsn);

Sentry.init({
  dsn: sentryDsn, // '' = disabled
  integrations: [Sentry.browserTracingIntegration()],
  tracesSampleRate: 0.1,
  environment: runtimeValue(stpConfig.sentryEnvironment) || 'development',
  release: runtimeValue(stpConfig.release) || undefined,
});

bootstrapApplication(AppComponent, appConfig).catch((err) =>
  console.error(err)
);
