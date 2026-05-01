/**
 * Native Sentry init + scrubber tests.
 *
 * `@sentry/react-native` is mocked because:
 *   - It pulls in native modules that don't run under jsdom.
 *   - We need to assert `init` was called with the right options
 *     (DSN, beforeSend, sendDefaultPii: false) and that
 *     `captureException` / `captureMessage` get the right inputs —
 *     both are easier to verify with a fake.
 *
 * The scrubber is exported as `scrubEvent` so we can run the
 * before-send pipeline against a synthetic Sentry event without
 * pumping it through the SDK.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const sentryMock = vi.hoisted(() => ({
  init: vi.fn(),
  captureException: vi.fn(),
  captureMessage: vi.fn(),
}));

vi.mock('@sentry/react-native', () => ({
  init: sentryMock.init,
  captureException: sentryMock.captureException,
  captureMessage: sentryMock.captureMessage,
}));

import {
  _resetSentryForTests,
  captureError,
  captureMetric,
  initSentry,
  scrubEvent,
} from '~/lib/sentry.native';

const SAVED_ENV = { ...process.env };

beforeEach(() => {
  sentryMock.init.mockClear();
  sentryMock.captureException.mockClear();
  sentryMock.captureMessage.mockClear();
  _resetSentryForTests();
  // Pin a known DSN for tests that need init to actually fire.
  process.env.EXPO_PUBLIC_SENTRY_DSN = 'https://k@o.ingest.sentry.io/1';
  process.env.EXPO_PUBLIC_ENV = 'test';
  // biome-ignore lint/performance/noDelete: tests need to clear, not stringify
  delete process.env.EXPO_PUBLIC_RELEASE;
  // biome-ignore lint/performance/noDelete: tests need to clear, not stringify
  delete process.env.EXPO_PUBLIC_DIST;
});
afterEach(() => {
  process.env = { ...SAVED_ENV };
  _resetSentryForTests();
});

describe('initSentry', () => {
  it('calls Sentry.init with DSN, environment, sendDefaultPii: false, and a beforeSend scrubber', () => {
    initSentry();
    expect(sentryMock.init).toHaveBeenCalledTimes(1);
    const opts = sentryMock.init.mock.calls[0]?.[0] as {
      dsn: string;
      environment: string;
      sendDefaultPii: boolean;
      beforeSend: (event: unknown) => unknown;
      tracesSampleRate: number;
    };
    expect(opts.dsn).toBe('https://k@o.ingest.sentry.io/1');
    expect(opts.environment).toBe('test');
    expect(opts.sendDefaultPii).toBe(false);
    expect(opts.tracesSampleRate).toBe(0);
    expect(typeof opts.beforeSend).toBe('function');
  });

  it('forwards release + dist when set in env', () => {
    process.env.EXPO_PUBLIC_RELEASE = '1.2.3';
    process.env.EXPO_PUBLIC_DIST = '42';
    initSentry();
    const opts = sentryMock.init.mock.calls[0]?.[0] as { release: string; dist: string };
    expect(opts.release).toBe('1.2.3');
    expect(opts.dist).toBe('42');
  });

  it('is a no-op when no DSN is configured (local dev)', () => {
    // biome-ignore lint/performance/noDelete: tests need to clear, not stringify
    delete process.env.EXPO_PUBLIC_SENTRY_DSN;
    initSentry();
    expect(sentryMock.init).not.toHaveBeenCalled();
    // captureError post-no-init should also be inert.
    captureError('boom', new Error('x'));
    expect(sentryMock.captureException).not.toHaveBeenCalled();
  });

  it('is idempotent — calling initSentry twice only initializes once', () => {
    initSentry();
    initSentry();
    expect(sentryMock.init).toHaveBeenCalledTimes(1);
  });
});

describe('captureError', () => {
  it('forwards to Sentry.captureException with the name as a tag', () => {
    initSentry();
    const err = new Error('whoops');
    captureError('signin-failed', err);
    expect(sentryMock.captureException).toHaveBeenCalledTimes(1);
    expect(sentryMock.captureException).toHaveBeenCalledWith(err, {
      tags: { name: 'signin-failed' },
    });
  });

  it('wraps a non-Error reason into an Error so Sentry gets a stack', () => {
    initSentry();
    captureError('weird', 'string-reason');
    const arg = sentryMock.captureException.mock.calls[0]?.[0] as Error;
    expect(arg).toBeInstanceOf(Error);
    expect(arg.message).toBe('string-reason');
  });

  it('handles non-Error non-string reasons (defensive)', () => {
    initSentry();
    captureError('weird', { unexpected: 'object' });
    const arg = sentryMock.captureException.mock.calls[0]?.[0] as Error;
    expect(arg.message).toBe('unknown');
  });

  it('is inert before init() runs (no DSN-less crash)', () => {
    // biome-ignore lint/performance/noDelete: tests need to clear, not stringify
    delete process.env.EXPO_PUBLIC_SENTRY_DSN;
    captureError('boom', new Error('x'));
    expect(sentryMock.captureException).not.toHaveBeenCalled();
  });
});

describe('captureMetric', () => {
  it('forwards to Sentry.captureMessage with value + extra', () => {
    initSentry();
    captureMetric('LCP', 2400, { rating: 'good' });
    expect(sentryMock.captureMessage).toHaveBeenCalledWith('LCP', {
      level: 'info',
      extra: { value: 2400, rating: 'good' },
    });
  });

  it('omits an empty extra bag', () => {
    initSentry();
    captureMetric('TTFB', 120);
    expect(sentryMock.captureMessage).toHaveBeenCalledWith('TTFB', {
      level: 'info',
      extra: { value: 120 },
    });
  });

  it('is inert before init() runs', () => {
    // biome-ignore lint/performance/noDelete: tests need to clear, not stringify
    delete process.env.EXPO_PUBLIC_SENTRY_DSN;
    captureMetric('LCP', 2400);
    expect(sentryMock.captureMessage).not.toHaveBeenCalled();
  });
});

describe('scrubEvent (PII denylist enforcement — RED LINE 1)', () => {
  it('redacts denylist keys in event.extra before send', () => {
    const e = scrubEvent({
      extra: {
        email: 'user@example.com',
        password: 'plaintext',
        request_id: 'r-1',
      },
    });
    expect(e.extra?.email).toBe('[REDACTED]');
    expect(e.extra?.password).toBe('[REDACTED]');
    expect(e.extra?.request_id).toBe('r-1');
  });

  it('redacts denylist keys in event.tags', () => {
    const e = scrubEvent({
      tags: { authorization: 'Bearer leaked-jwt', release: 'v1' },
    });
    expect(e.tags?.authorization).toBe('[REDACTED]');
    expect(e.tags?.release).toBe('v1');
  });

  it('redacts denylist keys in event.contexts', () => {
    const e = scrubEvent({
      contexts: { auth: { token: 'leaked', user_id: 'u1' } },
    });
    const auth = e.contexts?.auth as { token: string; user_id: string };
    expect(auth.token).toBe('[REDACTED]');
    expect(auth.user_id).toBe('u1');
  });

  it('strips email/username from event.user, keeping only the opaque id', () => {
    const e = scrubEvent({
      user: { id: 'u1', email: 'a@b.com', username: 'alice' },
    });
    expect(e.user).toEqual({ id: 'u1' });
  });

  it('returns an empty user object when no id is present', () => {
    const e = scrubEvent({
      user: { email: 'a@b.com', username: 'alice' },
    });
    expect(e.user).toEqual({});
  });

  it('redacts breadcrumb data', () => {
    const e = scrubEvent({
      breadcrumbs: [
        {
          message: 'login',
          data: { email: 'a@b.com', request_id: 'r' },
        },
      ],
    });
    expect(e.breadcrumbs?.[0]?.data?.email).toBe('[REDACTED]');
    expect(e.breadcrumbs?.[0]?.data?.request_id).toBe('r');
  });

  it('passes through breadcrumbs with no data field', () => {
    const input: Record<string, unknown> = {
      breadcrumbs: [{ message: 'navigate', category: 'navigation' }],
    };
    const e = scrubEvent(input as Parameters<typeof scrubEvent>[0]);
    const crumb = (e as { breadcrumbs: Array<Record<string, unknown>> }).breadcrumbs[0];
    expect(crumb?.data).toBeUndefined();
    expect(crumb?.message).toBe('navigate');
  });

  it('redacts denylist keys in event.request', () => {
    const e = scrubEvent({
      request: { headers: { authorization: 'Bearer x', 'content-type': 'application/json' } },
    });
    const headers = e.request?.headers as Record<string, string>;
    expect(headers.authorization).toBe('[REDACTED]');
    expect(headers['content-type']).toBe('application/json');
  });

  it('returns the event unchanged when payload is empty', () => {
    const e = scrubEvent({});
    expect(e).toEqual({});
  });

  it('never throws even on adversarial input', () => {
    // Build an event with a circular reference; the scrubber should
    // fail closed (return event as-is) rather than blow up.
    type Loopy = { extra: { self?: Loopy } };
    const loop: Loopy = { extra: {} };
    loop.extra.self = loop;
    expect(() => scrubEvent(loop as unknown as Parameters<typeof scrubEvent>[0])).not.toThrow();
  });
});
