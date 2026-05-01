/**
 * Native Sentry integration (Phase 8a).
 *
 * Initializes `@sentry/react-native` and exposes the same surface as
 * `sentry.web.ts` (which is a no-op). Web continues to flow errors via
 * `/v1/telemetry/error`; native goes direct to Sentry so we get
 * symbolicated stacks, native crash capture (Java/Kotlin/Obj-C/Swift),
 * and offline buffering — none of which our backend telemetry sink
 * provides.
 *
 * PII safety (RED LINE 1): every event runs through the same denylist
 * scrubber as `telemetry.ts` before leaving the device. The scrubber
 * walks the event payload (`extra`, `contexts`, `breadcrumbs`,
 * `request`) and redacts whole-fragment matches on the project's
 * canonical denylist (`pii-denylist.ts`).
 *
 * DSN is injected at build time via `EXPO_PUBLIC_SENTRY_DSN`. If the
 * env var is unset, `initSentry()` is a no-op — local dev builds don't
 * need to ship events.
 */

import * as Sentry from '@sentry/react-native';

import { redact } from './pii-denylist';

let initialized = false;

function getDsn(): string | undefined {
  const dsn = process.env.EXPO_PUBLIC_SENTRY_DSN;
  return dsn && dsn.length > 0 ? dsn : undefined;
}

function getRelease(): string | undefined {
  // EAS Build injects the runtime version + build number via these
  // env vars; falling back to undefined lets Sentry use the
  // bundle's auto-detected release.
  return process.env.EXPO_PUBLIC_RELEASE;
}

function getDist(): string | undefined {
  return process.env.EXPO_PUBLIC_DIST;
}

function getEnvironment(): string {
  return process.env.EXPO_PUBLIC_ENV ?? 'development';
}

/**
 * Best-effort PII scrubber for Sentry events. Runs in `beforeSend` so
 * it intercepts the event between capture and network send. Errors
 * inside the scrubber must never throw — Sentry would drop the event
 * AND we'd lose the original error context.
 */
export function scrubEvent<E extends Sentry.Event>(event: E): E {
  try {
    if (event.extra) {
      event.extra = redact(event.extra) as typeof event.extra;
    }
    if (event.contexts) {
      event.contexts = redact(event.contexts) as typeof event.contexts;
    }
    if (event.tags) {
      event.tags = redact(event.tags) as typeof event.tags;
    }
    if (event.request) {
      event.request = redact(event.request) as typeof event.request;
    }
    if (event.user) {
      // RED LINE 1: never ship email / username. Keep the opaque id only.
      const { id } = event.user;
      event.user = id ? { id } : {};
    }
    if (event.breadcrumbs) {
      event.breadcrumbs = event.breadcrumbs.map((b: Sentry.Breadcrumb) => ({
        ...b,
        ...(b.data ? { data: redact(b.data) as typeof b.data } : {}),
      }));
    }
  } catch {
    // Scrubber failures must not drop the event — better to ship a
    // possibly-unscrubbed event than to lose error visibility.
  }
  return event;
}

export function initSentry(): void {
  if (initialized) {
    return;
  }
  const dsn = getDsn();
  if (!dsn) {
    // No DSN → local dev / preview build with telemetry intentionally
    // off. Leave `initialized` false so capture* calls also short-circuit.
    return;
  }
  const release = getRelease();
  const dist = getDist();
  Sentry.init({
    dsn,
    environment: getEnvironment(),
    ...(release ? { release } : {}),
    ...(dist ? { dist } : {}),
    // Performance / replay are off at MVP — crash + error reporting only.
    tracesSampleRate: 0,
    enableAutoPerformanceTracing: false,
    // Send default PII is OFF; the scrubber below is the second line.
    sendDefaultPii: false,
    beforeSend: scrubEvent,
  });
  initialized = true;
}

export function captureError(name: string, err: unknown): void {
  if (!initialized) {
    return;
  }
  const error = err instanceof Error ? err : new Error(typeof err === 'string' ? err : 'unknown');
  Sentry.captureException(error, { tags: { name } });
}

export function captureMetric(
  name: string,
  value: number,
  extra?: Record<string, string | number | boolean | null>,
): void {
  if (!initialized) {
    return;
  }
  Sentry.captureMessage(name, {
    level: 'info',
    extra: { value, ...(extra ?? {}) },
  });
}

/** Test-only: reset the init guard so multiple init() calls can be exercised. */
export function _resetSentryForTests(): void {
  initialized = false;
}
