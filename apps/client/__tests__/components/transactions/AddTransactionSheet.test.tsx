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

describe('AddTransactionSheet — split-method control', () => {
  function captureBody() {
    const seen: { body: unknown }[] = [];
    server.use(
      http.post(`${BASE}/transactions`, async ({ request }) => {
        seen.push({ body: await request.json() });
        return HttpResponse.json(
          {
            txn_id: 'x',
            creator_id: ME,
            name: 'x',
            type: 'expense',
            amount: '30.00',
            currency: 'USD',
            txn_date: '2026-04-29',
            note: '',
            split_method: 'amount',
            members: [],
            payers: [],
            created_at: '2026-04-29T20:00:00Z',
            updated_at: '2026-04-29T20:00:00Z',
            deleted_at: null,
          },
          { status: 201 },
        );
      }),
    );
    return seen;
  }

  it('switches to amount split and submits per-member owed_amounts', async () => {
    const seen = captureBody();
    renderSheet();
    await waitFor(() =>
      expect(screen.getByTestId('add-txn-member-01J0000000000000000000BOB')).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByTestId('add-txn-name'), { target: { value: 'Groceries' } });
    fireEvent.change(screen.getByTestId('add-txn-amount'), { target: { value: '45.50' } });
    fireEvent.click(screen.getByTestId('add-txn-member-01J0000000000000000000BOB'));
    fireEvent.click(screen.getByTestId('add-txn-split-amount'));
    fireEvent.change(screen.getByTestId(`add-txn-member-owed_amount-${ME}`), {
      target: { value: '20.00' },
    });
    fireEvent.change(screen.getByTestId('add-txn-member-owed_amount-01J0000000000000000000BOB'), {
      target: { value: '25.50' },
    });
    fireEvent.click(screen.getByTestId('add-txn-submit'));
    await waitFor(() => expect(seen).toHaveLength(1));
    const body = seen[0]?.body as {
      split_method: string;
      members: { user_id: string; owed_amount: string | null; share: null; percent: null }[];
    };
    expect(body.split_method).toBe('amount');
    expect(body.members.find((m) => m.user_id === ME)?.owed_amount).toBe('20.00');
    expect(body.members.find((m) => m.user_id === '01J0000000000000000000BOB')?.owed_amount).toBe(
      '25.50',
    );
  });

  it('share split sends per-member shares and clears amount/percent fields', async () => {
    const seen = captureBody();
    renderSheet();
    await waitFor(() =>
      expect(screen.getByTestId('add-txn-member-01J0000000000000000000BOB')).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByTestId('add-txn-name'), { target: { value: 'Cab' } });
    fireEvent.change(screen.getByTestId('add-txn-amount'), { target: { value: '10.00' } });
    fireEvent.click(screen.getByTestId('add-txn-member-01J0000000000000000000BOB'));
    fireEvent.click(screen.getByTestId('add-txn-split-share'));
    fireEvent.change(screen.getByTestId(`add-txn-member-share-${ME}`), {
      target: { value: '1' },
    });
    fireEvent.change(screen.getByTestId('add-txn-member-share-01J0000000000000000000BOB'), {
      target: { value: '2' },
    });
    fireEvent.click(screen.getByTestId('add-txn-submit'));
    await waitFor(() => expect(seen).toHaveLength(1));
    const body = seen[0]?.body as {
      split_method: string;
      members: { user_id: string; share: string | null; owed_amount: null; percent: null }[];
    };
    expect(body.split_method).toBe('share');
    expect(body.members.find((m) => m.user_id === ME)?.share).toBe('1');
    expect(body.members.find((m) => m.user_id === ME)?.owed_amount).toBeNull();
    expect(body.members.find((m) => m.user_id === ME)?.percent).toBeNull();
  });

  it('percent split sends per-member percent', async () => {
    const seen = captureBody();
    renderSheet();
    await waitFor(() =>
      expect(screen.getByTestId('add-txn-member-01J0000000000000000000BOB')).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByTestId('add-txn-name'), { target: { value: 'Concert' } });
    fireEvent.change(screen.getByTestId('add-txn-amount'), { target: { value: '120.00' } });
    fireEvent.click(screen.getByTestId('add-txn-member-01J0000000000000000000BOB'));
    fireEvent.click(screen.getByTestId('add-txn-split-percent'));
    fireEvent.change(screen.getByTestId(`add-txn-member-percent-${ME}`), {
      target: { value: '40' },
    });
    fireEvent.change(screen.getByTestId('add-txn-member-percent-01J0000000000000000000BOB'), {
      target: { value: '60' },
    });
    fireEvent.click(screen.getByTestId('add-txn-submit'));
    await waitFor(() => expect(seen).toHaveLength(1));
    const body = seen[0]?.body as {
      split_method: string;
      members: { user_id: string; percent: string | null }[];
    };
    expect(body.split_method).toBe('percent');
    expect(body.members.find((m) => m.user_id === ME)?.percent).toBe('40');
  });

  it('hides split-method picker on settlement and forces amount split', async () => {
    renderSheet();
    await waitFor(() =>
      expect(screen.getByTestId('add-txn-member-01J0000000000000000000BOB')).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId('add-txn-type-settlement'));
    expect(screen.queryByTestId('add-txn-split')).not.toBeInTheDocument();
    expect(screen.queryByTestId('add-txn-payer-mode')).not.toBeInTheDocument();
  });
});

