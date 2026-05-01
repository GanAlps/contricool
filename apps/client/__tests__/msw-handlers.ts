import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';

// Absolute base — matches the test-setup `EXPO_PUBLIC_API_BASE_URL`.
// openapi-fetch resolves request URLs through `new URL(...)` which
// requires absolute bases, so MSW handlers must match the same.
const BASE = 'http://localhost/v1';

type SignupBody = {
  email: string;
  password: string;
  name: string;
  currency: string;
  phone?: string;
};
type LoginBody = { email: string; password: string };

export const defaultHandlers = [
  http.post(`${BASE}/auth/signup`, async ({ request }) => {
    const body = (await request.json()) as SignupBody;
    return HttpResponse.json(
      { user_id: '01J0000000000000000000000', status: 'PENDING_VERIFICATION', _email: body.email },
      { status: 202 },
    );
  }),
  http.post(`${BASE}/auth/verify-email`, async () =>
    HttpResponse.json({ email_verified: true, account_active: true }, { status: 200 }),
  ),
  http.post(`${BASE}/auth/resend-email-code`, async () =>
    HttpResponse.json({ status: 'RESENT' }, { status: 202 }),
  ),
  http.post(`${BASE}/auth/login`, async ({ request }) => {
    const body = (await request.json()) as LoginBody;
    // Mirror the backend's X-Client-Platform header behavior so native
    // tests see the same wire shape they will in production.
    const isNative = (request.headers.get('x-client-platform') ?? '').toLowerCase() === 'native';
    return HttpResponse.json(
      {
        access_token: 'access-jwt',
        id_token: 'id-jwt',
        expires_in: 3600,
        user: {
          user_id: '01J0000000000000000000000',
          name: 'Alice',
          currency: 'USD',
          _email: body.email,
        },
        refresh_token: isNative ? 'refresh-token-from-body' : null,
      },
      {
        status: 200,
        headers: isNative
          ? {}
          : {
              'set-cookie':
                'rt=refresh-token; HttpOnly; Secure; SameSite=Strict; Path=/v1/auth; Max-Age=2592000',
            },
      },
    );
  }),
  http.post(`${BASE}/auth/refresh`, async ({ request }) => {
    // Mirror backend: native sends refresh_token in body; web sends
    // empty body and relies on the HttpOnly cookie. Either path
    // returns the same RefreshResponse shape.
    let body: { refresh_token?: string | null } | null = null;
    if ((request.headers.get('content-type') ?? '').includes('application/json')) {
      try {
        body = (await request.json()) as { refresh_token?: string | null };
      } catch {
        body = null;
      }
    }
    if (
      (request.headers.get('x-client-platform') ?? '').toLowerCase() === 'native' &&
      !body?.refresh_token
    ) {
      return HttpResponse.json(
        {
          error: {
            code: 'MISSING_REFRESH_TOKEN',
            message: 'no refresh token',
            request_id: 'r',
          },
        },
        { status: 401 },
      );
    }
    return HttpResponse.json(
      { access_token: 'access-jwt-2', id_token: 'id-jwt-2', expires_in: 3600 },
      { status: 200 },
    );
  }),
  http.post(`${BASE}/auth/logout`, async ({ request }) => {
    // Phase 2c R6.1 + PR #22 two-token contract: logout requires
    //   Authorization: Bearer <id_token>
    //   X-Cognito-Access-Token: <access_token>
    // Mirror the backend so future client regressions show up here.
    if (!request.headers.get('authorization')?.startsWith('Bearer ')) {
      return HttpResponse.json(
        { error: { code: 'UNAUTHENTICATED', message: 'no bearer', request_id: 'r' } },
        { status: 401 },
      );
    }
    if (!request.headers.get('x-cognito-access-token')) {
      return HttpResponse.json(
        {
          error: {
            code: 'MISSING_ACCESS_TOKEN',
            message: 'access token required',
            request_id: 'r',
          },
        },
        { status: 400 },
      );
    }
    return new HttpResponse(null, { status: 204 });
  }),
  http.post(`${BASE}/auth/forgot-password`, async () =>
    HttpResponse.json({ status: 'RESET_CODE_SENT' }, { status: 202 }),
  ),
  http.post(`${BASE}/auth/reset-password`, async () =>
    HttpResponse.json({ password_reset: true }, { status: 200 }),
  ),
  http.get(`${BASE}/friends`, async () =>
    HttpResponse.json(
      {
        items: [
          {
            user_id: '01J0000000000000000000ALI',
            name: 'Alice',
            currency: 'USD',
            since: '2026-04-01T00:00:00Z',
            balance: { net: '0.00', settlement_status: 'settled' },
          },
          {
            user_id: '01J0000000000000000000BOB',
            name: 'Bob',
            currency: 'USD',
            since: '2026-04-02T00:00:00Z',
            balance: { net: '0.00', settlement_status: 'settled' },
          },
        ],
        next_cursor: null,
      },
      { status: 200 },
    ),
  ),
  http.post(`${BASE}/friends/add`, async ({ request }) => {
    // `_email` is a leading-underscore echo for tests that want to
    // assert the request body without intercepting the request — the
    // SDK strips unknown keys, so it never reaches screens.
    const body = (await request.json()) as { email: string };
    return HttpResponse.json(
      {
        user_id: '01J0000000000000000000NEW',
        name: 'Newbie',
        currency: 'USD',
        since: '2026-04-29T12:00:00Z',
        _email: body.email,
      },
      { status: 200 },
    );
  }),
  http.get(`${BASE}/friends/:userId/balance`, async ({ params }) =>
    HttpResponse.json(
      {
        user_id: params.userId,
        currency: 'USD',
        // Two-decimal Decimal shape — matches the Pydantic-serialised
        // value the live backend returns. Tests asserting `0.00 USD`
        // depend on this.
        net: '0.00',
        settlement_status: 'settled',
        last_transaction_at: null,
      },
      { status: 200 },
    ),
  ),
  http.delete(`${BASE}/friends/:userId`, async () => new HttpResponse(null, { status: 204 })),
  // ---- Phase 4c transactions surface ----
  http.get(`${BASE}/transactions`, async () =>
    HttpResponse.json(
      {
        items: [
          {
            txn_id: '01J0000000000000000000TX1',
            name: 'Dinner',
            type: 'expense',
            amount: '30.00',
            currency: 'USD',
            txn_date: '2026-04-29',
            split_method: 'equal',
            creator_id: '01J0000000000000000000ALI',
            my_owed_amount: '10.00',
            my_paid_amount: '0.00',
            created_at: '2026-04-29T20:00:00Z',
          },
        ],
        next_cursor: null,
      },
      { status: 200 },
    ),
  ),
  http.get(`${BASE}/transactions/:txnId`, async ({ params }) => {
    const id = String(params.txnId);
    return HttpResponse.json(
      {
        txn_id: id,
        creator_id: '01J0000000000000000000ALI',
        name: 'Dinner',
        type: 'expense',
        amount: '30.00',
        currency: 'USD',
        txn_date: '2026-04-29',
        note: '',
        split_method: 'equal',
        members: [
          {
            user_id: '01J0000000000000000000ALI',
            owed_amount: '10.00',
            share: null,
            percent: null,
          },
          {
            user_id: '01J0000000000000000000BOB',
            owed_amount: '10.00',
            share: null,
            percent: null,
          },
          {
            user_id: '01J0000000000000000000CAR',
            owed_amount: '10.00',
            share: null,
            percent: null,
          },
        ],
        payers: [{ user_id: '01J0000000000000000000ALI', paid_amount: '30.00' }],
        created_at: '2026-04-29T20:00:00Z',
        updated_at: '2026-04-29T20:00:00Z',
        deleted_at: null,
      },
      { status: 200 },
    );
  }),
  http.post(`${BASE}/transactions`, async ({ request }) => {
    type CreateBody = {
      name: string;
      type: string;
      amount: string;
      currency: string;
      txn_date: string;
      split_method: string;
      members: { user_id: string }[];
      payers: { user_id: string; paid_amount: string }[];
    };
    const idempotencyKey = request.headers.get('idempotency-key') ?? '';
    if (!idempotencyKey) {
      return HttpResponse.json(
        {
          error: {
            code: 'IDEMPOTENCY_KEY_REQUIRED',
            message: 'header required',
            request_id: 'r',
          },
        },
        { status: 400 },
      );
    }
    const body = (await request.json()) as CreateBody;
    return HttpResponse.json(
      {
        txn_id: '01J0000000000000000000NEW',
        creator_id: body.members[0]?.user_id,
        name: body.name,
        type: body.type,
        amount: body.amount,
        currency: body.currency,
        txn_date: body.txn_date,
        note: '',
        split_method: body.split_method,
        members: body.members.map((m) => ({
          user_id: m.user_id,
          owed_amount: '0.00',
          share: null,
          percent: null,
        })),
        payers: body.payers,
        created_at: '2026-04-29T20:00:00Z',
        updated_at: '2026-04-29T20:00:00Z',
        deleted_at: null,
      },
      { status: 201 },
    );
  }),
];

export const server = setupServer(...defaultHandlers);
