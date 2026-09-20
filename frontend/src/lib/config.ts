/**
 * Runtime configuration loader.
 *
 * `static/runtime-config.js` (loaded by `src/app.html` BEFORE the app bundle)
 * publishes the dev defaults on `window.__AUTOBREADBOARD_CONFIG__`. In a
 * Kubernetes deploy, the frontend ConfigMap overrides `runtime-config.js`
 * so the browser talks to the Ingress-routed API rather than localhost.
 *
 * The shape of the global is also declared in `src/app.d.ts` so consumers
 * get proper typing without an extra cast.
 */

export interface RuntimeConfig {
  apiBaseUrl: string;
  environment: string;
  buildSha: string;
}

export const FALLBACK_RUNTIME_CONFIG: RuntimeConfig = {
  apiBaseUrl: '/api/v1',
  environment: 'development',
  buildSha: 'dev'
};

export function getRuntimeConfig(): RuntimeConfig {
  if (typeof window === 'undefined') {
    return { ...FALLBACK_RUNTIME_CONFIG };
  }
  const fromGlobal = window.__AUTOBREADBOARD_CONFIG__;
  if (!fromGlobal) {
    return { ...FALLBACK_RUNTIME_CONFIG };
  }
  // Defensive merge: any missing key falls back rather than crashing the app.
  return {
    apiBaseUrl:
      typeof fromGlobal.apiBaseUrl === 'string' && fromGlobal.apiBaseUrl.length > 0
        ? fromGlobal.apiBaseUrl
        : FALLBACK_RUNTIME_CONFIG.apiBaseUrl,
    environment:
      typeof fromGlobal.environment === 'string' && fromGlobal.environment.length > 0
        ? fromGlobal.environment
        : FALLBACK_RUNTIME_CONFIG.environment,
    buildSha:
      typeof fromGlobal.buildSha === 'string' && fromGlobal.buildSha.length > 0
        ? fromGlobal.buildSha
        : FALLBACK_RUNTIME_CONFIG.buildSha
  };
}