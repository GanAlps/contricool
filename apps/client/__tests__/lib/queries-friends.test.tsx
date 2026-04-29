/**
 * Unit tests for the friends TanStack Query hooks.  Each hook gets a
 * happy-path assertion plus one error path (the 4xx envelope is
 * surfaced as `error` thanks to the SDK middleware).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { useAuthStore } from '~/lib/auth-store';
import {
  friendsKeys,
  useAddFriend,
  useFriendBalance,
  useFriends,
  useRemoveFriend,
} from '~/lib/queries/friends';

import { server } from '../msw-handlers';

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0, gcTime: 60_000 },
      mutations: { retry: false },
    },
  });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return { qc, Wrapper };
}

beforeEach(() => {
  useAuthStore.setState({ accessToken: 'a', idToken: 'i' });
});
afterEach(() => {
  useAuthStore.getState()._clear();
});

describe('friendsKeys', () => {
  it('exposes stable key shapes', () => {
    expect(friendsKeys.all).toEqual(['friends']);
    expect(friendsKeys.list(50)).toEqual(['friends', { limit: 50 }]);
    expect(friendsKeys.balance('u1')).toEqual(['friend-balance', 'u1']);
  });
});

describe('useFriends', () => {
  it('fetches the friend list', async () => {
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useFriends(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items.map((i) => i.name)).toEqual(['Alice', 'Bob']);
  });

  it('surfaces a server error on the hook', async () => {
    server.use(
      http.get('http://localhost/v1/friends', () =>
        HttpResponse.json(
          { error: { code: 'INTERNAL_ERROR', message: 'boom', request_id: 'r' } },
          { status: 500 },
        ),
      ),
    );
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useFriends(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe('useFriendBalance', () => {
  it('fetches the balance for the given user', async () => {
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useFriendBalance('u1'), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.user_id).toBe('u1');
    expect(result.current.data?.settlement_status).toBe('settled');
  });

  it('does not fire when userId is empty', () => {
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useFriendBalance(''), { wrapper: Wrapper });
    expect(result.current.fetchStatus).toBe('idle');
  });
});

describe('useAddFriend', () => {
  it('invalidates the friends list on success', async () => {
    const { qc, Wrapper } = makeWrapper();
    qc.setQueryData(friendsKeys.list(50), { items: [], next_cursor: null });
    const { result } = renderHook(() => useAddFriend(), { wrapper: Wrapper });
    await act(async () => {
      await result.current.mutateAsync({ email: 'x@example.com' });
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const state = qc.getQueryState(friendsKeys.list(50));
    expect(state?.isInvalidated).toBe(true);
  });

  it('surfaces 409 conflict to the caller', async () => {
    server.use(
      http.post('http://localhost/v1/friends/add', () =>
        HttpResponse.json(
          { error: { code: 'CONFLICT', message: 'already friends', request_id: 'r' } },
          { status: 409 },
        ),
      ),
    );
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useAddFriend(), { wrapper: Wrapper });
    await act(async () => {
      await expect(result.current.mutateAsync({ email: 'x@example.com' })).rejects.toThrow();
    });
  });
});

describe('useRemoveFriend', () => {
  it('invalidates list and clears balance cache on success', async () => {
    const { qc, Wrapper } = makeWrapper();
    qc.setQueryData(friendsKeys.list(50), { items: [], next_cursor: null });
    qc.setQueryData(friendsKeys.balance('u1'), { user_id: 'u1' });
    const { result } = renderHook(() => useRemoveFriend(), { wrapper: Wrapper });
    await act(async () => {
      await result.current.mutateAsync('u1');
    });
    expect(qc.getQueryData(friendsKeys.balance('u1'))).toBeUndefined();
    const state = qc.getQueryState(friendsKeys.list(50));
    expect(state?.isInvalidated).toBe(true);
  });

  it('surfaces a 404 on the hook', async () => {
    server.use(
      http.delete('http://localhost/v1/friends/:userId', () =>
        HttpResponse.json(
          { error: { code: 'USER_NOT_FOUND', message: 'no such friend', request_id: 'r' } },
          { status: 404 },
        ),
      ),
    );
    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useRemoveFriend(), { wrapper: Wrapper });
    await act(async () => {
      await expect(result.current.mutateAsync('ghost')).rejects.toThrow();
    });
  });
});
