/** ConfigService + runtimeValue — BUG-004 regression cover.
 *
 * The bug: NGINX_ENVSUBST_FILTER did not list SENTRY_DSN, so nginx served the SPA
 * the LITERAL string `${SENTRY_DSN}`. Sentry.init() doesn't throw on a malformed
 * DSN, it just no-ops — so frontend Sentry looked configured and reported nothing.
 *
 * These specs pin the three branches that matter: value set, value unset, and
 * value still an unsubstituted placeholder.
 */
import { TestBed } from '@angular/core/testing';

import { ConfigService } from './config.service';
import { RuntimeConfig, runtimeValue } from '../runtime-config';

function setRuntimeConfig(cfg: RuntimeConfig | undefined): void {
  (window as unknown as { STP_CONFIG?: RuntimeConfig }).STP_CONFIG = cfg;
}

describe('runtimeValue', () => {
  it('passes through a real value', () => {
    expect(runtimeValue('https://abc@o1.ingest.sentry.io/2')).toBe('https://abc@o1.ingest.sentry.io/2');
  });

  it('treats an unsubstituted ${...} placeholder as unset (BUG-004)', () => {
    expect(runtimeValue('${SENTRY_DSN}')).toBe('');
    expect(runtimeValue('${GRAFANA_URL}')).toBe('');
  });

  it('treats empty / whitespace / null / undefined as unset', () => {
    expect(runtimeValue('')).toBe('');
    expect(runtimeValue('   ')).toBe('');
    expect(runtimeValue(null)).toBe('');
    expect(runtimeValue(undefined)).toBe('');
  });
});

describe('ConfigService', () => {
  let service: ConfigService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(ConfigService);
  });

  afterEach(() => setRuntimeConfig(undefined));

  it('reads substituted values', () => {
    setRuntimeConfig({
      backendUrl: 'https://api.example.test',
      grafanaUrl: 'https://grafana.example.test',
      sentryDsn: 'https://abc@o1.ingest.sentry.io/2',
      sentryEnvironment: 'staging',
      release: 'deadbee',
    });

    expect(service.backendUrl).toBe('https://api.example.test');
    expect(service.grafanaUrl).toBe('https://grafana.example.test');
    expect(service.sentryDsn).toBe('https://abc@o1.ingest.sentry.io/2');
    expect(service.sentryEnvironment).toBe('staging');
    expect(service.release).toBe('deadbee');
  });

  it('reports Sentry as OFF when the DSN is an unsubstituted placeholder (BUG-004)', () => {
    setRuntimeConfig({
      backendUrl: 'https://api.example.test', // this one WAS in the filter
      grafanaUrl: '${GRAFANA_URL}',
      sentryDsn: '${SENTRY_DSN}',
      sentryEnvironment: '${SENTRY_ENVIRONMENT}',
      release: '${RELEASE}',
    });

    // The whole point: a filter regression must degrade to "feature off",
    // never to "Sentry initialised with a junk DSN".
    expect(service.sentryDsn).toBe('');
    expect(service.grafanaUrl).toBe('');
    expect(service.release).toBe('');
    expect(service.sentryEnvironment).toBe('development'); // falls back to the default
    expect(service.backendUrl).toBe('https://api.example.test');
  });

  it('falls back cleanly when STP_CONFIG is absent (ng serve, no nginx)', () => {
    setRuntimeConfig(undefined);

    expect(service.backendUrl).toBe('');
    expect(service.sentryDsn).toBe('');
    expect(service.sentryEnvironment).toBe('development');
  });
});
