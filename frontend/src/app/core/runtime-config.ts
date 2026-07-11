/** Runtime config injected by nginx at serve time (see docker/nginx.conf.template).
 *
 * Defense in depth for BUG-004.
 *
 * nginx substitutes only the vars listed in NGINX_ENVSUBST_FILTER. A var missing
 * from that allowlist is NOT substituted, and its literal text — `${SENTRY_DSN}` —
 * is served to the browser. That is not hypothetical: it is exactly what shipped,
 * and `Sentry.init({ dsn: '${SENTRY_DSN}' })` does not throw on a malformed DSN,
 * it just silently becomes a no-op. The result was a Sentry integration that
 * looked wired up and reported nothing.
 *
 * `runtimeValue()` therefore treats a value that is empty OR still looks like an
 * unsubstituted placeholder as **unset**. A filter regression then degrades to
 * "feature off" (honest, and the CI guard in scripts/check_envsubst_filter.py
 * will fail the build) rather than "feature silently broken".
 */

export interface RuntimeConfig {
  backendUrl?: string;
  grafanaUrl?: string;
  sentryDsn?: string;
  sentryEnvironment?: string;
  release?: string;
}

/** Normalize a runtime-config value: empty or `${...}` placeholder -> ''. */
export function runtimeValue(raw: string | undefined | null): string {
  const value = (raw ?? '').trim();
  if (!value || value.startsWith('${')) {
    return '';
  }
  return value;
}

/** Read `window.STP_CONFIG`, defaulting to {} when the config script is absent
 *  (e.g. `ng serve` with no nginx in front). */
export function readRuntimeConfig(): RuntimeConfig {
  return (window as unknown as { STP_CONFIG?: RuntimeConfig }).STP_CONFIG ?? {};
}
