import createOpenapiClient, { type Middleware } from 'openapi-fetch';

import { authMiddleware } from './middleware';
import type { paths } from './schema';

export type { paths } from './schema';
export { ApiErrorException } from './errors';
export type { ApiError, ApiErrorDetail } from './errors';

export type ClientOptions = {
  /** API base URL — usually `/v1` or `https://<host>/v1`. */
  baseUrl: string;
  /** Returns the current access token (or null if signed out). */
  getAccessToken: () => string | null;
  /**
   * Called when the 401-refresh-retry flow exhausts and the user
   * needs to be signed out locally.
   */
  onUnauthenticated: () => Promise<void> | void;
  /** Called after a successful refresh so the store can store new tokens. */
  onTokenRefreshed?: (tokens: { access_token: string; id_token: string }) => void;
};

export type ContricoolClient = ReturnType<typeof createOpenapiClient<paths>>;

export function createClient(opts: ClientOptions): ContricoolClient {
  const client = createOpenapiClient<paths>({
    baseUrl: opts.baseUrl,
    credentials: 'include',
    // Dispatch dynamically so test runtimes (MSW, fetch-mock) that
    // patch `globalThis.fetch` after module load are picked up.
    // Without this wrapper, openapi-fetch captures the unpatched
    // reference at createClient time.
    fetch: (request) => globalThis.fetch(request),
  });
  client.use(authMiddleware(opts) as Middleware);
  return client;
}

// ---------------------------------------------------------------------------
// Friendly response/request type aliases for the auth surface.
//
// Phase 2c paths are stable; if a route is ever renamed the aliases break
// at compile time, which is the right failure mode.
// ---------------------------------------------------------------------------

type AuthPaths = paths;

export type SignInRequest = NonNullable<
  AuthPaths['/auth/login']['post']['requestBody']
>['content']['application/json'];
export type SignInResponse =
  AuthPaths['/auth/login']['post']['responses']['200']['content']['application/json'];

export type SignupRequest = NonNullable<
  AuthPaths['/auth/signup']['post']['requestBody']
>['content']['application/json'];
export type SignupResponse =
  AuthPaths['/auth/signup']['post']['responses']['202']['content']['application/json'];

export type VerifyEmailRequest = NonNullable<
  AuthPaths['/auth/verify-email']['post']['requestBody']
>['content']['application/json'];
export type VerifyEmailResponse =
  AuthPaths['/auth/verify-email']['post']['responses']['200']['content']['application/json'];

export type ResendEmailCodeRequest = NonNullable<
  AuthPaths['/auth/resend-email-code']['post']['requestBody']
>['content']['application/json'];
export type ResendEmailCodeResponse =
  AuthPaths['/auth/resend-email-code']['post']['responses']['202']['content']['application/json'];

export type ForgotPasswordRequest = NonNullable<
  AuthPaths['/auth/forgot-password']['post']['requestBody']
>['content']['application/json'];
export type ForgotPasswordResponse =
  AuthPaths['/auth/forgot-password']['post']['responses']['202']['content']['application/json'];

export type ResetPasswordRequest = NonNullable<
  AuthPaths['/auth/reset-password']['post']['requestBody']
>['content']['application/json'];
export type ResetPasswordResponse =
  AuthPaths['/auth/reset-password']['post']['responses']['200']['content']['application/json'];

export type RefreshResponse =
  AuthPaths['/auth/refresh']['post']['responses']['200']['content']['application/json'];

export type AuthUser = SignInResponse['user'];
export type Currency = AuthUser['currency'];