describe('AddTransactionSheet — multi-payer control', () => {
  it('submits per-payer amounts when in multiple mode', async () => {
    const seen: { body: unknown }[] = [];
    server.use(
      http.post(`${BASE}/transactions`, async ({ request }) => {
        seen.push({ body: await request.json() });
        return HttpResponse.json(
          {
            txn_id: 'x',
            creator_id: ME,
            name: 'x',
            type: 'expense',
            amount: '200.00',
            currency: 'USD',
            txn_date: '2026-04-29',
            note: '',
            split_method: 'equal',
            members: [],
            payers: [],
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
    fireEvent.change(screen.getByTestId('add-txn-name'), { target: { value: 'Hotel' } });
    fireEvent.change(screen.getByTestId('add-txn-amount'), { target: { value: '200.00' } });
    fireEvent.click(screen.getByTestId('add-txn-member-01J0000000000000000000BOB'));
    fireEvent.click(screen.getByTestId('add-txn-payer-mode-multiple'));
    fireEvent.change(screen.getByTestId(`add-txn-payer-amount-${ME}`), {
      target: { value: '120.00' },
    });
    fireEvent.change(screen.getByTestId('add-txn-payer-amount-01J0000000000000000000BOB'), {
      target: { value: '80.00' },
    });
    fireEvent.click(screen.getByTestId('add-txn-submit'));
    await waitFor(() => expect(seen).toHaveLength(1));
    const body = seen[0]?.body as {
      payers: { user_id: string; paid_amount: string }[];
    };
    expect(body.payers).toHaveLength(2);
    expect(body.payers.find((p) => p.user_id === ME)?.paid_amount).toBe('120.00');
    expect(body.payers.find((p) => p.user_id === '01J0000000000000000000BOB')?.paid_amount).toBe(
      '80.00',
    );
  });

  it('shows a payers field error if multiple is selected with no amounts entered', async () => {
    renderSheet();
    await waitFor(() =>
      expect(screen.getByTestId('add-txn-member-01J0000000000000000000BOB')).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByTestId('add-txn-name'), { target: { value: 'Hotel' } });
    fireEvent.change(screen.getByTestId('add-txn-amount'), { target: { value: '50.00' } });
    fireEvent.click(screen.getByTestId('add-txn-member-01J0000000000000000000BOB'));
    fireEvent.click(screen.getByTestId('add-txn-payer-mode-multiple'));
    fireEvent.click(screen.getByTestId('add-txn-submit'));
    await waitFor(() => expect(screen.getByTestId('add-txn-payers-error')).toBeInTheDocument());
  });
});

describe('AddTransactionSheet — type control', () => {
  it('switching to settlement collapses members to two and forces amount split', async () => {
    const seen: { body: unknown }[] = [];
    server.use(
      http.post(`${BASE}/transactions`, async ({ request }) => {
        seen.push({ body: await request.json() });
        return HttpResponse.json(
          {
            txn_id: 'x',
            creator_id: ME,
            name: 'x',
            type: 'settlement',
            amount: '10.00',
            currency: 'USD',
            txn_date: '2026-04-29',
            note: '',
            split_method: 'amount',
            members: [],
            payers: [],
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
    fireEvent.change(screen.getByTestId('add-txn-name'), { target: { value: 'Settle' } });
    fireEvent.change(screen.getByTestId('add-txn-amount'), { target: { value: '10.00' } });
    fireEvent.click(screen.getByTestId('add-txn-member-01J0000000000000000000BOB'));
    fireEvent.click(screen.getByTestId('add-txn-type-settlement'));
    fireEvent.click(screen.getByTestId('add-txn-submit'));
    await waitFor(() => expect(seen).toHaveLength(1));
    const body = seen[0]?.body as {
      type: string;
      split_method: string;
      members: {
        user_id: string;
        owed_amount: string | null;
        share: string | null;
        percent: string | null;
      }[];
      payers: { user_id: string; paid_amount: string }[];
    };
    expect(body.type).toBe('settlement');
    expect(body.split_method).toBe('amount');
    expect(body.members).toHaveLength(2);

    // Server contract for settlement (validate_create_payload):
    //   payer member's owed_amount === '0.00'
    //   the other member's owed_amount === full amount
    //   share + percent are null on every member
    const payerMember = body.members.find((m) => m.user_id === ME);
    const otherMember = body.members.find((m) => m.user_id !== ME);
    expect(payerMember?.owed_amount).toBe('0.00');
    expect(otherMember?.owed_amount).toBe('10.00');
    expect(payerMember?.share).toBeNull();
    expect(payerMember?.percent).toBeNull();
    expect(otherMember?.share).toBeNull();
    expect(otherMember?.percent).toBeNull();

    // Settlement is always single-payer.
    expect(body.payers).toHaveLength(1);
    expect(body.payers[0]?.user_id).toBe(ME);
    expect(body.payers[0]?.paid_amount).toBe('10.00');
  });

  it('Phase 5: edit-mode hydrates from existing txn and PUTs with If-Match', async () => {
    const seen: { ifMatch: string | null; body: unknown }[] = [];
    server.use(
      http.put(`${BASE}/transactions/:txnId`, async ({ request }) => {
        seen.push({
          ifMatch: request.headers.get('if-match'),
          body: await request.json(),
        });
        return HttpResponse.json(
          {
            txn_id: 'tx1',
            creator_id: ME,
            name: 'Dinner edited',
            type: 'expense',
            amount: '40.00',
            currency: 'USD',
            txn_date: '2026-04-29',
            note: '',
            split_method: 'equal',
            members: [
              { user_id: ME, owed_amount: '20.00', share: null, percent: null },
              {
                user_id: '01J0000000000000000000BOB',
                owed_amount: '20.00',
                share: null,
                percent: null,
              },
            ],
            payers: [{ user_id: ME, paid_amount: '40.00' }],
            created_at: '2026-04-29T20:00:00Z',
            updated_at: '2026-04-29T20:05:00Z',
            deleted_at: null,
          },
          { status: 200 },
        );
      }),
    );
    const existing = {
      txn_id: 'tx1',
      creator_id: ME,
      name: 'Dinner',
      type: 'expense' as const,
      amount: '30.00',
      currency: 'USD' as const,
      txn_date: '2026-04-29',
      note: '',
      split_method: 'equal' as const,
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
    };
    render(
      withProviders(
        <>
          <AddTransactionSheet open onClose={() => {}} existing={existing as never} />
          <Toaster />
        </>,
      ),
    );
    await waitFor(() => expect(screen.getByTestId('add-txn-name')).toHaveValue('Dinner'));
    expect(screen.getByTestId('add-txn-amount')).toHaveValue('30.00');
    fireEvent.change(screen.getByTestId('add-txn-amount'), { target: { value: '40.00' } });
    fireEvent.click(screen.getByTestId('add-txn-submit'));
    await waitFor(() => expect(seen).toHaveLength(1));
    expect(seen[0]?.ifMatch).toBe('2026-04-29T20:00:00Z');
    const updateBody = seen[0]?.body as { name: string; amount: string };
    expect(updateBody.amount).toBe('40.00');
  });

  it('Phase 5: PRECONDITION_FAILED on edit surfaces the refresh banner', async () => {
    server.use(
      http.put(`${BASE}/transactions/:txnId`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'PRECONDITION_FAILED',
              message: 'stale',
              request_id: 'r',
            },
          },
          { status: 412 },
        ),
      ),
    );
    const existing = {
      txn_id: 'tx1',
      creator_id: ME,
      name: 'Dinner',
      type: 'expense' as const,
      amount: '30.00',
      currency: 'USD' as const,
      txn_date: '2026-04-29',
      note: '',
      split_method: 'equal' as const,
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
    };
    render(
      withProviders(
        <>
          <AddTransactionSheet open onClose={() => {}} existing={existing as never} />
          <Toaster />
        </>,
      ),
    );
    await waitFor(() => expect(screen.getByTestId('add-txn-name')).toHaveValue('Dinner'));
    fireEvent.click(screen.getByTestId('add-txn-submit'));
    await waitFor(() => expect(screen.getByTestId('add-txn-banner')).toHaveTextContent(/changed/i));
  });

  it('reverting to expense resets split_method to equal so per-member rows do not appear', async () => {
    renderSheet();
    await waitFor(() =>
      expect(screen.getByTestId('add-txn-member-01J0000000000000000000BOB')).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId('add-txn-member-01J0000000000000000000BOB'));
    fireEvent.click(screen.getByTestId('add-txn-type-settlement'));
    // Split picker is hidden in settlement mode.
    expect(screen.queryByTestId('add-txn-split')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('add-txn-type-expense'));
    // Back in expense mode, split picker appears, equal is active,
    // and the per-member input rows are hidden (they only appear for
    // amount/share/percent).
    expect(screen.getByTestId('add-txn-split')).toBeInTheDocument();
    expect(screen.queryByTestId('add-txn-member-inputs')).not.toBeInTheDocument();
  });
});
