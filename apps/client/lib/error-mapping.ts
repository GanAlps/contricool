import type { ApiError } from './api';

export type ScreenError =
  | { kind: 'fields'; errors: { field: string; message: string }[] }
  | { kind: 'banner'; message: string }
  | { kind: 'toast'; message: string; retryAfter?: number };

export type FriendlyMap = Partial<Record<string, string>>;

/**
 * Map an ApiError onto a tagged union the screen can render.
 *
 * @param friendly per-screen lookup of stable `error.code` → friendly
 *                 banner copy.  Falls back to `err.message` for unknown
 *                 codes.
 */
export function mapApiError(err: ApiError, friendly: FriendlyMap = {}): ScreenError {
  if (err.code === 'RATE_LIMITED') {
    return {
      kind: 'toast',
      message: friendly.RATE_LIMITED ?? 'Too many requests — please wait and try again.',
      ...(err.retry_after !== undefined ? { retryAfter: err.retry_after } : {}),
    };
  }
  if (
    (err.code === 'VALIDATION_ERROR' || err.code === 'INVALID_PASSWORD') &&
    err.details.length > 0
  ) {
    return {
      kind: 'fields',
      errors: err.details.map((d) => ({ field: d.field, message: d.issue })),
    };
  }
  if (err.code === 'NETWORK_ERROR' || err.http_status >= 500) {
    return {
      kind: 'toast',
      message: friendly[err.code] ?? 'Something went wrong. Please try again.',
    };
  }
  return {
    kind: 'banner',
    message: friendly[err.code] ?? err.message,
  };
}
