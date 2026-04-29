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
      },
      {
        status: 200,
        headers: {
          'set-cookie':
            'rt=refresh-token; HttpOnly; Secure; SameSite=Strict; Path=/v1/auth; Max-Age=2592000',
        },
      },
    );
  }),
  http.post(`${BASE}/auth/refresh`, async () =>
    HttpResponse.json(
      { access_token: 'access-jwt-2', id_token: 'id-jwt-2', expires_in: 3600 },
      { status: 200 },
    ),
  ),
  http.post(`${BASE}/auth/logout`, async () => new HttpResponse(null, { status: 204 })),
  http.post(`${BASE}/auth/forgot-password`, async () =>
    HttpResponse.json({ status: 'RESET_CODE_SENT' }, { status: 202 }),
  ),
  http.post(`${BASE}/auth/reset-password`, async () =>
    HttpResponse.json({ password_reset: true }, { status: 200 }),
  ),
];

export const server = setupServer(...defaultHandlers);
