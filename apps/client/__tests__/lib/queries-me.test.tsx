/**
 * Phase 7 — TanStack Query hook tests for the /v1/me feature.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

import { useAuthStore } from '~/lib/auth-store';
import { useDeleteMyAccount, useExportMyData } from '~/lib/queries/me';

import { server } from '../msw-handlers';

const BASE = 'http://localhost/v1';

function makeWrapper() {
  useAuthStore.setState({
    user: {
      user_id: '01J0000000000000000000ALI',
      name: 'Alice',
      currency: 'USD',
    },
    accessToken: 'access-jwt',
    idToken: 'id-jwt',
    loading: false,
  } as never);

  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return { Wrapper };
}

describe('useDeleteMyAccount', () => {
  it('issues DELETE /me and resolves', async () => {
    server.use(http.delete(`${BASE}/me`, () => new HttpResponse(null, { status: 204 })));
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useDeleteMyAccount(), { wrapper: Wrapper });
    await result.current.mutateAsync();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it('surfaces 4xx envelopes as errors', async () => {
    server.use(
      http.delete(`${BASE}/me`, () =>
        HttpResponse.json(
          { error: { code: 'INTERNAL', message: 'oops', request_id: 'r' } },
          { status: 500 },
        ),
      ),
    );
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useDeleteMyAccount(), { wrapper: Wrapper });
    await expect(result.current.mutateAsync()).rejects.toThrow();
  });
});

describe('useExportMyData', () => {
  it('returns the export blob from the server', async () => {
    server.use(
      http.get(`${BASE}/me/export`, () =>
        HttpResponse.json(
          {
            profile: {
              user_id: '01J0000000000000000000ALI',
              name: 'Alice',
              currency: 'USD',
              status: 'active',
              created_at: '2026-04-29T20:00:00Z',
            },
            friendships: [],
            transactions: [],
            exported_at: '2026-04-29T20:00:00Z',
          },
          { status: 200 },
        ),
      ),
    );
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useExportMyData(), { wrapper: Wrapper });
    const data = await result.current.mutateAsync();
    expect(data.profile.user_id).toBe('01J0000000000000000000ALI');
    expect(data.friendships).toHaveLength(0);
  });

  it('rejects with the rate-limited envelope', async () => {
    server.use(
      http.get(`${BASE}/me/export`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'RATE_LIMITED',
              message: 'Try again later',
              request_id: 'r',
              retry_after_seconds: 86400,
            },
          },
          { status: 429 },
        ),
      ),
    );
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useExportMyData(), { wrapper: Wrapper });
    await waitFor(async () => {
      await expect(result.current.mutateAsync()).rejects.toThrow();
    });
  });
});
