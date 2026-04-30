/**
 * Phase 4c — AddTransactionSheet integration tests covering the
 * happy path, the field-level validation surface, the typed-error
 * mapping, and the idempotency-key lifecycle.
 *
 * The friend list comes from the default MSW handler.  Each test
 * either reuses that handler or registers a per-test override.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { AddTransactionSheet } from '~/components/transactions/AddTransactionSheet';
import { Toaster, useToasterStore } from '~/components/ui/Toaster';
import { useAuthStore } from '~/lib/auth-store';

import { mockExpoRouter, resetRouterMock } from '../../app/_router-mock';
import { server } from '../../msw-handlers';
import { withProviders } from '../../test-utils';

mockExpoRouter();

const BASE = 'http://localhost/v1';
const ME = '01J0000000000000000000ALI';

beforeEach(() => {
  resetRouterMock();
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

function renderSheet() {
  return render(
    withProviders(
      <>
        <AddTransactionSheet open onClose={() => {}} />
        <Toaster />
      </>,
    ),
  );
}

describe('AddTransactionSheet — happy path', () => {
  it('submits an equal-split with the requester paying full amount', async () => {
    const seen: { body: unknown; key: string | null }[] = [];
    server.use(
      http.post(`${BASE}/transactions`, async ({ request }) => {
        const body = await request.json();
        seen.push({ body, key: request.headers.get('idempotency-key') });
        return HttpResponse.json(
          {
            txn_id: '01J0000000000000000000NEW',
            creator_id: ME,
            name: 'Dinner',
            type: 'expense',
            amount: '30.00',
            currency: 'USD',
            txn_date: '2026-04-29',
            note: '',
            split_method: 'equal',
            members: [
              { user_id: ME, owed_amount: '15.00', share: null, percent: null },
              {
                user_id: '01J0000000000000000000BOB',
                owed_amount: '15.00',
                share: null,
                percent: null,
              },
            ],
            payers: [{ user_id: ME, paid_amount: '30.00' }],
            created_at: '2026-04-29T20:00:00Z',
            updated_at: '2026-04-29T20:00:00Z',
            deleted_at: null,
          },
          { status: 201 },
        );
      }),
    );
    renderSheet();
    await waitFor(() =>
      expect(screen.getByTestId('add-txn-member-01J0000000000000000000BOB')).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByTestId('add-txn-name'), { target: { value: 'Dinner' } });
    fireEvent.change(screen.getByTestId('add-txn-amount'), { target: { value: '30.00' } });
    fireEvent.click(screen.getByTestId('add-txn-member-01J0000000000000000000BOB'));
    fireEvent.click(screen.getByTestId('add-txn-submit'));
    await waitFor(() => expect(seen).toHaveLength(1));
    expect(seen[0]?.key).toBeTruthy();
    expect(typeof seen[0]?.key).toBe('string');
    const body = seen[0]?.body as {
      name: string;
      amount: string;
      payers: { paid_amount: string }[];
    };
    expect(body.name).toBe('Dinner');
    expect(body.amount).toBe('30.00');
    expect(body.payers[0]?.paid_amount).toBe('30.00');
  });
});

describe('AddTransactionSheet — validation', () => {
  it('blocks submit without a name', async () => {
    renderSheet();
    fireEvent.change(screen.getByTestId('add-txn-amount'), { target: { value: '30.00' } });
    fireEvent.click(screen.getByTestId('add-txn-submit'));
    await waitFor(() => expect(screen.getByTestId('add-txn-name-error')).toBeInTheDocument());
  });

  it('blocks submit with a non-positive amount', async () => {
    renderSheet();
    fireEvent.change(screen.getByTestId('add-txn-name'), { target: { value: 'X' } });
    fireEvent.change(screen.getByTestId('add-txn-amount'), { target: { value: '0' } });
    fireEvent.click(screen.getByTestId('add-txn-submit'));
    await waitFor(() => expect(screen.getByTestId('add-txn-amount-error')).toBeInTheDocument());
  });

  it('blocks submit when fewer than 2 members are selected', async () => {
    renderSheet();
    fireEvent.change(screen.getByTestId('add-txn-name'), { target: { value: 'X' } });
    fireEvent.change(screen.getByTestId('add-txn-amount'), { target: { value: '10.00' } });
    fireEvent.click(screen.getByTestId('add-txn-submit'));
    await waitFor(() => expect(screen.getByTestId('add-txn-members-error')).toBeInTheDocument());
  });
});

describe('AddTransactionSheet — server-error mapping', () => {
  function fillValidForm() {
    fireEvent.change(screen.getByTestId('add-txn-name'), { target: { value: 'X' } });
    fireEvent.change(screen.getByTestId('add-txn-amount'), { target: { value: '10.00' } });
    fireEvent.click(screen.getByTestId('add-txn-member-01J0000000000000000000BOB'));
  }

  it('NOT_FRIEND surfaces an inline banner', async () => {
    server.use(
      http.post(`${BASE}/transactions`, () =>
        HttpResponse.json(
          {
            error: { code: 'NOT_FRIEND', message: 'no', request_id: 'r' },
          },
          { status: 422 },
        ),
      ),
    );
    renderSheet();
    await waitFor(() =>
      expect(screen.getByTestId('add-txn-member-01J0000000000000000000BOB')).toBeInTheDocument(),
    );
    fillValidForm();
    fireEvent.click(screen.getByTestId('add-txn-submit'));
    await waitFor(() => expect(screen.getByTestId('add-txn-banner')).toBeInTheDocument());
  });

  it('IDEMPOTENCY_KEY_REUSED surfaces a toast', async () => {
    server.use(
      http.post(`${BASE}/transactions`, () =>
        HttpResponse.json(
          {
            error: { code: 'IDEMPOTENCY_KEY_REUSED', message: 'no', request_id: 'r' },
          },
          { status: 409 },
        ),
      ),
    );
    renderSheet();
    await waitFor(() =>
      expect(screen.getByTestId('add-txn-member-01J0000000000000000000BOB')).toBeInTheDocument(),
    );
    fillValidForm();
    fireEvent.click(screen.getByTestId('add-txn-submit'));
    await waitFor(() => expect(screen.getByTestId('toast-error')).toBeInTheDocument());
  });

  it('PAID_SUM is mapped to the payers field error', async () => {
    server.use(
      http.post(`${BASE}/transactions`, () =>
        HttpResponse.json(
          {
            error: { code: 'PAID_SUM', message: 'no', request_id: 'r' },
          },
          { status: 422 },
        ),
      ),
    );
    renderSheet();
    await waitFor(() =>
      expect(screen.getByTestId('add-txn-member-01J0000000000000000000BOB')).toBeInTheDocument(),
    );
    fillValidForm();
    fireEvent.click(screen.getByTestId('add-txn-submit'));
    await waitFor(() => expect(screen.getByTestId('add-txn-payers-error')).toBeInTheDocument());
  });
});
