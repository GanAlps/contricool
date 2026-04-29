import { describe, expect, it } from 'vitest';

import type { ApiError } from '~/lib/api';
import { mapApiError } from '~/lib/error-mapping';

function err(partial: Partial<ApiError>): ApiError {
  return {
    code: 'X',
    message: 'fallback',
    request_id: 'r',
    details: [],
    http_status: 400,
    ...partial,
  };
}

describe('mapApiError', () => {
  it('maps RATE_LIMITED to a toast and propagates retry_after', () => {
    const r = mapApiError(err({ code: 'RATE_LIMITED', http_status: 429, retry_after: 60 }));
    expect(r).toMatchObject({ kind: 'toast', retryAfter: 60 });
  });

  it('uses friendly copy for known banner codes', () => {
    const r = mapApiError(err({ code: 'INVALID_CREDENTIALS', http_status: 401 }), {
      INVALID_CREDENTIALS: 'Email or password is incorrect.',
    });
    expect(r).toEqual({
      kind: 'banner',
      message: 'Email or password is incorrect.',
    });
  });

  it('falls back to err.message for unknown codes', () => {
    const r = mapApiError(err({ code: 'WEIRD', message: 'specific msg' }));
    expect(r).toEqual({ kind: 'banner', message: 'specific msg' });
  });

  it('returns field errors for VALIDATION_ERROR with details', () => {
    const r = mapApiError(
      err({
        code: 'VALIDATION_ERROR',
        http_status: 422,
        details: [
          { field: 'email', issue: 'invalid' },
          { field: 'password', issue: 'too short' },
        ],
      }),
    );
    expect(r).toEqual({
      kind: 'fields',
      errors: [
        { field: 'email', message: 'invalid' },
        { field: 'password', message: 'too short' },
      ],
    });
  });

  it('returns field errors for INVALID_PASSWORD with details', () => {
    const r = mapApiError(
      err({
        code: 'INVALID_PASSWORD',
        http_status: 422,
        details: [{ field: 'password', issue: 'weak' }],
      }),
    );
    expect(r).toEqual({
      kind: 'fields',
      errors: [{ field: 'password', message: 'weak' }],
    });
  });

  it('returns banner for INVALID_PASSWORD without details', () => {
    const r = mapApiError(err({ code: 'INVALID_PASSWORD', http_status: 422 }));
    expect(r.kind).toBe('banner');
  });

  it('returns generic toast for 5xx', () => {
    const r = mapApiError(err({ code: 'INTERNAL', http_status: 500 }));
    expect(r).toEqual({ kind: 'toast', message: 'Something went wrong. Please try again.' });
  });

  it('returns generic toast for NETWORK_ERROR', () => {
    const r = mapApiError(err({ code: 'NETWORK_ERROR', http_status: 0 }));
    expect(r.kind).toBe('toast');
  });

  it('uses friendly copy for RATE_LIMITED when provided', () => {
    const r = mapApiError(err({ code: 'RATE_LIMITED', http_status: 429 }), {
      RATE_LIMITED: 'Slow down, partner.',
    });
    expect(r).toMatchObject({ kind: 'toast', message: 'Slow down, partner.' });
  });

  it('uses friendly copy for NETWORK_ERROR / 5xx when provided', () => {
    const r = mapApiError(err({ code: 'INTERNAL', http_status: 500 }), {
      INTERNAL: 'Server is having a moment.',
    });
    expect(r).toMatchObject({ kind: 'toast', message: 'Server is having a moment.' });
  });
});
