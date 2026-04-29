import type { Middleware, MiddlewareCallbackParams } from 'openapi-fetch';

import { ApiErrorException, parseError } from './errors';

export type AuthMiddlewareOptions = {
  /** Returns the current access token, or null if signed out. */
  getAccessToken: () => string | null;
  /**
   * Called after a refresh succeeds — the consumer (auth store) can
   * persist the new tokens.
   */
  onTokenRefreshed?: (tokens: { access_token: string; id_token: string }) => void;
  /**
   * Called when the refresh-and-retry flow can't recover — the
   * consumer should clear local auth state.  Errors thrown by this
   * callback are swallowed so the original 401 is still surfaced.
   */
  onUnauthenticated: () => Promise<void> | void;
  /**
   * Resolves the absolute URL of the refresh endpoint.  Tests can
   * inject this; production wiring just lets the middleware build it
   * from the original request URL.
   */
  refreshUrl?: () => string;
};

const RETRY_FLAG = Symbol.for('contricool.no-retry');

type FlaggedRequest = Request & { [RETRY_FLAG]?: true };

function isAuthBootstrapPath(pathname: string): boolean {
  // Match `/v1/auth/...`, `/auth/...`, etc — everything in the auth
  // bootstrap surface that should never trigger refresh-retry.
  return /\/auth\//.test(pathname);
}

function defaultRefreshUrl(originalUrl: string): string {
  // Replace whatever comes after the API-version prefix with `/auth/refresh`.
  // Works for both `https://host/v1/me` → `https://host/v1/auth/refresh`
  // and same-origin `/v1/me` → `/v1/auth/refresh`.
  const match = originalUrl.match(/^(.*?\/v\d+)\//);
  if (match) {
    return `${match[1]}/auth/refresh`;
  }
  // Same-origin relative form: jsdom resolves these against the
  // document base, so the absolute prefix matcher above already
  // handles them. If we still don't have a match, build a path-only
  // refresh URL anchored at the request's origin.
  const url = new URL(originalUrl);
  return `${url.origin}/auth/refresh`;
}

export function authMiddleware(opts: AuthMiddlewareOptions): Middleware {
  return {
    onRequest({ request }: MiddlewareCallbackParams): Request {
      const url = new URL(request.url);
      if (!isAuthBootstrapPath(url.pathname)) {
        const t = opts.getAccessToken();
        if (t) {
          request.headers.set('authorization', `Bearer ${t}`);
        }
      }
      return request;
    },

    async onResponse({
      request,
      response,
    }: MiddlewareCallbackParams & { response: Response }): Promise<Response | undefined> {
      if (response.ok) {
        return response;
      }

      const url = new URL(request.url);
      const flagged = request as FlaggedRequest;
      const alreadyRetried = flagged[RETRY_FLAG] === true;

      if (response.status === 401 && !isAuthBootstrapPath(url.pathname) && !alreadyRetried) {
        const refreshUrl = (opts.refreshUrl ?? (() => defaultRefreshUrl(request.url)))();
        const refreshReq = new Request(refreshUrl, {
          method: 'POST',
          credentials: 'include',
        });
        // Mark so the response of this very call doesn't recurse.
        (refreshReq as FlaggedRequest)[RETRY_FLAG] = true;
        let refreshOk = false;
        let tokens: { access_token: string; id_token: string } | null = null;
        try {
          const r = await fetch(refreshReq);
          if (r.ok) {
            tokens = (await r.json()) as { access_token: string; id_token: string };
            refreshOk = true;
          }
        } catch {
          refreshOk = false;
        }

        if (refreshOk && tokens) {
          opts.onTokenRefreshed?.(tokens);
          const replay = new Request(request, {
            headers: new Headers(request.headers),
          });
          replay.headers.set('authorization', `Bearer ${tokens.access_token}`);
          (replay as FlaggedRequest)[RETRY_FLAG] = true;
          return fetch(replay);
        }

        // Refresh failed — sign out, then fall through to envelope parse
        // so the original 401 is what the screen sees.
        try {
          await opts.onUnauthenticated();
        } catch {
          // swallow — we still want to surface the original 401
        }
      }

      const apiError = await parseError(response);
      throw new ApiErrorException(apiError);
    },
  };
}
