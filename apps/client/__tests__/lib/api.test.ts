/**
 * Phase 2e: lib/api.ts is now a thin singleton over @contricool/client-sdk.
 * The exhaustive middleware behaviour is tested in the SDK package
 * (errors / middleware / createClient suites).  These tests verify
 * that the singleton wires the SDK to the auth store correctly:
 *   - `apiClient` is a single instance (no per-call factory churn).
 *   - `getAccessToken` reads from the live store.
 *   - `onTokenRefreshed` writes back through `_setTokensFromRefresh`.
 *   - `onUnauthenticated` clears the store.
 */
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { ApiErrorException, apiClient } from '~/lib/api';
import { useAuthStore } from '~/lib/auth-store';

import { server } from '../msw-handlers';

function b64url(input: string): string {
  return btoa(input).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_');
}
function makeIdToken(claims: Record<string, unknown>): string {
  return `${b64url('{}')}.${b64url(JSON.stringify(claims))}.sig`;
}

beforeEach(() => {
  useAuthStore.getState()._clear();
});
afterEach(() => {
  useAuthStore.getState()._clear();
});

describe('apiClient singleton', () => {
  it('is a single instance — repeated imports return the same client', async () => {
    const reimported = (await import('~/lib/api')).apiClient;
    expect(reimported).toBe(apiClient);
  });

  it('attaches Bearer token from the store on non-/auth/ requests', async () => {
    useAuthStore.setState({ accessToken: 'tok-123' });
    let received: string | null = null;
    server.use(
      http.get('http://localhost/v1/me', ({ request }) => {
        received = request.headers.get('authorization');
        return HttpResponse.json({ ok: true });
      }),
    );
    // openapi-fetch with a path not in the schema falls back to a
    // typed-as-never call; cast through unknown to bypass.
    await (
      apiClient as unknown as {
        GET: (p: string) => Promise<{ data?: unknown }>;
      }
    ).GET('/me');
    expect(received).toBe('Bearer tok-123');
  });

  it('updates the store when a 401 triggers a successful refresh', async () => {
    useAuthStore.setState({ accessToken: 'old-tok' });
    const newId = makeIdToken({
      'custom:user_id': 'u1',
      name: 'Alice',
      'custom:currency': 'USD',
    });
    server.use(
      http.get('http://localhost/v1/me', ({ request }) => {
        const a = request.headers.get('authorization');
        if (a === 'Bearer new-tok') return HttpResponse.json({ user_id: 'u1' });
        return HttpResponse.json(
          { error: { code: 'UNAUTHENTICATED', message: 'expired', request_id: 'r' } },
          { status: 401 },
        );
      }),
      http.post('http://localhost/v1/auth/refresh', () =>
        HttpResponse.json({ access_token: 'new-tok', id_token: newId, expires_in: 3600 }),
      ),
    );
    await (
      apiClient as unknown as {
        GET: (p: string) => Promise<{ data?: unknown }>;
      }
    ).GET('/me');
    expect(useAuthStore.getState().accessToken).toBe('new-tok');
    expect(useAuthStore.getState().user?.name).toBe('Alice');
  });

  it('clears the store when refresh also fails', async () => {
    useAuthStore.setState({
      user: { user_id: 'u', name: 'A', currency: 'USD' },
      accessToken: 'old',
      idToken: 'i',
      loading: false,
    });
    server.use(
      http.get('http://localhost/v1/me', () =>
        HttpResponse.json(
          { error: { code: 'UNAUTHENTICATED', message: 'gone', request_id: 'r' } },
          { status: 401 },
        ),
      ),
      http.post('http://localhost/v1/auth/refresh', () =>
        HttpResponse.json(
          { error: { code: 'REFRESH_FAILED', message: 'no', request_id: 'r2' } },
          { status: 401 },
        ),
      ),
    );
    await expect(
      (
        apiClient as unknown as {
          GET: (p: string) => Promise<{ data?: unknown }>;
        }
      ).GET('/me'),
    ).rejects.toBeInstanceOf(ApiErrorException);
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().accessToken).toBeNull();
  });

  it('does not retry on /v1/auth/login 401', async () => {
    let refreshCalled = 0;
    server.use(
      http.post('http://localhost/v1/auth/login', () =>
        HttpResponse.json(
          { error: { code: 'INVALID_CREDENTIALS', message: 'nope', request_id: 'r' } },
          { status: 401 },
        ),
      ),
      http.post('http://localhost/v1/auth/refresh', () => {
        refreshCalled++;
        return HttpResponse.json({ access_token: 'x', id_token: 'y', expires_in: 1 });
      }),
    );
    await expect(
      apiClient.POST('/auth/login', { body: { email: 'a@b.com', password: 'wrong' } }),
    ).rejects.toMatchObject({ error: { code: 'INVALID_CREDENTIALS' } });
    expect(refreshCalled).toBe(0);
  });
});
