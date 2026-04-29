import { describe, expect, it } from 'vitest';

import { ApiErrorException, parseError } from '../errors';

function jsonRes(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

describe('parseError', () => {
  it('parses a Phase 2c envelope with all fields', async () => {
    const r = jsonRes(
      {
        error: {
          code: 'INVALID_CREDENTIALS',
          message: 'Email or password is incorrect',
          request_id: 'req-1',
          details: [{ field: 'email', issue: 'malformed' }],
          retry_after: 60,
        },
      },
      401,
    );
    const e = await parseError(r);
    expect(e).toEqual({
      code: 'INVALID_CREDENTIALS',
      message: 'Email or password is incorrect',
      request_id: 'req-1',
      details: [{ field: 'email', issue: 'malformed' }],
      retry_after: 60,
      http_status: 401,
    });
  });

  it('defaults missing request_id and details', async () => {
    const r = jsonRes({ error: { code: 'X', message: 'y' } }, 400);
    const e = await parseError(r);
    expect(e.request_id).toBeNull();
    expect(e.details).toEqual([]);
    expect(e.retry_after).toBeUndefined();
  });

  it('synthesises NETWORK_ERROR for raw HTML 5xx', async () => {
    const r = new Response('<html>500</html>', { status: 500 });
    const e = await parseError(r);
    expect(e.code).toBe('NETWORK_ERROR');
    expect(e.http_status).toBe(500);
  });

  it('synthesises NETWORK_ERROR for empty body', async () => {
    const r = new Response(null, { status: 502 });
    const e = await parseError(r);
    expect(e.code).toBe('NETWORK_ERROR');
    expect(e.http_status).toBe(502);
  });

  it('synthesises NETWORK_ERROR when body is malformed JSON', async () => {
    const r = new Response('{not-json', {
      status: 503,
      headers: { 'content-type': 'application/json' },
    });
    const e = await parseError(r);
    expect(e.code).toBe('NETWORK_ERROR');
  });

  it('synthesises NETWORK_ERROR when envelope shape is partial', async () => {
    const r = jsonRes({ error: { code: 'X' } }, 400); // no message
    const e = await parseError(r);
    expect(e.code).toBe('NETWORK_ERROR');
  });

  it('handles a Response whose .text() throws', async () => {
    const fake = {
      status: 502,
      clone: () => ({
        text: () => {
          throw new Error('stream broke');
        },
      }),
    } as unknown as Response;
    const e = await parseError(fake);
    expect(e.code).toBe('NETWORK_ERROR');
    expect(e.http_status).toBe(502);
  });
});

describe('ApiErrorException', () => {
  it('preserves the error payload and standard Error fields', () => {
    const e = new ApiErrorException({
      code: 'BAD',
      message: 'thing',
      request_id: 'r',
      details: [],
      http_status: 400,
    });
    expect(e.name).toBe('ApiErrorException');
    expect(e.message).toBe('BAD: thing');
    expect(e.error.http_status).toBe(400);
  });
});
