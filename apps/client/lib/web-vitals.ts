/**
 * Web Vitals reporter.
 *
 * Posts the four Core Web Vitals (LCP, INP, CLS, FCP) plus TTFB to
 * the telemetry sink as ``level=metric`` events. The ``web-vitals``
 * package is web-only — on native we no-op.
 *
 * Lazy import: `web-vitals` is only loaded on the web bundle to keep
 * the native bundle lean.
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
    // Dynamic import keeps web-vitals out of the native bundle.
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
