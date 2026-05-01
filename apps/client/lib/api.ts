/**
 * Phase 2e: thin shim over `@contricool/client-sdk`.
 *
 * The SDK does the heavy lifting (Bearer attach, envelope parse,
 * 401-refresh-retry-once with recursion guard).  This file just wires
 * the SDK to the auth store via callback closures, so token state
 * stays in one place and module-load doesn't introduce a cycle.
 */

import { type ContricoolClient, createClient } from '@contricool/client-sdk';

import { useAuthStore } from './auth-store';
import { clearRefreshToken, getRefreshToken } from './secure-storage';

/** Singleton SDK client used by the auth driver and (later) feature modules. */
export const apiClient: ContricoolClient = createClient({
  baseUrl: process.env.EXPO_PUBLIC_API_BASE_URL ?? '/v1',
  getTokens: () => {
    const s = useAuthStore.getState();
    if (!s.accessToken || !s.idToken) {
      return null;
    }
    return { accessToken: s.accessToken, idToken: s.idToken };
  },
  onUnauthenticated: async () => {
    // Clear in-memory state AND platform-secure storage. Without the
    // latter, a dead refresh token survives the implicit 401-retry
    // failure and re-hydrates the next boot with the same bad value,
    // producing a boot loop. Web's `clearRefreshToken` is a no-op
    // (cookie cleared by the backend's clear-cookie response header).
    useAuthStore.getState()._clear();
    await clearRefreshToken();
  },
  onTokenRefreshed: ({ access_token, id_token }) => {
    useAuthStore.getState()._setTokensFromRefresh(access_token, id_token);
  },
  // Native: returns the refresh token from expo-secure-store so the
  // SDK middleware can attach it in the 401-retry refresh body.
  // Web: returns null (HttpOnly cookie carries the value instead).
  getRefreshToken,
});

// Re-export for screens / drivers that previously imported the
// envelope types from this module.
export { ApiErrorException } from '@contricool/client-sdk';
export type { ApiError, ApiErrorDetail } from '@contricool/client-sdk';
