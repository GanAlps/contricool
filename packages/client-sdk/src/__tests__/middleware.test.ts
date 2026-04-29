import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiErrorException } from '../errors';
import { authMiddleware } from '../middleware';

type FetchMock = ReturnType<typeof vi.fn<typeof fetch>>;

let fetchMock: FetchMock;

function jsonRes(body: unknown, status = 200, headers?: Record<string, string>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', ...headers },
  });
}

function makeMw(
  overrides: Partial<Parameters<typeof authMiddleware>[0]> = {},
): ReturnType<typeof authMiddleware> {
  return authMiddleware({
    getTokens: () => null,
    onUnauthenticated: () => {},
    ...overrides,
  });
}

beforeEach(() => {
  fetchMock = vi.fn() as unknown as FetchMock;
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('authMiddleware.onRequest', () => {
  it('attaches Authorization on non-/auth/ paths when a token is available', async () => {
    const mw = makeMw({ getTokens: () => ({ accessToken: 'tok-1', idToken: 'id-1' }) });
    const req = new Request('http://localhost/v1/me', { method: 'GET' });
    const out = (await mw.onRequest!({
      request: req,
      schemaPath: '',
      params: {},
    } as never)) as Request;
    expect(out.headers.get('authorization')).toBe('Bearer id-1');
  });

  it('attaches both id and access tokens on /auth/logout (Phase 2c two-token contract)', async () => {
    // Backend (PR #22) requires:
    //   Authorization: Bearer <id_token>
    //   X-Cognito-Access-Token: <access_token>
    // Without either, logout 401s, GlobalSignOut never fires, and the
    // refresh cookie isn't cleared — hard-reload re-hydrates the session.
    const mw = makeMw({ getTokens: () => ({ accessToken: 'tok-1', idToken: 'id-1' }) });
    const req = new Request('http://localhost/v1/auth/logout', { method: 'POST' });
    const out = (await mw.onRequest!({
      request: req,
      schemaPath: '',
      params: {},
    } as never)) as Request;
    expect(out.headers.get('authorization')).toBe('Bearer id-1');
    expect(out.headers.get('x-cognito-access-token')).toBe('tok-1');
  });

  it('attaches Authorization on /auth/login but no X-Cognito-Access-Token', async () => {
    const mw = makeMw({ getTokens: () => ({ accessToken: 'tok-1', idToken: 'id-1' }) });
    const req = new Request('http://localhost/v1/auth/login', { method: 'POST' });
    const out = (await mw.onRequest!({
      request: req,
      schemaPath: '',
      params: {},
    } as never)) as Request;
    expect(out.headers.get('authorization')).toBe('Bearer id-1');
    expect(out.headers.get('x-cognito-access-token')).toBeNull();
  });

  it('skips Authorization when no token is available', async () => {
    const mw = makeMw();
    const req = new Request('http://localhost/v1/me');
    const out = (await mw.onRequest!({
      request: req,
      schemaPath: '',
      params: {},
    } as never)) as Request;
    expect(out.headers.get('authorization')).toBeNull();
  });
});

describe('authMiddleware.onResponse', () => {
  it('passes through 2xx responses unchanged', async () => {
    const mw = makeMw();
    const req = new Request('http://localhost/v1/me');
    const res = jsonRes({ ok: true }, 200);
    const out = await mw.onResponse!({
      request: req,
      response: res,
      schemaPath: '',
      params: {},
    } as never);
    expect(out).toBe(res);
  });

  it('throws ApiErrorException for envelope-shaped 4xx', async () => {
    const mw = makeMw();
    const req = new Request('http://localhost/v1/auth/login');
    const res = jsonRes(
      { error: { code: 'INVALID_CREDENTIALS', message: 'nope', request_id: 'r' } },
      401,
    );
    await expect(
      mw.onResponse!({ request: req, response: res, schemaPath: '', params: {} } as never),
    ).rejects.toBeInstanceOf(ApiErrorException);
  });

  it('does NOT trigger refresh-and-retry on /auth/* 401 (regression of N4)', async () => {
    const onUnauth = vi.fn();
    const onRefreshed = vi.fn();
    const mw = makeMw({ onUnauthenticated: onUnauth, onTokenRefreshed: onRefreshed });
    const req = new Request('http://localhost/v1/auth/login', { method: 'POST' });
    const res = jsonRes(
      { error: { code: 'INVALID_CREDENTIALS', message: 'nope', request_id: 'r' } },
      401,
    );
    await expect(
      mw.onResponse!({ request: req, response: res, schemaPath: '', params: {} } as never),
    ).rejects.toMatchObject({ error: { code: 'INVALID_CREDENTIALS' } });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(onUnauth).not.toHaveBeenCalled();
    expect(onRefreshed).not.toHaveBeenCalled();
  });

  it('handles a POST whose body clone throws (defensive REPLAY_BODY catch)', async () => {
    const mw = makeMw({ getTokens: () => ({ accessToken: 't', idToken: 'id' }) });
    const req = new Request('http://localhost/v1/transactions', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: '{"x":1}',
    });
    Object.defineProperty(req, 'clone', {
      value: () => {
        throw new Error('clone unavailable');
      },
    });
    // Should not throw — the defensive catch sets the slot to null.
    await mw.onRequest!({ request: req, schemaPath: '', params: {} } as never);
    expect(req.headers.get('authorization')).toBe('Bearer id');
  });

  it('replays a POST 401 with the original body intact (B1 regression)', async () => {
    const onRefreshed = vi.fn();
    const mw = makeMw({
      getTokens: () => ({ accessToken: 'old-token', idToken: 'old-id' }),
      onTokenRefreshed: onRefreshed,
    });
    fetchMock.mockResolvedValueOnce(
      jsonRes({ access_token: 'new-token', id_token: 'new-id', expires_in: 3600 }, 200),
    );
    fetchMock.mockResolvedValueOnce(jsonRes({ ok: true }, 200));
    const originalBody = JSON.stringify({ note: 'lunch', amount: 12.5 });
    // Real flow: openapi-fetch invokes onRequest before sending. We
    // simulate the same lifecycle here so the body capture in onRequest
    // happens, then the body is "consumed" by the simulated send, then
    // onResponse's retry path uses the captured body.
    const req = new Request('http://localhost/v1/transactions', {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: 'Bearer old-token' },
      body: originalBody,
    });
    await mw.onRequest!({ request: req, schemaPath: '', params: {} } as never);
    // Drain the original body to mimic the first failed send.
    await req.text();
    const res = jsonRes(
      { error: { code: 'UNAUTHENTICATED', message: 'expired', request_id: 'r' } },
      401,
    );
    const out = (await mw.onResponse!({
      request: req,
      response: res,
      schemaPath: '',
      params: {},
    } as never)) as Response;
    expect(out.status).toBe(200);
    // Two fetches happened: refresh + replay.
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const replayCall = fetchMock.mock.calls[1]?.[0] as Request;
    const replayBody = await replayCall.text();
    expect(replayBody).toBe(originalBody);
    expect(replayCall.method).toBe('POST');
    expect(replayCall.headers.get('authorization')).toBe('Bearer new-id');
    expect(replayCall.headers.get('content-type')).toBe('application/json');
  });

  it('refresh succeeds → retries original with new bearer → returns retry response (N3)', async () => {
    const onRefreshed = vi.fn();
    const mw = makeMw({
      getTokens: () => ({ accessToken: 'old-token', idToken: 'old-id' }),
      onTokenRefreshed: onRefreshed,
    });
    fetchMock.mockResolvedValueOnce(
      jsonRes({ access_token: 'new-token', id_token: 'new-id', expires_in: 3600 }, 200),
    );
    fetchMock.mockResolvedValueOnce(jsonRes({ user_id: 'u1' }, 200));
    const req = new Request('http://localhost/v1/me', {
      method: 'GET',
      headers: { authorization: 'Bearer old-token' },
    });
    const res = jsonRes(
      { error: { code: 'UNAUTHENTICATED', message: 'expired', request_id: 'r' } },
      401,
    );
    const out = (await mw.onResponse!({
      request: req,
      response: res,
      schemaPath: '',
      params: {},
    } as never)) as Response;
    const body = (await out.json()) as { user_id: string };
    expect(body.user_id).toBe('u1');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const refreshCall = fetchMock.mock.calls[0]?.[0] as Request;
    expect(refreshCall.url).toBe('http://localhost/v1/auth/refresh');
    const replayCall = fetchMock.mock.calls[1]?.[0] as Request;
    expect(replayCall.headers.get('authorization')).toBe('Bearer new-id');
    expect(onRefreshed).toHaveBeenCalledWith({
      access_token: 'new-token',
      id_token: 'new-id',
      expires_in: 3600,
    });
  });

  it('refresh fails → onUnauthenticated called → original 401 surfaced', async () => {
    const onUnauth = vi.fn();
    const mw = makeMw({
      getTokens: () => ({ accessToken: 'old-token', idToken: 'old-id' }),
      onUnauthenticated: onUnauth,
    });
    fetchMock.mockResolvedValueOnce(
      jsonRes({ error: { code: 'REFRESH_FAILED', message: 'nope', request_id: 'r2' } }, 401),
    );
    const req = new Request('http://localhost/v1/me');
    const res = jsonRes(
      { error: { code: 'UNAUTHENTICATED', message: 'gone', request_id: 'r1' } },
      401,
    );
    await expect(
      mw.onResponse!({ request: req, response: res, schemaPath: '', params: {} } as never),
    ).rejects.toMatchObject({ error: { code: 'UNAUTHENTICATED' } });
    expect(onUnauth).toHaveBeenCalledOnce();
  });

  it('refresh network error is treated as a refresh failure', async () => {
    const onUnauth = vi.fn();
    const mw = makeMw({
      getTokens: () => ({ accessToken: 't', idToken: 'id' }),
      onUnauthenticated: onUnauth,
    });
    fetchMock.mockRejectedValueOnce(new Error('network'));
    const req = new Request('http://localhost/v1/me');
    const res = jsonRes({ error: { code: 'UNAUTHENTICATED', message: 'x', request_id: 'r' } }, 401);
    await expect(
      mw.onResponse!({ request: req, response: res, schemaPath: '', params: {} } as never),
    ).rejects.toMatchObject({ error: { code: 'UNAUTHENTICATED' } });
    expect(onUnauth).toHaveBeenCalledOnce();
  });

  it('onUnauthenticated errors are swallowed', async () => {
    const mw = makeMw({
      getTokens: () => ({ accessToken: 't', idToken: 'id' }),
      onUnauthenticated: () => {
        throw new Error('boom');
      },
    });
    fetchMock.mockResolvedValueOnce(
      jsonRes({ error: { code: 'REFRESH_FAILED', message: 'x', request_id: 'r' } }, 401),
    );
    const req = new Request('http://localhost/v1/me');
    const res = jsonRes({ error: { code: 'UNAUTHENTICATED', message: 'x', request_id: 'r' } }, 401);
    await expect(
      mw.onResponse!({ request: req, response: res, schemaPath: '', params: {} } as never),
    ).rejects.toMatchObject({ error: { code: 'UNAUTHENTICATED' } });
  });

  it('uses the injected refreshUrl when provided', async () => {
    const refreshUrl = vi.fn(() => 'http://example.com/special-refresh');
    const mw = makeMw({ getTokens: () => ({ accessToken: 't', idToken: 'id' }), refreshUrl });
    fetchMock.mockResolvedValueOnce(
      jsonRes({ access_token: 'x', id_token: 'y', expires_in: 1 }, 200),
    );
    fetchMock.mockResolvedValueOnce(jsonRes({ ok: true }, 200));
    const req = new Request('http://example.com/v1/me');
    const res = jsonRes({ error: { code: 'UNAUTHENTICATED', message: 'x', request_id: 'r' } }, 401);
    await mw.onResponse!({ request: req, response: res, schemaPath: '', params: {} } as never);
    expect(refreshUrl).toHaveBeenCalled();
    const refreshCall = fetchMock.mock.calls[0]?.[0] as Request;
    expect(refreshCall.url).toBe('http://example.com/special-refresh');
  });

  it('falls back to a host-relative refresh path when no version prefix is found', async () => {
    const mw = makeMw({ getTokens: () => ({ accessToken: 't', idToken: 'id' }) });
    fetchMock.mockResolvedValueOnce(
      jsonRes({ access_token: 'x', id_token: 'y', expires_in: 1 }, 200),
    );
    fetchMock.mockResolvedValueOnce(jsonRes({ ok: true }, 200));
    const req = new Request('http://example.com/me-without-prefix');
    const res = jsonRes({ error: { code: 'UNAUTHENTICATED', message: 'x', request_id: 'r' } }, 401);
    await mw.onResponse!({ request: req, response: res, schemaPath: '', params: {} } as never);
    const refreshCall = fetchMock.mock.calls[0]?.[0] as Request;
    expect(refreshCall.url).toBe('http://example.com/auth/refresh');
  });

  it('builds same-origin refresh path for relative URLs', async () => {
    const mw = makeMw({ getTokens: () => ({ accessToken: 't', idToken: 'id' }) });
    fetchMock.mockResolvedValueOnce(
      jsonRes({ access_token: 'x', id_token: 'y', expires_in: 1 }, 200),
    );
    fetchMock.mockResolvedValueOnce(jsonRes({ ok: true }, 200));
    // jsdom resolves `/v1/me` against window.location.
    const req = new Request('http://localhost/v1/me');
    const res = jsonRes({ error: { code: 'UNAUTHENTICATED', message: 'x', request_id: 'r' } }, 401);
    await mw.onResponse!({ request: req, response: res, schemaPath: '', params: {} } as never);
    const refreshCall = fetchMock.mock.calls[0]?.[0] as Request;
    expect(refreshCall.url).toMatch(/\/v1\/auth\/refresh$/);
  });
});
