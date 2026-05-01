/**
 * PII denylist + redactor for client-side telemetry.
 *
 * The set is the client mirror of `apps/api/app/core/observability.py`:
 * the same keys that the backend Logger redacts must be redacted on
 * the client before any payload leaves the device. This module is the
 * single source of truth on the client; Sentry's `beforeSend` and any
 * future error-reporting transport call `redact` before sending.
 *
 * Matching is whole-fragment, case-insensitive — `userEmail`,
 * `user_email`, `user-email`, and `UserEmail` all redact. Compound
 * keys (`credit_card`, `card_number`) are normalised separately so
 * generic words like `card` don't over-redact `discount_card`.
 *
 * Performance: redaction allocates a new object tree, so callers
 * should avoid running it on hot paths. Telemetry events are the only
 * intended caller and they're rate-limited upstream.
 */

export const DENY_KEYS: ReadonlySet<string> = new Set([
  'email',
  'phone',
  'password',
  'otp',
  'authorization',
  'cookie',
  'secret',
  'token',
  'ssn',
  'salt',
]);

export const DENY_COMPOUND_KEYS: ReadonlySet<string> = new Set([
  'credit_card',
  'credit_card_number',
  'card_number',
  'cc_number',
  'ccn',
]);

export const REDACTED = '[REDACTED]';

const SPLIT_RE = /[_\-\s]|(?<=[a-z])(?=[A-Z])/;
const NORMALISE_RE = /[\-\s]+/g;

function normaliseCompound(key: string): string {
  // Insert `_` at CamelCase boundaries, collapse other separators, lowercase.
  const camelled = key.replace(/(?<=[a-z])(?=[A-Z])/g, '_');
  return camelled.replace(NORMALISE_RE, '_').toLowerCase();
}

export function isSensitiveKey(key: unknown): boolean {
  if (typeof key !== 'string') {
    return false;
  }
  if (DENY_COMPOUND_KEYS.has(normaliseCompound(key))) {
    return true;
  }
  for (const frag of key.split(SPLIT_RE)) {
    if (frag && DENY_KEYS.has(frag.toLowerCase())) {
      return true;
    }
  }
  return false;
}

/**
 * Returns a deep copy of `value` with any object key whose name
 * matches `isSensitiveKey` mapped to `[REDACTED]`. Arrays and nested
 * objects are walked. Primitives are returned unchanged. Cycles are
 * not handled — telemetry payloads should never be cyclic; if one
 * arrives, the redactor will throw, which is the right failure mode
 * for a malformed event.
 */
export function redact<T>(value: T): T {
  if (value === null || typeof value !== 'object') {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => redact(item)) as unknown as T;
  }
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    out[k] = isSensitiveKey(k) ? REDACTED : redact(v);
  }
  return out as T;
}
