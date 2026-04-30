/**
 * Friend detail screen — N12, N13, N14, N15 + happy path.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { Toaster, useToasterStore } from '~/components/ui/Toaster';
import { useAuthStore } from '~/lib/auth-store';

import { server } from '../../msw-handlers';
import { withProviders } from '../../test-utils';
import { getRouterMock, mockExpoRouter, resetRouterMock, setSearchParams } from '../_router-mock';

mockExpoRouter();

const FriendDetailScreen = (await import('~/app/(app)/friends/[userId]')).default;

function renderDetail() {
  return render(
    withProviders(
      <>
        <FriendDetailScreen />
        <Toaster />
      </>,
    ),
  );
}

beforeEach(() => {
  resetRouterMock();
  setSearchParams({ userId: 'u1' });
  useAuthStore.setState({
    user: { user_id: 'me', name: 'Me', currency: 'USD' },
    accessToken: 'a',
    idToken: 'i',
    loading: false,
  });
  useToasterStore.getState().clear();
  // Default friends list has Alice (u1) and Bob (u2) so the cache
  // lookup for `name` finds something.
  server.use(
    http.get('http://localhost/v1/friends', () =>
      HttpResponse.json(
        {
          items: [
            {
              user_id: 'u1',
              name: 'Alice',
              currency: 'USD',
              since: '2026-04-01T00:00:00Z',
            },
          ],
          next_cursor: null,
        },
        { status: 200 },
      ),
    ),
  );
});
afterEach(() => {
  useAuthStore.getState()._clear();
  useToasterStore.getState().clear();
});

describe('FriendDetailScreen — happy path', () => {
  it('renders name + currency + Settled balance card', async () => {
    renderDetail();
    await waitFor(() => expect(screen.getByTestId('friend-detail-balance')).toBeInTheDocument());
    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.getByText('Settled')).toBeInTheDocument();
    expect(screen.getByTestId('friend-detail-balance')).toHaveTextContent('0.00 USD');
  });
});

describe('FriendDetailScreen — N12 balance 404', () => {
  it('renders the not-friends state with back link', async () => {
    server.use(
      http.get('http://localhost/v1/friends/:userId/balance', () =>
        HttpResponse.json(
          { error: { code: 'USER_NOT_FOUND', message: 'no', request_id: 'r' } },
          { status: 404 },
        ),
      ),
    );
    renderDetail();
    await waitFor(() => expect(screen.getByTestId('friend-not-found')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('friend-not-found-back'));
    expect(getRouterMock().calls).toContainEqual({ kind: 'replace', href: '/friends' });
  });
});

describe('FriendDetailScreen — remove flow', () => {
  it('N13: cancel does not call the DELETE API', async () => {
    let calls = 0;
    server.use(
      http.delete('http://localhost/v1/friends/:userId', () => {
        calls += 1;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderDetail();
    await waitFor(() => expect(screen.getByTestId('friend-detail-balance')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('friend-remove'));
    await waitFor(() => expect(screen.getByTestId('confirm-remove')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('confirm-remove-cancel'));
    await waitFor(() => expect(screen.queryByTestId('confirm-remove')).not.toBeInTheDocument());
    expect(calls).toBe(0);
  });

  it('N14: confirm → DELETE → toast + router.back', async () => {
    server.use(
      http.delete(
        'http://localhost/v1/friends/:userId',
        () => new HttpResponse(null, { status: 204 }),
      ),
    );
    renderDetail();
    await waitFor(() => expect(screen.getByTestId('friend-detail-balance')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('friend-remove'));
    await waitFor(() => expect(screen.getByTestId('confirm-remove')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('confirm-remove-confirm'));
    await waitFor(() =>
      expect(screen.getByTestId('toast-success')).toHaveTextContent('Removed Alice'),
    );
    expect(getRouterMock().calls).toContainEqual({ kind: 'back' });
  });

  it('N15: 404 race → "Already removed" info toast + back', async () => {
    server.use(
      http.delete('http://localhost/v1/friends/:userId', () =>
        HttpResponse.json(
          { error: { code: 'USER_NOT_FOUND', message: 'race', request_id: 'r' } },
          { status: 404 },
        ),
      ),
    );
    renderDetail();
    await waitFor(() => expect(screen.getByTestId('friend-detail-balance')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('friend-remove'));
    await waitFor(() => expect(screen.getByTestId('confirm-remove')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('confirm-remove-confirm'));
    await waitFor(() =>
      expect(screen.getByTestId('toast-info')).toHaveTextContent(/already removed/i),
    );
    expect(getRouterMock().calls).toContainEqual({ kind: 'back' });
  });

  it('shows generic toast on 5xx remove and stays on detail screen', async () => {
    server.use(
      http.delete('http://localhost/v1/friends/:userId', () =>
        HttpResponse.json(
          { error: { code: 'INTERNAL_ERROR', message: 'down', request_id: 'r' } },
          { status: 500 },
        ),
      ),
    );
    renderDetail();
    await waitFor(() => expect(screen.getByTestId('friend-detail-balance')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('friend-remove'));
    await waitFor(() => expect(screen.getByTestId('confirm-remove')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('confirm-remove-confirm'));
    await waitFor(() => expect(screen.getByTestId('toast-error')).toBeInTheDocument());
    expect(getRouterMock().calls.find((c) => c.kind === 'back')).toBeUndefined();
  });
});

describe('FriendDetailScreen — balance status variants', () => {
  it('renders friend_owes headline', async () => {
    server.use(
      http.get('http://localhost/v1/friends/:userId/balance', ({ params }) =>
        HttpResponse.json(
          {
            user_id: params.userId,
            currency: 'USD',
            net: '15.00',
            settlement_status: 'friend_owes',
            last_transaction_at: '2026-04-29T12:00:00Z',
          },
          { status: 200 },
        ),
      ),
    );
    renderDetail();
    await waitFor(() => expect(screen.getByTestId('friend-detail-headline')).toBeInTheDocument());
    expect(screen.getByTestId('friend-detail-headline')).toHaveTextContent(/Friend owes you/);
  });

  it('renders you_owe headline with absolute value', async () => {
    server.use(
      http.get('http://localhost/v1/friends/:userId/balance', ({ params }) =>
        HttpResponse.json(
          {
            user_id: params.userId,
            currency: 'USD',
            net: '-7.50',
            settlement_status: 'you_owe',
            last_transaction_at: '2026-04-29T12:00:00Z',
          },
          { status: 200 },
        ),
      ),
    );
    renderDetail();
    await waitFor(() => expect(screen.getByTestId('friend-detail-headline')).toBeInTheDocument());
    expect(screen.getByTestId('friend-detail-headline')).toHaveTextContent(/You owe 7\.50/);
  });

  it('renders friend transactions empty state when none', async () => {
    server.use(
      http.get('http://localhost/v1/transactions', () =>
        HttpResponse.json({ items: [], next_cursor: null }, { status: 200 }),
      ),
    );
    renderDetail();
    await waitFor(() => expect(screen.getByTestId('friend-txns-empty')).toBeInTheDocument());
  });
});
