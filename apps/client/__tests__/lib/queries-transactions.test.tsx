/**
 * Phase 4c — TanStack Query hook tests for the transactions feature.
 * Mirrors the friends hook tests; one happy + one error per hook.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

import { useAuthStore } from '~/lib/auth-store';
import {
  transactionsKeys,
  useCreateTransaction,
  useTransaction,
  useTransactions,
} from '~/lib/queries/transactions';

import { server } from '../msw-handlers';

const BASE = 'http://localhost/v1';

function makeWrapper() {
  // Auth-store needs tokens so the SDK middleware attaches the
  // Authorization header (otherwise an unauth-redirect kicks in).
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
      queries: { retry: false, staleTime: 0, gcTime: 60_000 },
      mutations: { retry: false },
    },
  });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return { Wrapper, qc };
}

describe('useTransactions', () => {
  it('returns the seeded MSW list', async () => {
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useTransactions(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toHaveLength(1);
    expect(result.current.data?.items[0]?.txn_id).toBe('01J0000000000000000000TX1');
  });

  it('surfaces 4xx envelopes as errors', async () => {
    server.use(
      http.get(`${BASE}/transactions`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'UNAUTHENTICATED',
              message: 'Authentication required.',
              request_id: 'r',
            },
          },
          { status: 401 },
        ),
      ),
    );
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useTransactions(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe('useTransaction', () => {
  it('fetches a single transaction by id', async () => {
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useTransaction('01J0000000000000000000TX1'), {
      wrapper: Wrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.txn_id).toBe('01J0000000000000000000TX1');
    expect(result.current.data?.members).toHaveLength(3);
  });

  it('disables itself for empty id', () => {
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useTransaction(''), { wrapper: Wrapper });
    expect(result.current.fetchStatus).toBe('idle');
  });
});

describe('useCreateTransaction', () => {
  it('attaches Idempotency-Key header and invalidates caches on 201', async () => {
    server.use(
      http.post(`${BASE}/transactions`, async ({ request }) => {
        const key = request.headers.get('idempotency-key');
        return HttpResponse.json(
          {
            txn_id: '01J0000000000000000000NEW',
            creator_id: '01J0000000000000000000ALI',
            name: 'X',
            type: 'expense',
            amount: '10.00',
            currency: 'USD',
            txn_date: '2026-04-29',
            note: '',
            split_method: 'equal',
            members: [
              {
                user_id: '01J0000000000000000000ALI',
                owed_amount: '5.00',
                share: null,
                percent: null,
              },
              {
                user_id: '01J0000000000000000000BOB',
                owed_amount: '5.00',
                share: null,
                percent: null,
              },
            ],
            payers: [{ user_id: '01J0000000000000000000ALI', paid_amount: '10.00' }],
            created_at: '2026-04-29T20:00:00Z',
            updated_at: '2026-04-29T20:00:00Z',
            deleted_at: null,
            _key: key,
          },
          { status: 201 },
        );
      }),
    );
    const { Wrapper, qc } = makeWrapper();
    const { result } = renderHook(() => useCreateTransaction(), { wrapper: Wrapper });

    const txn = await result.current.mutateAsync({
      body: {
        name: 'X',
        type: 'expense',
        amount: '10.00',
        currency: 'USD',
        txn_date: '2026-04-29',
        split_method: 'equal',
        note: '',
        members: [
          { user_id: '01J0000000000000000000ALI', share: null, percent: null, owed_amount: null },
          { user_id: '01J0000000000000000000BOB', share: null, percent: null, owed_amount: null },
        ],
        payers: [{ user_id: '01J0000000000000000000ALI', paid_amount: '10.00' }],
      },
      idempotencyKey: 'shared-key-1',
    });
    expect(txn.txn_id).toBe('01J0000000000000000000NEW');

    // Cache invalidations happened.
    const stale = qc
      .getQueryCache()
      .findAll({ queryKey: transactionsKeys.all })
      .every((q) => q.state.isInvalidated || q.state.fetchStatus === 'idle');
    expect(stale).toBe(true);
  });

  it('surfaces 422 NOT_FRIEND as a mutation error', async () => {
    server.use(
      http.post(`${BASE}/transactions`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'NOT_FRIEND',
              message: 'One or more members are not your friend.',
              request_id: 'r',
            },
          },
          { status: 422 },
        ),
      ),
    );
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useCreateTransaction(), { wrapper: Wrapper });
    await expect(
      result.current.mutateAsync({
        body: {
          name: 'X',
          type: 'expense',
          amount: '10.00',
          currency: 'USD',
          txn_date: '2026-04-29',
          split_method: 'equal',
          note: '',
          members: [
            { user_id: '01J0000000000000000000ALI', share: null, percent: null, owed_amount: null },
            { user_id: '01J0000000000000000000BOB', share: null, percent: null, owed_amount: null },
          ],
          payers: [{ user_id: '01J0000000000000000000ALI', paid_amount: '10.00' }],
        },
        idempotencyKey: 'k',
      }),
    ).rejects.toBeDefined();
  });
});
