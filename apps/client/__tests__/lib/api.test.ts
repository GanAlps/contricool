import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { type ApiAuthAccessors, ApiErrorException, apiFetch, setApiAuthAccessors } from '~/lib/api';

import { server } from '../msw-handlers';

const BASE = '/v1';

function makeAccessors(initialToken: string | null = null): {
  accessors: ApiAuthAccessors;
  state: { token: string | null; refreshSet: number; signedOut: number };
} {
  const state = { token: initialToken, refreshSet: 0, signedOut: 0 };
  const accessors: ApiAuthAccessors = {
    getAccessToken: () => state.token,
    setTokensFromRefresh: ({ access_token }) => {
      state.token = access_token;
      state.refreshSet++;
    },
    forceSignOut: () => {
      state.signedOut++;
    },
  };
  return { accessors, state };
}

describe('apiFetch', () => {
  beforeEach(() => {
    setApiAuthAccessors(null);
  });
  afterEach(() => {
    setApiAuthAccessors(null);
  });

  it('attaches Authorization: Bearer when accessors return a token and auth is bearer', async () => {
    const { accessors, state } = makeAccessors('tok-1');
    setApiAuthAccessors(accessors);
    let receivedAuth: string | null = null;
    server.use(
      http.get(`${BASE}/things`, ({ request }) => {
        receivedAuth = request.headers.get('authorization');
        return HttpResponse.json({ ok: true });
      }),
    );
    await apiFetch('/things');
    expect(receivedAuth).toBe('Bearer tok-1');
    expect(state.token).toBe('tok-1');
  });

  it('skips Authorization when auth: public', async () => {
    const { accessors } = makeAccessors('tok-1');
    setApiAuthAccessors(accessors);
    let receivedAuth: string | null = '<unset>';
    server.use(
      http.post(`${BASE}/auth/login`, ({ request }) => {
        receivedAuth = request.headers.get('authorization');
        return HttpResponse.json({ ok: true });
      }),
    );
    await apiFetch('/auth/login', { method: 'POST', json: {}, auth: 'public' });
    expect(receivedAuth).toBeNull();
  });

  it('returns void on 204', async () => {
    server.use(http.post(`${BASE}/auth/logout`, () => new HttpResponse(null, { status: 204 })));
    setApiAuthAccessors(makeAccessors('tok-1').accessors);
    const result = await apiFetch('/auth/logout', { method: 'POST' });
    expect(result).toBeUndefined();
  });

  it('parses JSON on 200', async () => {
    server.use(http.get(`${BASE}/me`, () => HttpResponse.json({ user_id: 'u1' })));
    setApiAuthAccessors(makeAccessors('tok-1').accessors);
    const r = await apiFetch<{ user_id: string }>('/me');
    expect(r.user_id).toBe('u1');
  });

  it('throws ApiErrorException with envelope code on 4xx', async () => {
    server.use(
      http.post(`${BASE}/auth/login`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'INVALID_CREDENTIALS',
              message: 'Email or password is incorrect',
              request_id: 'req-1',
            },
          },
          { status: 401 },
        ),
      ),
    );
    setApiAuthAccessors(makeAccessors().accessors);
    await expect(
      apiFetch('/auth/login', { method: 'POST', json: {}, auth: 'public' }),
    ).rejects.toMatchObject({
      name: 'ApiErrorException',
      error: { code: 'INVALID_CREDENTIALS', http_status: 401 },
    });
  });

  it('synthesises NETWORK_ERROR on raw 5xx HTML body (N20)', async () => {
    server.use(http.get(`${BASE}/me`, () => new HttpResponse('<html>503</html>', { status: 503 })));
    setApiAuthAccessors(makeAccessors('tok-1').accessors);
    try {
      await apiFetch('/me');
      throw new Error('should have thrown');
    } catch (e) {
      expect(e).toBeInstanceOf(ApiErrorException);
      const ee = e as ApiErrorException;
      expect(ee.error.code).toBe('NETWORK_ERROR');
      expect(ee.error.request_id).toBeNull();
      expect(ee.error.http_status).toBe(503);
    }
  });

  it('handles empty 200 body as undefined', async () => {
    server.use(http.post(`${BASE}/ping`, () => new HttpResponse('', { status: 200 })));
    setApiAuthAccessors(makeAccessors().accessors);
    const r = await apiFetch('/ping', { method: 'POST', auth: 'public' });
    expect(r).toBeUndefined();
  });

  it('retries once after 401 → refresh succeeds → original returns (N17)', async () => {
    const { accessors, state } = makeAccessors('old-token');
    setApiAuthAccessors(accessors);
    let callCount = 0;
    server.use(
      http.get(`${BASE}/me`, ({ request }) => {
        callCount++;
        const auth = request.headers.get('authorization');
        if (auth === 'Bearer new-token') {
          return HttpResponse.json({ user_id: 'u1' });
        }
        return HttpResponse.json(
          { error: { code: 'UNAUTHENTICATED', message: 'expired', request_id: 'r1' } },
          { status: 401 },
        );
      }),
      http.post(`${BASE}/auth/refresh`, () =>
        HttpResponse.json({ access_token: 'new-token', id_token: 'new-id', expires_in: 3600 }),
      ),
    );
    const r = await apiFetch<{ user_id: string }>('/me');
    expect(r.user_id).toBe('u1');
    expect(callCount).toBe(2);
    expect(state.refreshSet).toBe(1);
    expect(state.token).toBe('new-token');
  });

  it('signs out and surfaces 401 when refresh also returns 401 (N18)', async () => {
    const { accessors, state } = makeAccessors('old-token');
    setApiAuthAccessors(accessors);
    server.use(
      http.get(`${BASE}/me`, () =>
        HttpResponse.json(
          { error: { code: 'UNAUTHENTICATED', message: 'expired', request_id: 'r1' } },
          { status: 401 },
        ),
      ),
      http.post(`${BASE}/auth/refresh`, () =>
        HttpResponse.json(
          { error: { code: 'REFRESH_FAILED', message: 'no refresh', request_id: 'r2' } },
          { status: 401 },
        ),
      ),
    );
    await expect(apiFetch('/me')).rejects.toMatchObject({
      error: { code: 'UNAUTHENTICATED', http_status: 401 },
    });
    expect(state.signedOut).toBe(1);
  });

  it('does NOT trigger refresh-and-retry on /v1/auth/login 401 (N19)', async () => {
    const { accessors, state } = makeAccessors();
    setApiAuthAccessors(accessors);
    let refreshCalled = 0;
    server.use(
      http.post(`${BASE}/auth/login`, () =>
        HttpResponse.json(
          { error: { code: 'INVALID_CREDENTIALS', message: 'nope', request_id: 'r1' } },
          { status: 401 },
        ),
      ),
      http.post(`${BASE}/auth/refresh`, () => {
        refreshCalled++;
        return HttpResponse.json({ access_token: 'x', id_token: 'y', expires_in: 1 });
      }),
    );
    await expect(
      apiFetch('/auth/login', { method: 'POST', json: {}, auth: 'public' }),
    ).rejects.toMatchObject({ error: { code: 'INVALID_CREDENTIALS' } });
    expect(refreshCalled).toBe(0);
    expect(state.signedOut).toBe(0);
  });

  it('preserves retry_after when present on 429', async () => {
    server.use(
      http.post(`${BASE}/auth/forgot-password`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'RATE_LIMITED',
              message: 'slow down',
              request_id: 'r1',
              retry_after: 60,
            },
          },
          { status: 429 },
        ),
      ),
    );
    setApiAuthAccessors(makeAccessors().accessors);
    try {
      await apiFetch('/auth/forgot-password', {
        method: 'POST',
        json: {},
        auth: 'public',
      });
      throw new Error('should have thrown');
    } catch (e) {
      const ee = e as ApiErrorException;
      expect(ee.error.code).toBe('RATE_LIMITED');
      expect(ee.error.retry_after).toBe(60);
    }
  });

  it('does not retry when accessors not configured', async () => {
    let calls = 0;
    server.use(
      http.get(`${BASE}/me`, () => {
        calls++;
        return HttpResponse.json(
          { error: { code: 'UNAUTHENTICATED', message: 'x', request_id: 'r1' } },
          { status: 401 },
        );
      }),
    );
    await expect(apiFetch('/me')).rejects.toBeInstanceOf(ApiErrorException);
    expect(calls).toBe(1);
  });

  it('does not retry when __noRetry is set', async () => {
    const { accessors, state } = makeAccessors('t');
    setApiAuthAccessors(accessors);
    let calls = 0;
    server.use(
      http.get(`${BASE}/me`, () => {
        calls++;
        return HttpResponse.json(
          { error: { code: 'UNAUTHENTICATED', message: 'x', request_id: 'r1' } },
          { status: 401 },
        );
      }),
    );
    await expect(apiFetch('/me', { __noRetry: true })).rejects.toBeInstanceOf(ApiErrorException);
    expect(calls).toBe(1);
    expect(state.signedOut).toBe(0);
  });

  it('falls through to NETWORK_ERROR when body is empty on a non-2xx', async () => {
    server.use(http.get(`${BASE}/me`, () => new HttpResponse(null, { status: 502 })));
    setApiAuthAccessors(makeAccessors('t').accessors);
    try {
      await apiFetch('/me');
      throw new Error('should have thrown');
    } catch (e) {
      const ee = e as ApiErrorException;
      expect(ee.error.code).toBe('NETWORK_ERROR');
      expect(ee.error.http_status).toBe(502);
    }
  });

  it('forceSignOut errors are swallowed', async () => {
    const accessors: ApiAuthAccessors = {
      getAccessToken: () => 't',
      setTokensFromRefresh: vi.fn(),
      forceSignOut: () => {
        throw new Error('boom');
      },
    };
    setApiAuthAccessors(accessors);
    server.use(
      http.get(`${BASE}/me`, () =>
        HttpResponse.json(
          { error: { code: 'UNAUTHENTICATED', message: 'x', request_id: 'r1' } },
          { status: 401 },
        ),
      ),
      http.post(`${BASE}/auth/refresh`, () =>
        HttpResponse.json(
          { error: { code: 'REFRESH_FAILED', message: 'x', request_id: 'r2' } },
          { status: 401 },
        ),
      ),
    );
    await expect(apiFetch('/me')).rejects.toMatchObject({
      error: { code: 'UNAUTHENTICATED' },
    });
  });

  it('handles empty error body via empty text path', async () => {
    server.use(http.get(`${BASE}/me`, () => new HttpResponse(null, { status: 500 })));
    setApiAuthAccessors(makeAccessors('t').accessors);
    try {
      await apiFetch('/me');
      throw new Error('should have thrown');
    } catch (e) {
      const ee = e as ApiErrorException;
      expect(ee.error.http_status).toBe(500);
      expect(ee.error.code).toBe('NETWORK_ERROR');
    }
  });

  it('parses an envelope without a request_id (defaults to null)', async () => {
    server.use(
      http.get(`${BASE}/things`, () =>
        HttpResponse.json({ error: { code: 'X', message: 'y' } }, { status: 400 }),
      ),
    );
    setApiAuthAccessors(makeAccessors('t').accessors);
    try {
      await apiFetch('/things');
      throw new Error('should have thrown');
    } catch (e) {
      const ee = e as ApiErrorException;
      expect(ee.error.request_id).toBeNull();
      expect(ee.error.details).toEqual([]);
    }
  });

  it('respects a caller-supplied content-type', async () => {
    let receivedCT: string | null = null;
    server.use(
      http.post(`${BASE}/raw`, ({ request }) => {
        receivedCT = request.headers.get('content-type');
        return HttpResponse.json({ ok: true });
      }),
    );
    setApiAuthAccessors(makeAccessors().accessors);
    await apiFetch('/raw', {
      method: 'POST',
      json: { x: 1 },
      auth: 'public',
      headers: { 'content-type': 'application/vnd.custom' },
    });
    expect(receivedCT).toBe('application/vnd.custom');
  });

  it('handles a Response whose .text() throws (defensive parseError catch)', async () => {
    // Stub fetch globally for this test only — bypasses MSW.
    const realFetch = globalThis.fetch;
    globalThis.fetch = (async () =>
      ({
        ok: false,
        status: 502,
        text: () => {
          throw new Error('stream broke');
        },
      }) as unknown as Response) as typeof fetch;
    try {
      setApiAuthAccessors(makeAccessors('t').accessors);
      try {
        await apiFetch('/me');
        throw new Error('should have thrown');
      } catch (e) {
        const ee = e as ApiErrorException;
        expect(ee.error.code).toBe('NETWORK_ERROR');
        expect(ee.error.http_status).toBe(502);
      }
    } finally {
      globalThis.fetch = realFetch;
    }
  });
});
