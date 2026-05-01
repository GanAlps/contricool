/**
 * Web telemetry client (Phase 8a — split out of `telemetry.ts`).
 *
 * Posts uncaught errors and Web Vitals to the backend
 * `/v1/telemetry/error` sink. The route is public (no auth needed)
 * so a logged-out error-boundary capture still lands.
 *
 * Native uses `telemetry.native.ts` which forwards to Sentry directly
 * (symbolicated stacks + native crash capture, neither of which the
 * backend sink provides).
 *
 * The client deliberately:
 *   - does not import the SDK (the SDK injects an Authorization
 *     header which is never useful here, and importing it from this
 *     module would be a layering violation since this is loaded by
 *     the root layout before auth bootstraps);
 *   - swallows all errors — telemetry that fails to post must not
 *     itself produce more errors;
 *   - rate-limits client-side at one event per 200 ms per (level, name)
 *     so a tight loop of the same error doesn't spam the sink.
 */

import { redact } from './pii-denylist';

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

function getBaseUrl(): string {
  // Mirrors lib/api: defaults to '/v1' (same-origin via CloudFront).
  return process.env.EXPO_PUBLIC_API_BASE_URL ?? '/v1';
}

export async function postTelemetry(payload: TelemetryPayload): Promise<void> {
  if (!shouldEmit(payload.level, payload.name)) {
    return;
  }
  const body: TelemetryPayload = redact({
    ...payload,
    url: payload.url ?? (typeof window !== 'undefined' ? window.location.href : ''),
    user_agent: payload.user_agent ?? (typeof navigator !== 'undefined' ? navigator.userAgent : ''),
  });
  try {
    const url = `${getBaseUrl()}/telemetry/error`;
    // ``keepalive: true`` lets the request continue after a page
    // unload, which is the common case for "user just hit a crash
    // and refreshed."
    await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
      keepalive: true,
    });
  } catch {
    // Never re-throw from telemetry; a failure here is not actionable
    // by the user and would just amplify the noise.
  }
}

/** Convenience wrapper for the frontend error boundary path. */
export function reportError(name: string, err: unknown): void {
  const message = err instanceof Error ? err.message : typeof err === 'string' ? err : 'unknown';
  const stack = err instanceof Error && err.stack ? err.stack : '';
  void postTelemetry({ level: 'error', name, message, stack });
}

/** Convenience wrapper for Web Vitals. */
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
