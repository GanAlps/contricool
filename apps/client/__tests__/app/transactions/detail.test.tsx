/**
 * Phase 4c — transaction detail screen integration tests.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { useAuthStore } from '~/lib/auth-store';

import { server } from '../../msw-handlers';
import { withProviders } from '../../test-utils';
import { mockExpoRouter, resetRouterMock, setSearchParams } from '../_router-mock';

mockExpoRouter();

const TransactionDetailScreen = (await import('~/app/(app)/transactions/[txnId]')).default;

const BASE = 'http://localhost/v1';

beforeEach(() => {
  resetRouterMock();
  setSearchParams({ txnId: '01J0000000000000000000TX1' });
  useAuthStore.setState({
    user: { user_id: '01J0000000000000000000ALI', name: 'Alice', currency: 'USD' },
    accessToken: 'a',
    idToken: 'i',
    loading: false,
  });
});
afterEach(() => {
  useAuthStore.getState()._clear();
});

describe('TransactionDetailScreen — happy path', () => {
  it('renders amount + members + payers', async () => {
    render(withProviders(<TransactionDetailScreen />));
    await waitFor(() => expect(screen.getByTestId('txn-detail')).toBeInTheDocument());
    expect(screen.getByTestId('txn-detail-amount')).toHaveTextContent('30.00 USD');
    expect(screen.getByTestId('txn-detail-members')).toBeInTheDocument();
    expect(screen.getByTestId('txn-detail-payers')).toBeInTheDocument();
  });
});

describe('TransactionDetailScreen — 404 mask', () => {
  it('renders the not-found state', async () => {
    server.use(
      http.get(`${BASE}/transactions/:txnId`, () =>
        HttpResponse.json(
          { error: { code: 'NOT_FOUND', message: 'no', request_id: 'r' } },
          { status: 404 },
        ),
      ),
    );
    render(withProviders(<TransactionDetailScreen />));
    await waitFor(() => expect(screen.getByTestId('txn-not-found')).toBeInTheDocument());
  });
});
