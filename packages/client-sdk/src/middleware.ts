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
const REPLAY_BODY = Symbol.for('contricool.replay-body');

type FlaggedRequest = Request & {
  [RETRY_FLAG]?: true;
  [REPLAY_BODY]?: string | null;
};

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
    async onRequest({ request }: MiddlewareCallbackParams): Promise<Request> {
      // Attach the bearer whenever a token is available.
      //
      // The original Phase 2d code skipped this for any `/auth/*` path
      // on the assumption that all auth-bootstrap routes are public.
      // That assumption was wrong: `/auth/logout` is the one
      // **authenticated** route in the auth bootstrap (Phase 2c R6.1).
      // Without the bearer, the JWT authorizer 401s before the handler
      // runs, so Cognito GlobalSignOut never fires AND the backend
      // never sends the `Set-Cookie: rt=; Max-Age=0` cookie clear —
      // hard-reload after sign-out re-hydrates the session.
      //
      // The other `/auth/*` routes (login, signup, refresh, …) ignore
      // the Authorization header entirely, so attaching it there is a
      // harmless no-op.
      const t = opts.getAccessToken();
      if (t) {
        request.headers.set('authorization', `Bearer ${t}`);
      }
      // Phase 2e — capture the body BEFORE openapi-fetch consumes the
      // request stream.  The 401-retry path below has to send the same
      // body again, but `new Request(consumedRequest, ...)` produces a
      // body-less Request because the stream is already drained.
      // Methods that never carry a body (GET / HEAD / OPTIONS) skip
      // this so we don't pay the clone cost.
      const method = request.method.toUpperCase();
      const flagged = request as FlaggedRequest;
      if (
        method !== 'GET' &&
        method !== 'HEAD' &&
        method !== 'OPTIONS' &&
        flagged[REPLAY_BODY] === undefined
      ) {
        try {
          flagged[REPLAY_BODY] = await request.clone().text();
        } catch {
          flagged[REPLAY_BODY] = null;
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
          // Build a fresh Request from primitives — the original's body
          // stream is already consumed by openapi-fetch's first send,
          // so `new Request(request, ...)` would produce body: null
          // for any POST/PUT/PATCH.  The captured body string from
          // onRequest is what we re-attach.
          const flaggedReq = request as FlaggedRequest;
          const replayHeaders = new Headers(request.headers);
          replayHeaders.set('authorization', `Bearer ${tokens.access_token}`);
          const method = request.method.toUpperCase();
          const carriesBody = method !== 'GET' && method !== 'HEAD' && method !== 'OPTIONS';
          const replay = new Request(request.url, {
            method: request.method,
            headers: replayHeaders,
            body: carriesBody ? (flaggedReq[REPLAY_BODY] ?? null) : null,
            credentials: 'include',
          });
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
