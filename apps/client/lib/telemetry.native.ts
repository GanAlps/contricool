/**
 * Native telemetry client (Phase 8a).
 *
 * Forwards errors and metrics to Sentry instead of the backend
 * `/v1/telemetry/error` sink. Why split:
 *   - Sentry symbolicates RN/Hermes stacks via uploaded source maps,
 *     and captures native (Java/Kotlin/Obj-C/Swift) crashes that JS
 *     telemetry can't see.
 *   - Sentry buffers offline events and ships when connectivity
 *     returns — important on mobile where network is flaky.
 *   - Web continues on the backend sink; we don't want to inflate the
 *     web bundle with a third-party SDK we already don't need there.
 *
 * The public surface (`postTelemetry`, `reportError`, `reportMetric`,
 * `_resetTelemetryForTests`) mirrors `telemetry.web.ts` so call sites
 * (ErrorBoundary, web-vitals.ts) work unchanged via Metro's platform
 * resolver.
 *
 * Same dedup window (200 ms per level+name) as web — Sentry already
 * does its own dedup at the SDK level, but the client-side gate keeps
 * a tight error loop from hammering the wire.
 */

import { captureError, captureMetric } from '~/lib/sentry';

type TelemetryLevel = 'error' | 'metric';

type TelemetryPayload = {
  level: TelemetryLevel;
  name: string;
  message?: string;
  stack?: string;
  url?: string;
  user_agent?: string;
  value?: number;
  extra?: Record<string, string | number | boolean | null>;
};

const DEDUP_MS = 200;
const lastSeenAt = new Map<string, number>();

function dedupKey(level: TelemetryLevel, name: string): string {
  return `${level}:${name}`;
}

function shouldEmit(level: TelemetryLevel, name: string): boolean {
  const key = dedupKey(level, name);
  const now = Date.now();
  const last = lastSeenAt.get(key);
  if (last !== undefined && now - last < DEDUP_MS) {
    return false;
  }
  lastSeenAt.set(key, now);
  return true;
}

export async function postTelemetry(payload: TelemetryPayload): Promise<void> {
  if (!shouldEmit(payload.level, payload.name)) {
    return;
  }
  try {
    if (payload.level === 'error') {
      // Reconstruct an Error so Sentry's stack symbolication kicks in.
      // The PII scrubber in `sentry.native.ts` runs in beforeSend.
      const err = new Error(payload.message ?? payload.name);
      if (payload.stack) {
        err.stack = payload.stack;
      }
      captureError(payload.name, err);
    } else {
      captureMetric(payload.name, payload.value ?? 0, payload.extra);
    }
  } catch {
    // Telemetry must never re-throw; a Sentry init failure should not
    // crash the screen that reported the error.
  }
}

/** Convenience wrapper for the frontend error boundary path. */
export function reportError(name: string, err: unknown): void {
  const message = err instanceof Error ? err.message : typeof err === 'string' ? err : 'unknown';
  const stack = err instanceof Error && err.stack ? err.stack : '';
  void postTelemetry({ level: 'error', name, message, stack });
}

/** Convenience wrapper for runtime metrics (kept for parity with web). */
export function reportMetric(
  name: string,
  value: number,
  extra?: Record<string, string | number | boolean | null>,
): void {
  void postTelemetry({
    level: 'metric',
    name,
    value,
    ...(extra ? { extra } : {}),
  });
}

/** Test-only: clear the dedup cache so unit tests can replay events. */
export function _resetTelemetryForTests(): void {
  lastSeenAt.clear();
}
