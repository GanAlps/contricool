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

  it('falls back to default base URL when EXPO_PUBLIC_API_BASE_URL is unset', async () => {
    // Exercise the ``?? '/v1'`` fallback in getBaseUrl. Test-setup
    // pins the env var; we clear it for this test to take the
    // fallback branch. The relative URL won't be intercepted by
    // MSW (different origin resolution under jsdom) — telemetry
    // swallows the resulting network failure, which itself
    // exercises the catch-block branch.
    const original = process.env.EXPO_PUBLIC_API_BASE_URL;
    // ``delete`` is required here — assigning ``undefined`` to a
    // process.env key sets the string "undefined", which is truthy
    // and would not exercise the ``?? '/v1'`` nullish fallback.
    // biome-ignore lint/performance/noDelete: see comment above
    delete process.env.EXPO_PUBLIC_API_BASE_URL;
    try {
      // Should not throw (telemetry swallows network errors).
      await expect(
        postTelemetry({ level: 'error', name: 'fallback-base' }),
      ).resolves.toBeUndefined();
    } finally {
      if (original !== undefined) {
        process.env.EXPO_PUBLIC_API_BASE_URL = original;
      }
    }
  });

  it('reportError handles a non-Error non-string reason', async () => {
    let body: unknown = null;
    server.use(
      http.post(`${BASE}/telemetry/error`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ accepted: true }, { status: 202 });
      }),
    );
    reportError('weird-reason', { unexpected: 'object' });
    await new Promise((r) => setTimeout(r, 50));
    expect((body as { message: string }).message).toBe('unknown');
  });

  it('reportMetric without extra omits the bag', async () => {
    let body: unknown = null;
    server.use(
      http.post(`${BASE}/telemetry/error`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ accepted: true }, { status: 202 });
      }),
    );
    reportMetric('TTFB', 120);
    await new Promise((r) => setTimeout(r, 50));
    const b = body as { value: number; extra?: unknown };
    expect(b.value).toBe(120);
    expect(b.extra).toBeUndefined();
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

  it('redacts denylist keys before posting (PII never leaves the device)', async () => {
    // RED LINE 1: even telemetry payloads must not leak PII. The redactor
    // is wired in postTelemetry; this test is the safety net.
    let body: unknown = null;
    server.use(
      http.post(`${BASE}/telemetry/error`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ accepted: true }, { status: 202 });
      }),
    );
    await postTelemetry({
      level: 'error',
      name: 'auth-failure',
      extra: {
        // These are the canonical leak vectors — adding to the bag
        // simulates a future caller that forgot to scrub.
        email: 'user@example.com',
        password: 'plaintext',
        authorization: 'Bearer leaked-jwt',
        // A non-sensitive sibling key proves we don't over-redact.
        request_id: 'req-123',
      },
    });
    const b = body as { extra: Record<string, string> };
    expect(b.extra.email).toBe('[REDACTED]');
    expect(b.extra.password).toBe('[REDACTED]');
    expect(b.extra.authorization).toBe('[REDACTED]');
    expect(b.extra.request_id).toBe('req-123');
  });
});
