/**
 * Web Sentry stub — by design, all three exports are no-ops on web. The
 * test asserts the surface compiles and never throws, since vitest
 * resolves `~/lib/sentry` to `sentry.web.ts` and a regression that
 * reintroduced a real Sentry init would crash inside jsdom.
 */
import { describe, expect, it } from 'vitest';

import { captureError, captureMetric, initSentry } from '~/lib/sentry';

describe('sentry.web (no-op stub)', () => {
  it('initSentry is a no-op and returns void', () => {
    expect(initSentry()).toBeUndefined();
  });

  it('captureError swallows any input without throwing', () => {
    expect(() => captureError('boom', new Error('x'))).not.toThrow();
    expect(() => captureError('boom', 'string-reason')).not.toThrow();
    expect(() => captureError('boom', null)).not.toThrow();
  });

  it('captureMetric accepts the same surface shape as native', () => {
    expect(() => captureMetric('LCP', 2400)).not.toThrow();
    expect(() => captureMetric('LCP', 2400, { rating: 'good' })).not.toThrow();
  });
});
