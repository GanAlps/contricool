/**
 * Web Vitals reporter (web-only).
 *
 * Posts the four Core Web Vitals (LCP, INP, CLS, FCP) plus TTFB to
 * the telemetry sink as ``level=metric`` events.
 *
 * Previously this lived at `lib/web-vitals.ts` and gated the
 * `web-vitals` import behind a runtime `await import(...)` to keep
 * the package out of the native bundle. That broke EAS local
 * Android builds: Metro statically analyzes dynamic imports and
 * tries to resolve `metro-runtime/asyncRequire.js`, which fails
 * when EAS's two-stage temp dirs (`eas-build-local-nodejs/<UUID-A>/...`
 * vs `<UUID-B>/...`) cross-contaminate with pnpm's hash-dir layout.
 *
 * Switching to Metro's `.web.ts` platform suffix bypasses that
 * entirely — the file doesn't exist for native bundlers, so
 * `web-vitals` is never resolved on Android/iOS. The matching
 * `web-vitals.native.ts` is a no-op stub so call sites stay clean.
 */

import { reportMetric } from '~/lib/telemetry';

type MetricLike = {
  name: string;
  value: number;
  id?: string;
  rating?: 'good' | 'needs-improvement' | 'poor';
  navigationType?: string;
};

let installed = false;

/**
 * Install the Web Vitals reporters. Idempotent. No-op on native /
 * SSR / when ``web-vitals`` isn't available.
 */
export async function reportWebVitals(): Promise<void> {
  if (installed || typeof window === 'undefined') {
    return;
  }
  installed = true;
  try {
    const wv = (await import('web-vitals')) as {
      onLCP?: (cb: (m: MetricLike) => void) => void;
      onINP?: (cb: (m: MetricLike) => void) => void;
      onCLS?: (cb: (m: MetricLike) => void) => void;
      onFCP?: (cb: (m: MetricLike) => void) => void;
      onTTFB?: (cb: (m: MetricLike) => void) => void;
    };

    const send = (m: MetricLike): void => {
      reportMetric(m.name, m.value, {
        rating: m.rating ?? null,
        navigation_type: m.navigationType ?? null,
      });
    };

    wv.onLCP?.(send);
    wv.onINP?.(send);
    wv.onCLS?.(send);
    wv.onFCP?.(send);
    wv.onTTFB?.(send);
  } catch {
    // Optional dep — never break the page if web-vitals isn't there.
  }
}

/** Test-only: reset the once-flag so subsequent tests re-install. */
export function _resetWebVitalsForTests(): void {
  installed = false;
}
