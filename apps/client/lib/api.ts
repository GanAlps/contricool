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

/** Singleton SDK client used by the auth driver and (later) feature modules. */
export const apiClient: ContricoolClient = createClient({
  baseUrl: process.env.EXPO_PUBLIC_API_BASE_URL ?? '/v1',
  getAccessToken: () => useAuthStore.getState().accessToken,
  onUnauthenticated: async () => {
    useAuthStore.getState()._clear();
  },
  onTokenRefreshed: ({ access_token, id_token }) => {
    useAuthStore.getState()._setTokensFromRefresh(access_token, id_token);
  },
});

// Re-export for screens / drivers that previously imported the
// envelope types from this module.
export { ApiErrorException } from '@contricool/client-sdk';
export type { ApiError, ApiErrorDetail } from '@contricool/client-sdk';
