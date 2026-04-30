/**
 * Phase 4c — transactions list screen integration tests.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { useAuthStore } from '~/lib/auth-store';

import { server } from '../../msw-handlers';
import { withProviders } from '../../test-utils';
import { mockExpoRouter, resetRouterMock, setSearchParams } from '../_router-mock';

mockExpoRouter();

const TransactionsListScreen = (await import('~/app/(app)/transactions/index')).default;

beforeEach(() => {
  resetRouterMock();
  setSearchParams({});
  useAuthStore.setState({
    user: { user_id: 'me', name: 'Me', currency: 'USD' },
    accessToken: 'a',
    idToken: 'i',
    loading: false,
  });
});
afterEach(() => {
  useAuthStore.getState()._clear();
});

describe('TransactionsListScreen', () => {
  it('renders the seeded transaction', async () => {
    render(withProviders(<TransactionsListScreen />));
    await waitFor(() => expect(screen.getByTestId('txns-list')).toBeInTheDocument());
    expect(screen.getByText('Dinner')).toBeInTheDocument();
  });

  it('shows the All filter chip and an Add CTA', async () => {
    render(withProviders(<TransactionsListScreen />));
    expect(screen.getByTestId('filter-chip-all')).toBeInTheDocument();
    expect(screen.getByTestId('txns-add')).toBeInTheDocument();
  });

  it('renders the empty state when no transactions match', async () => {
    server.use(
      http.get('http://localhost/v1/transactions', () =>
        HttpResponse.json({ items: [], next_cursor: null }, { status: 200 }),
      ),
    );
    render(withProviders(<TransactionsListScreen />));
    await waitFor(() => expect(screen.getByTestId('txns-empty')).toBeInTheDocument());
    expect(screen.getByTestId('txns-empty-add')).toBeInTheDocument();
  });

  it('renders a "With <friend>" chip when friend_id is in the URL', async () => {
    setSearchParams({ friend_id: '01J0000000000000000000ALI' });
    render(withProviders(<TransactionsListScreen />));
    await waitFor(() =>
      expect(
        screen.getByTestId('filter-chip-friend-01J0000000000000000000ALI'),
      ).toBeInTheDocument(),
    );
  });
});

describe('TransactionsListScreen — interactions', () => {
  it('opens the add-transaction sheet when the CTA is tapped', async () => {
    render(withProviders(<TransactionsListScreen />));
    fireEvent.click(screen.getByTestId('txns-add'));
    await waitFor(() => expect(screen.getByTestId('add-txn-sheet')).toBeInTheDocument());
  });

  it('clears the friend filter when the All chip is tapped', async () => {
    setSearchParams({ friend_id: '01J0000000000000000000ALI' });
    const { getRouterMock } = await import('../_router-mock');
    render(withProviders(<TransactionsListScreen />));
    fireEvent.click(screen.getByTestId('filter-chip-all'));
    expect(
      getRouterMock().calls.some((c) => c.kind === 'replace' && c.href === '/transactions'),
    ).toBe(true);
  });
});
