/**
 * Native telemetry — verifies the `.native.ts` variant forwards to
 * Sentry instead of POSTing to /v1/telemetry/error. Sentry is mocked
 * at the module boundary because the real `@sentry/react-native`
 * pulls native modules that don't run in jsdom.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const sentry = vi.hoisted(() => ({
  captureError: vi.fn(),
  captureMetric: vi.fn(),
}));

vi.mock('~/lib/sentry', () => ({
  captureError: sentry.captureError,
  captureMetric: sentry.captureMetric,
  initSentry: vi.fn(),
}));

import {
  _resetTelemetryForTests,
  postTelemetry,
  reportError,
  reportMetric,
} from '~/lib/telemetry.native';

beforeEach(() => {
  sentry.captureError.mockClear();
  sentry.captureMetric.mockClear();
  _resetTelemetryForTests();
});
afterEach(() => {
  _resetTelemetryForTests();
});

describe('telemetry.native', () => {
  it('postTelemetry error → Sentry.captureError with reconstructed Error', async () => {
    await postTelemetry({
      level: 'error',
      name: 'boom',
      message: 'something broke',
      stack: 'Error: something broke\n    at foo',
    });
    expect(sentry.captureError).toHaveBeenCalledTimes(1);
    const [name, err] = sentry.captureError.mock.calls[0] ?? [];
    expect(name).toBe('boom');
    expect(err).toBeInstanceOf(Error);
    expect((err as Error).message).toBe('something broke');
    expect((err as Error).stack).toContain('Error: something broke');
  });

  it('falls back to name when message is omitted', async () => {
    await postTelemetry({ level: 'error', name: 'unnamed' });
    const err = sentry.captureError.mock.calls[0]?.[1] as Error;
    expect(err.message).toBe('unnamed');
  });

  it('postTelemetry metric → Sentry.captureMetric with value + extra', async () => {
    await postTelemetry({
      level: 'metric',
      name: 'LCP',
      value: 2400,
      extra: { rating: 'good' },
    });
    expect(sentry.captureMetric).toHaveBeenCalledWith('LCP', 2400, { rating: 'good' });
  });

  it('metric with no value defaults to 0', async () => {
    await postTelemetry({ level: 'metric', name: 'X' });
    expect(sentry.captureMetric).toHaveBeenCalledWith('X', 0, undefined);
  });

  it('dedups same-level same-name within 200 ms', async () => {
    await postTelemetry({ level: 'error', name: 'boom' });
    await postTelemetry({ level: 'error', name: 'boom' });
    await postTelemetry({ level: 'error', name: 'boom' });
    expect(sentry.captureError).toHaveBeenCalledTimes(1);
  });

  it('does not dedup across distinct names', async () => {
    await postTelemetry({ level: 'error', name: 'a' });
    await postTelemetry({ level: 'error', name: 'b' });
    expect(sentry.captureError).toHaveBeenCalledTimes(2);
  });

  it('swallows Sentry init errors so the app never crashes from telemetry', async () => {
    sentry.captureError.mockImplementationOnce(() => {
      throw new Error('sentry-not-initialized');
    });
    await expect(postTelemetry({ level: 'error', name: 'boom' })).resolves.toBeUndefined();
  });

  it('reportError extracts message + stack from an Error', async () => {
    const err = new Error('whoops');
    reportError('test-name', err);
    await new Promise((r) => setTimeout(r, 5));
    const captured = sentry.captureError.mock.calls[0]?.[1] as Error;
    expect(captured.message).toBe('whoops');
    expect(typeof captured.stack).toBe('string');
  });

  it('reportError handles non-Error reasons', async () => {
    reportError('s', 'string-reason');
    await new Promise((r) => setTimeout(r, 5));
    const captured = sentry.captureError.mock.calls[0]?.[1] as Error;
    expect(captured.message).toBe('string-reason');

    sentry.captureError.mockClear();
    _resetTelemetryForTests();

    reportError('o', { x: 1 });
    await new Promise((r) => setTimeout(r, 5));
    const captured2 = sentry.captureError.mock.calls[0]?.[1] as Error;
    expect(captured2.message).toBe('unknown');
  });

  it('reportMetric without extra omits the bag', () => {
    reportMetric('TTFB', 120);
    expect(sentry.captureMetric).toHaveBeenCalledWith('TTFB', 120, undefined);
  });

  it('reportMetric attaches an extra dimension bag', () => {
    reportMetric('LCP', 2200, { rating: 'good' });
    expect(sentry.captureMetric).toHaveBeenCalledWith('LCP', 2200, { rating: 'good' });
  });
});
