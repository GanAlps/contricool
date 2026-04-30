/**
 * Tests for the frontend telemetry client.
 */
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { _resetTelemetryForTests, postTelemetry, reportError, reportMetric } from '~/lib/telemetry';

import { server } from '../msw-handlers';

const BASE = 'http://localhost/v1';

beforeEach(() => {
  _resetTelemetryForTests();
});
afterEach(() => {
  _resetTelemetryForTests();
});

describe('postTelemetry', () => {
  it('POSTs an error event to /v1/telemetry/error', async () => {
    let body: unknown = null;
    server.use(
      http.post(`${BASE}/telemetry/error`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ accepted: true }, { status: 202 });
      }),
    );
    await postTelemetry({ level: 'error', name: 'boom', message: 'x' });
    const b = body as { level: string; name: string; message: string };
    expect(b.level).toBe('error');
    expect(b.name).toBe('boom');
    expect(b.message).toBe('x');
  });

  it('POSTs a metric event with value', async () => {
    let body: unknown = null;
    server.use(
      http.post(`${BASE}/telemetry/error`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ accepted: true }, { status: 202 });
      }),
    );
    await postTelemetry({ level: 'metric', name: 'LCP', value: 2400 });
    const b = body as { level: string; name: string; value: number };
    expect(b.level).toBe('metric');
    expect(b.value).toBe(2400);
  });

  it('dedups same-name same-level events within 200 ms', async () => {
    let calls = 0;
    server.use(
      http.post(`${BASE}/telemetry/error`, () => {
        calls += 1;
        return HttpResponse.json({ accepted: true }, { status: 202 });
      }),
    );
    await postTelemetry({ level: 'error', name: 'boom' });
    await postTelemetry({ level: 'error', name: 'boom' });
    await postTelemetry({ level: 'error', name: 'boom' });
    expect(calls).toBe(1);
  });

  it('does not dedup across distinct names', async () => {
    let calls = 0;
    server.use(
      http.post(`${BASE}/telemetry/error`, () => {
        calls += 1;
        return HttpResponse.json({ accepted: true }, { status: 202 });
      }),
    );
    await postTelemetry({ level: 'error', name: 'a' });
    await postTelemetry({ level: 'error', name: 'b' });
    expect(calls).toBe(2);
  });

  it('swallows network errors so the page never crashes from telemetry', async () => {
    server.use(http.post(`${BASE}/telemetry/error`, () => HttpResponse.error()));
    // No throw expected.
    await expect(postTelemetry({ level: 'error', name: 'net-fail' })).resolves.toBeUndefined();
  });

  it('reportError extracts message + stack from an Error', async () => {
    let body: unknown = null;
    server.use(
      http.post(`${BASE}/telemetry/error`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ accepted: true }, { status: 202 });
      }),
    );
    const err = new Error('whoops');
    reportError('test-name', err);
    // reportError fires post async; await a microtask.
    await new Promise((r) => setTimeout(r, 50));
    const b = body as { level: string; name: string; message: string; stack: string };
    expect(b.level).toBe('error');
    expect(b.message).toBe('whoops');
    expect(typeof b.stack).toBe('string');
  });

  it('reportError handles a non-Error reason', async () => {
    let body: unknown = null;
    server.use(
      http.post(`${BASE}/telemetry/error`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ accepted: true }, { status: 202 });
      }),
    );
    reportError('test-string', 'string-reason');
    await new Promise((r) => setTimeout(r, 50));
    expect((body as { message: string }).message).toBe('string-reason');
  });

  it('reportMetric attaches an extra dimension bag', async () => {
    let body: unknown = null;
    server.use(
      http.post(`${BASE}/telemetry/error`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ accepted: true }, { status: 202 });
      }),
    );
    reportMetric('LCP', 2200, { rating: 'good' });
    await new Promise((r) => setTimeout(r, 50));
    const b = body as { value: number; extra: { rating: string } };
    expect(b.value).toBe(2200);
    expect(b.extra.rating).toBe('good');
  });
});
