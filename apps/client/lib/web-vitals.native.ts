/**
 * Web Vitals on native — no-op.
 *
 * Core Web Vitals are browser metrics (LCP / INP / CLS / FCP / TTFB
 * are all measured against page paint and layout shift). They have
 * no equivalent on native and the `web-vitals` npm package depends
 * on browser-only globals.
 *
 * This stub exists so `_layout.tsx` can call `reportWebVitals()`
 * unconditionally — Metro's platform suffix resolver picks this
 * file for Android / iOS bundles, the matching `.web.ts` for web.
 */

export async function reportWebVitals(): Promise<void> {
  // Intentionally empty.
}

/** Test-only: parity with the web variant so cross-platform tests don't branch. */
export function _resetWebVitalsForTests(): void {
  // Intentionally empty.
}
