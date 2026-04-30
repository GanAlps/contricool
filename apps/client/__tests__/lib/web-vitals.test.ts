/**
 * web-vitals reporter tests. We mock the ``web-vitals`` package so
 * the test owns the metric callback timing and doesn't depend on
 * the browser firing real LCP / INP events.
 */
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { _resetTelemetryForTests } from '~/lib/telemetry';
import { _resetWebVitalsForTests, reportWebVitals } from '~/lib/web-vitals';

import { server } from '../msw-handlers';

const BASE = 'http://localhost/v1';

beforeEach(() => {
  _resetTelemetryForTests();
  _resetWebVitalsForTests();
});
afterEach(() => {
  _resetTelemetryForTests();
  _resetWebVitalsForTests();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('reportWebVitals', () => {
  it('subscribes to LCP/INP/CLS/FCP/TTFB and posts each metric', async () => {
    type Cb = (m: {
      name: string;
      value: number;
      rating?: string;
      navigationType?: string;
    }) => void;
    const captured: { name: string; cb: Cb }[] = [];
    vi.doMock('web-vitals', () => ({
      onLCP: (cb: Cb) => captured.push({ name: 'LCP', cb }),
      onINP: (cb: Cb) => captured.push({ name: 'INP', cb }),
      onCLS: (cb: Cb) => captured.push({ name: 'CLS', cb }),
      onFCP: (cb: Cb) => captured.push({ name: 'FCP', cb }),
      onTTFB: (cb: Cb) => captured.push({ name: 'TTFB', cb }),
    }));

    const posted: { name: string; value: number }[] = [];
    server.use(
      http.post(`${BASE}/telemetry/error`, async ({ request }) => {
        const body = (await request.json()) as { name: string; value: number };
        posted.push(body);
        return HttpResponse.json({ accepted: true }, { status: 202 });
      }),
    );

    await reportWebVitals();
    expect(captured.map((c) => c.name).sort()).toEqual(['CLS', 'FCP', 'INP', 'LCP', 'TTFB']);

    // Fire one with a rating + navigationType — exercises the truthy
    // ?? branches in `send`.
    captured[0]?.cb({
      name: 'LCP',
      value: 2400,
      rating: 'good',
      navigationType: 'navigate',
    });
    // Fire a second with neither — exercises the null fallback
    // (`m.rating ?? null`, `m.navigationType ?? null`).
    captured[1]?.cb({ name: 'INP', value: 50 });
    await new Promise((r) => setTimeout(r, 50));
    expect(posted).toHaveLength(2);
    expect(posted.map((p) => p.name).sort()).toEqual(['INP', 'LCP']);
  });

  it('is idempotent — second call is a no-op', async () => {
    let calls = 0;
    vi.doMock('web-vitals', () => ({
      onLCP: () => {
        calls += 1;
      },
      onINP: () => {},
      onCLS: () => {},
      onFCP: () => {},
      onTTFB: () => {},
    }));
    await reportWebVitals();
    await reportWebVitals();
    expect(calls).toBe(1);
  });

  it('swallows a missing web-vitals package', async () => {
    vi.doMock('web-vitals', () => {
      throw new Error('not installed');
    });
    await expect(reportWebVitals()).resolves.toBeUndefined();
  });
});
