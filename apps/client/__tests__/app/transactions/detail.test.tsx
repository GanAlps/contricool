/**
 * Phase 4c + Phase 5 — transaction detail screen tests.
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

const TransactionDetailScreen = (await import('~/app/(app)/transactions/[txnId]')).default;

const BASE = 'http://localhost/v1';
const ME = '01J0000000000000000000ALI';
const BOB = '01J0000000000000000000BOB';

function renderDetail() {
  return render(
    withProviders(
      <>
        <TransactionDetailScreen />
        <Toaster />
      </>,
    ),
  );
}

beforeEach(() => {
  resetRouterMock();
  setSearchParams({ txnId: '01J0000000000000000000TX1' });
  useAuthStore.setState({
    user: { user_id: ME, name: 'Alice', currency: 'USD' },
    accessToken: 'a',
    idToken: 'i',
    loading: false,
  });
  useToasterStore.getState().clear();
});
afterEach(() => {
  useAuthStore.getState()._clear();
  useToasterStore.getState().clear();
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

describe('TransactionDetailScreen — Phase 5 lifecycle', () => {
  it('shows edit + delete buttons when the requester is the creator', async () => {
    render(withProviders(<TransactionDetailScreen />));
    await waitFor(() => expect(screen.getByTestId('txn-detail')).toBeInTheDocument());
    expect(screen.getByTestId('txn-detail-edit')).toBeInTheDocument();
    expect(screen.getByTestId('txn-detail-delete')).toBeInTheDocument();
  });

  it('hides edit + delete buttons when the requester is not the creator', async () => {
    server.use(
      http.get(`${BASE}/transactions/:txnId`, ({ params }) =>
        HttpResponse.json(
          {
            txn_id: String(params.txnId),
            creator_id: BOB, // not me
            name: 'Dinner',
            type: 'expense',
            amount: '30.00',
            currency: 'USD',
            txn_date: '2026-04-29',
            note: '',
            split_method: 'equal',
            members: [
              { user_id: ME, owed_amount: '10.00', share: null, percent: null },
              { user_id: BOB, owed_amount: '20.00', share: null, percent: null },
            ],
            payers: [{ user_id: BOB, paid_amount: '30.00' }],
            created_at: '2026-04-29T20:00:00Z',
            updated_at: '2026-04-29T20:00:00Z',
            deleted_at: null,
          },
          { status: 200 },
        ),
      ),
    );
    render(withProviders(<TransactionDetailScreen />));
    await waitFor(() => expect(screen.getByTestId('txn-detail')).toBeInTheDocument());
    expect(screen.queryByTestId('txn-detail-edit')).not.toBeInTheDocument();
    expect(screen.queryByTestId('txn-detail-delete')).not.toBeInTheDocument();
  });

  it('opens the confirm-delete sheet, calls DELETE, navigates back', async () => {
    let deleted = 0;
    server.use(
      http.delete(`${BASE}/transactions/:txnId`, () => {
        deleted += 1;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderDetail();
    await waitFor(() => expect(screen.getByTestId('txn-detail')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('txn-detail-delete'));
    await waitFor(() => expect(screen.getByTestId('txn-confirm-delete')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('txn-confirm-delete-confirm'));
    await waitFor(() => expect(deleted).toBe(1));
    expect(getRouterMock().calls).toContainEqual({ kind: 'back' });
  });

  it('cancel does not call DELETE', async () => {
    let deleted = 0;
    server.use(
      http.delete(`${BASE}/transactions/:txnId`, () => {
        deleted += 1;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderDetail();
    await waitFor(() => expect(screen.getByTestId('txn-detail')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('txn-detail-delete'));
    await waitFor(() => expect(screen.getByTestId('txn-confirm-delete')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('txn-confirm-delete-cancel'));
    await waitFor(() => expect(screen.queryByTestId('txn-confirm-delete')).not.toBeInTheDocument());
    expect(deleted).toBe(0);
  });

  it('shows the restore bar when the txn is soft-deleted, and restore succeeds', async () => {
    let restored = 0;
    server.use(
      http.get(`${BASE}/transactions/:txnId`, ({ params }) =>
        HttpResponse.json(
          {
            txn_id: String(params.txnId),
            creator_id: ME,
            name: 'Dinner',
            type: 'expense',
            amount: '30.00',
            currency: 'USD',
            txn_date: '2026-04-29',
            note: '',
            split_method: 'equal',
            members: [
              { user_id: ME, owed_amount: '10.00', share: null, percent: null },
              { user_id: BOB, owed_amount: '20.00', share: null, percent: null },
            ],
            payers: [{ user_id: ME, paid_amount: '30.00' }],
            created_at: '2026-04-29T20:00:00Z',
            updated_at: '2026-04-29T20:00:00Z',
            deleted_at: '2026-04-29T20:05:00Z',
          },
          { status: 200 },
        ),
      ),
      http.post(`${BASE}/transactions/:txnId/restore`, ({ params }) => {
        restored += 1;
        return HttpResponse.json(
          {
            txn_id: String(params.txnId),
            creator_id: ME,
            name: 'Dinner',
            type: 'expense',
            amount: '30.00',
            currency: 'USD',
            txn_date: '2026-04-29',
            note: '',
            split_method: 'equal',
            members: [
              { user_id: ME, owed_amount: '10.00', share: null, percent: null },
              { user_id: BOB, owed_amount: '20.00', share: null, percent: null },
            ],
            payers: [{ user_id: ME, paid_amount: '30.00' }],
            created_at: '2026-04-29T20:00:00Z',
            updated_at: '2026-04-29T20:06:00Z',
            deleted_at: null,
          },
          { status: 200 },
        );
      }),
    );
    renderDetail();
    await waitFor(() => expect(screen.getByTestId('txn-detail-restore-bar')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('txn-detail-restore'));
    await waitFor(() => expect(restored).toBe(1));
  });

  it('GONE on restore surfaces the 30-day expired message', async () => {
    server.use(
      http.get(`${BASE}/transactions/:txnId`, ({ params }) =>
        HttpResponse.json(
          {
            txn_id: String(params.txnId),
            creator_id: ME,
            name: 'Dinner',
            type: 'expense',
            amount: '30.00',
            currency: 'USD',
            txn_date: '2026-04-29',
            note: '',
            split_method: 'equal',
            members: [
              { user_id: ME, owed_amount: '10.00', share: null, percent: null },
              { user_id: BOB, owed_amount: '20.00', share: null, percent: null },
            ],
            payers: [{ user_id: ME, paid_amount: '30.00' }],
            created_at: '2026-04-29T20:00:00Z',
            updated_at: '2026-04-29T20:05:00Z',
            deleted_at: '2026-03-01T00:00:00Z',
          },
          { status: 200 },
        ),
      ),
      http.post(`${BASE}/transactions/:txnId/restore`, () =>
        HttpResponse.json(
          { error: { code: 'GONE', message: 'expired', request_id: 'r' } },
          { status: 410 },
        ),
      ),
    );
    renderDetail();
    await waitFor(() => expect(screen.getByTestId('txn-detail-restore-bar')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('txn-detail-restore'));
    await waitFor(() => expect(screen.getByTestId('toast-error')).toHaveTextContent(/30-day/));
  });
});
