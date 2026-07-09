/** Runtime config accessor. Reads `window.STP_CONFIG`, which nginx fills in at
 *  serve time from env vars (see docker/nginx.conf.template). Falls back to
 *  empty strings when the config script is absent (e.g. `ng serve` without
 *  nginx). Callers treat empty values as "feature off". */
import { Injectable } from '@angular/core';

export interface RuntimeConfig {
  backendUrl?: string;
  grafanaUrl?: string;
  sentryDsn?: string;
  sentryEnvironment?: string;
  release?: string;
}

@Injectable({ providedIn: 'root' })
export class ConfigService {
  private get cfg(): RuntimeConfig {
    return (window as unknown as { STP_CONFIG?: RuntimeConfig }).STP_CONFIG ?? {};
  }

  get backendUrl(): string { return this.cfg.backendUrl ?? ''; }
  get grafanaUrl(): string { return this.cfg.grafanaUrl ?? ''; }
  get sentryDsn(): string { return this.cfg.sentryDsn ?? ''; }
  get sentryEnvironment(): string { return this.cfg.sentryEnvironment ?? 'development'; }
  get release(): string { return this.cfg.release ?? ''; }
}
