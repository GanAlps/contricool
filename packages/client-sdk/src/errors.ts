/**
 * Phase 2c error envelope mirrored as a typed error class so screens
 * can `try/catch` the SDK uniformly.
 */

export type ApiErrorDetail = { field: string; issue: string };

export type ApiError = {
  code: string;
  message: string;
  request_id: string | null;
  details: ApiErrorDetail[];
  retry_after?: number;
  http_status: number;
};

export class ApiErrorException extends Error {
  readonly error: ApiError;
  constructor(error: ApiError) {
    super(`${error.code}: ${error.message}`);
    this.name = 'ApiErrorException';
    this.error = error;
  }
}

/**
 * Parse a non-2xx Response body into an `ApiError`.
 *
 * - Phase 2c envelopes (`{ error: { code, message, ... } }`) are
 *   preserved field-for-field.
 * - Anything else (raw HTML, empty body, malformed JSON) collapses to
 *   `code='NETWORK_ERROR'` so the screen layer never sees `undefined`.
 */
export async function parseError(res: Response): Promise<ApiError> {
  let bodyText = '';
  try {
    bodyText = await res.clone().text();
  } catch {
    bodyText = '';
  }
  if (bodyText) {
    try {
      const parsed = JSON.parse(bodyText) as { error?: Partial<ApiError> };
      const e = parsed.error;
      if (e && typeof e.code === 'string' && typeof e.message === 'string') {
        return {
          code: e.code,
          message: e.message,
          request_id: e.request_id ?? null,
          details: e.details ?? [],
          ...(e.retry_after !== undefined ? { retry_after: e.retry_after } : {}),
          http_status: res.status,
        };
      }
    } catch {
      // fall through to NETWORK_ERROR synth
    }
  }
  return {
    code: 'NETWORK_ERROR',
    message: `Request failed with status ${res.status}`,
    request_id: null,
    details: [],
    http_status: res.status,
  };
}
