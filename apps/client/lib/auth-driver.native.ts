/**
 * Native auth driver (Phase 8a).
 *
 * Mirrors `auth-driver.web.ts` but stores the refresh token in
 * `expo-secure-store` instead of relying on the HttpOnly cookie.
 * Native callers send `X-Client-Platform: native` on /v1/auth/login
 * so the backend returns the refresh token in the body for storage.
 *
 * The SDK's auto-refresh middleware reads the stored token via the
 * `getRefreshToken` callback wired in `lib/api.ts`, so on-the-wire
 * 401-retry behavior is identical to web — only persistence differs.
 */

import { apiClient } from './api';
import type { AuthDriver } from './auth-driver-types';
import { clearRefreshToken, getRefreshToken, setRefreshToken } from './secure-storage';

const PLATFORM_HEADER = { 'X-Client-Platform': 'native' };

export const nativeAuthDriver: AuthDriver = {
  signUp: async (input) => {
    const r = await apiClient.POST('/auth/signup', { body: input });
    return r.data!;
  },
  verifyEmail: async (input) => {
    const r = await apiClient.POST('/auth/verify-email', { body: input });
    return r.data!;
  },
  resendEmailCode: async (input) => {
    const r = await apiClient.POST('/auth/resend-email-code', { body: input });
    return r.data!;
  },
  signIn: async (input) => {
    const r = await apiClient.POST('/auth/login', {
      body: input,
      headers: PLATFORM_HEADER,
    });
    const data = r.data!;
    // Persist the body-returned refresh token; web variant relies on
    // the HttpOnly cookie set by the same endpoint.
    if (data.refresh_token) {
      await setRefreshToken(data.refresh_token);
    }
    // The auth store doesn't model a refresh token (it lives in secure
    // storage now). Strip the field so callers see the same LoginResponse
    // shape they get on web.
    const { refresh_token: _rt, ...rest } = data;
    return rest;
  },
  refreshSession: async () => {
    // Two refresh paths exist on native:
    //   1. SDK middleware 401-retry — body wired via `getRefreshToken`
    //      callback in `lib/api.ts` (covers all authenticated calls).
    //   2. Explicit boot-time refresh from `_layout.tsx` — uses this
    //      method directly. We have to read secure-storage and pass
    //      the token in the body ourselves; openapi-fetch doesn't run
    //      the middleware's refresh helper for explicit requests.
    const refresh_token = await getRefreshToken();
    const r = await apiClient.POST('/auth/refresh', {
      body: { refresh_token },
      headers: PLATFORM_HEADER,
    });
    return r.data!;
  },
  signOut: async () => {
    let driverErr: unknown = null;
    try {
      await apiClient.POST('/auth/logout');
    } catch (e) {
      driverErr = e;
    }
    // Always clear secure storage even if the API call failed — a
    // partial sign-out must not leave a usable refresh token on the
    // device.
    await clearRefreshToken();
    if (driverErr) {
      throw driverErr;
    }
  },
  forgotPassword: async (input) => {
    const r = await apiClient.POST('/auth/forgot-password', { body: input });
    return r.data!;
  },
  resetPassword: async (input) => {
    const r = await apiClient.POST('/auth/reset-password', { body: input });
    return r.data!;
  },
};

export default nativeAuthDriver;
