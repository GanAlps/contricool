/**
 * Phase 2d API client.  Thin fetch wrapper for /v1/auth/* with the
 * web 401-refresh-retry-once flow from Design 10.
 *
 * Replaced by the generated `@contricool/client-sdk` in Phase 2e.
 */

import type { ApiErrorDetail, ApiErrorEnvelope } from './types';

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

export type ApiAuthMode = 'bearer' | 'public';

export interface ApiFetchInit extends Omit<RequestInit, 'body'> {
  auth?: ApiAuthMode;
  /** JSON body — stringified automatically. */
  json?: unknown;
  /** Internal: prevents the 401-retry-after-refresh recursion. */
  __noRetry?: boolean;
}

/**
 * Auth-store accessors injected at boot to break the
 * `lib/api.ts` ↔ `lib/auth-store.ts` cycle.
 */
export type ApiAuthAccessors = {
  /** Returns the current access token, or null. */
  getAccessToken(): string | null;
  /** Sets new tokens after a successful refresh. */
  setTokensFromRefresh(args: { access_token: string; id_token: string }): void;
  /** Called when refresh fails — clears the store. */
  forceSignOut(): Promise<void> | void;
};

let accessors: ApiAuthAccessors | null = null;

export function setApiAuthAccessors(a: ApiAuthAccessors | null): void {
  accessors = a;
}

function baseUrl(): string {
  return process.env.EXPO_PUBLIC_API_BASE_URL ?? '/v1';
}

function isAuthBootstrapPath(path: string): boolean {
  return path.startsWith('/auth/');
}

function buildHeaders(init: ApiFetchInit): Headers {
  const h = new Headers(init.headers);
  if (init.json !== undefined && !h.has('content-type')) {
    h.set('content-type', 'application/json');
  }
  if (init.auth !== 'public') {
    const t = accessors?.getAccessToken() ?? null;
    if (t) {
      h.set('authorization', `Bearer ${t}`);
    }
  }
  return h;
}

async function parseError(res: Response): Promise<ApiError> {
  const status = res.status;
  let bodyText = '';
  try {
    bodyText = await res.text();
  } catch {
    bodyText = '';
  }
  if (bodyText) {
    try {
      const parsed = JSON.parse(bodyText) as Partial<ApiErrorEnvelope>;
      const e = parsed.error;
      if (e && typeof e.code === 'string' && typeof e.message === 'string') {
        return {
          code: e.code,
          message: e.message,
          request_id: e.request_id ?? null,
          details: e.details ?? [],
          ...(e.retry_after !== undefined ? { retry_after: e.retry_after } : {}),
          http_status: status,
        };
      }
    } catch {
      // fall through to network-error synth
    }
  }
  return {
    code: 'NETWORK_ERROR',
    message: `Request failed with status ${status}`,
    request_id: null,
    details: [],
    http_status: status,
  };
}

export async function apiFetch<T>(path: string, init: ApiFetchInit = {}): Promise<T> {
  const url = `${baseUrl()}${path}`;
  const headers = buildHeaders(init);
  // Strip the ApiFetchInit-only keys before handing the rest to fetch.
  const { json: _j, auth: _a, __noRetry: _r, ...rest } = init;
  void _j;
  void _a;
  void _r;
  const fetchInit: RequestInit = {
    ...rest,
    headers,
    credentials: 'include',
  };
  if (init.json !== undefined) {
    fetchInit.body = JSON.stringify(init.json);
  }

  const res = await fetch(url, fetchInit);

  if (res.ok) {
    if (res.status === 204) {
      return undefined as T;
    }
    const txt = await res.text();
    if (!txt) {
      return undefined as T;
    }
    return JSON.parse(txt) as T;
  }

  const err = await parseError(res);

  // 401 retry-once: only on protected, non-/auth/* routes when retry is allowed.
  if (
    res.status === 401 &&
    init.auth !== 'public' &&
    !isAuthBootstrapPath(path) &&
    !init.__noRetry &&
    accessors
  ) {
    try {
      const refreshed = await apiFetch<{ access_token: string; id_token: string }>(
        '/auth/refresh',
        { method: 'POST', auth: 'public', __noRetry: true },
      );
      accessors.setTokensFromRefresh(refreshed);
      // Retry original once with __noRetry to prevent recursion.
      return apiFetch<T>(path, { ...init, __noRetry: true });
    } catch {
      // Refresh failed — sign out, surface the original 401.
      try {
        await accessors.forceSignOut();
      } catch {
        // ignore
      }
      throw new ApiErrorException(err);
    }
  }

  throw new ApiErrorException(err);
}
