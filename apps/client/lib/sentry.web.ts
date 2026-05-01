/**
 * Web Sentry stub (Phase 8a).
 *
 * Web does NOT use Sentry — uncaught errors and Web Vitals already flow
 * through `/v1/telemetry/error` (see `telemetry.web.ts`), and adding a
 * third-party SDK to the web bundle would inflate ship size for no
 * incremental signal. The native variant (`sentry.native.ts`) ships the
 * real `@sentry/react-native` integration.
 *
 * Keeping the same surface here lets `_layout.tsx` call `initSentry()`
 * unconditionally without a `Platform.OS` guard at the call site —
 * Metro picks the right module at bundle time.
 */

export function initSentry(): void {
  // No-op on web. See module docstring.
}

export function captureError(_name: string, _err: unknown): void {
  // No-op — web routes errors through `telemetry.web.ts`.
}

export function captureMetric(
  _name: string,
  _value: number,
  _extra?: Record<string, string | number | boolean | null>,
): void {
  // No-op — web routes metrics through `telemetry.web.ts`.
}
