import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createClient } from '../index';

type FetchMock = ReturnType<typeof vi.fn<typeof fetch>>;

let fetchMock: FetchMock;

function jsonRes(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

beforeEach(() => {
  fetchMock = vi.fn() as unknown as FetchMock;
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('createClient', () => {
  it('issues typed POSTs to /auth/login and returns the response data', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonRes(
        {
          access_token: 'a',
          id_token: 'i',
          expires_in: 3600,
          user: { user_id: 'u1', name: 'Alice', currency: 'USD' },
        },
        200,
      ),
    );
    const client = createClient({
      baseUrl: 'http://localhost/v1',
      getAccessToken: () => null,
      onUnauthenticated: () => {},
    });
    const r = await client.POST('/auth/login', {
      body: { email: 'a@b.com', password: 'P@ssword123!' },
    });
    expect(r.data?.user.name).toBe('Alice');
    expect(fetchMock).toHaveBeenCalledOnce();
    const callReq = fetchMock.mock.calls[0]?.[0] as Request;
    expect(callReq.url).toBe('http://localhost/v1/auth/login');
    expect(callReq.method).toBe('POST');
  });

  it('throws an ApiErrorException on a 4xx envelope', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonRes({ error: { code: 'INVALID_CREDENTIALS', message: 'nope', request_id: 'r' } }, 401),
    );
    const client = createClient({
      baseUrl: 'http://localhost/v1',
      getAccessToken: () => null,
      onUnauthenticated: () => {},
    });
    await expect(
      client.POST('/auth/login', { body: { email: 'a@b.com', password: 'wrong' } }),
    ).rejects.toMatchObject({ error: { code: 'INVALID_CREDENTIALS', http_status: 401 } });
  });
});
