/**
 * Negative-leaning suite — every denylist key has a positive case
 * (it redacts) AND a near-miss case (a similarly-named key does not
 * over-redact). Mirrors the backend's `tests/core/test_observability.py`
 * coverage matrix; deviation between client and server denylists is a
 * red-flag for the auth/security review.
 */

import { describe, expect, it } from 'vitest';

import { DENY_KEYS, REDACTED, isSensitiveKey, redact } from '~/lib/pii-denylist';

describe('isSensitiveKey', () => {
  it.each([
    'email',
    'phone',
    'password',
    'otp',
    'authorization',
    'cookie',
    'secret',
    'token',
    'ssn',
    'salt',
  ])('whole-fragment match: %s', (key) => {
    expect(isSensitiveKey(key)).toBe(true);
  });

  it.each([
    ['userEmail', true],
    ['user_email', true],
    ['user-email', true],
    ['UserEmail', true],
    ['EMAIL', true],
    ['refresh_token', true],
    ['accessToken', true],
    ['set-cookie', true],
    ['discount_card', false], // near-miss: `card` alone is not in DENY_KEYS
    ['status_code', false], // `code` is intentionally NOT denied
    ['country', false],
    ['emailbody', false], // not a fragment match — `email` and `body` joined without separator
    ['unrelated', false],
  ])('case-and-shape variant: %s → sensitive=%s', (key, expected) => {
    expect(isSensitiveKey(key)).toBe(expected);
  });

  it.each([
    'credit_card',
    'credit-card',
    'creditCard',
    'card_number',
    'cardNumber',
    'cc_number',
    'CCN',
  ])('compound key: %s', (key) => {
    expect(isSensitiveKey(key)).toBe(true);
  });

  it('non-string keys are not sensitive', () => {
    expect(isSensitiveKey(42)).toBe(false);
    expect(isSensitiveKey(null)).toBe(false);
    expect(isSensitiveKey(undefined)).toBe(false);
  });
});

describe('redact', () => {
  it('replaces values for every key in DENY_KEYS', () => {
    const obj: Record<string, string> = {};
    for (const key of DENY_KEYS) {
      obj[key] = `secret-${key}`;
    }
    const out = redact(obj) as Record<string, string>;
    for (const key of DENY_KEYS) {
      expect(out[key]).toBe(REDACTED);
    }
  });

  it('walks nested objects', () => {
    const out = redact({
      level: 'error',
      user: {
        user_id: 'u1',
        email: 'leak@example.com',
        nested: { phone: '+15555550100', name: 'safe' },
      },
    });
    expect(out).toEqual({
      level: 'error',
      user: {
        user_id: 'u1',
        email: REDACTED,
        nested: { phone: REDACTED, name: 'safe' },
      },
    });
  });

  it('walks arrays', () => {
    const out = redact([
      { email: 'a@b.com', name: 'A' },
      { email: 'c@d.com', name: 'C' },
    ]);
    expect(out).toEqual([
      { email: REDACTED, name: 'A' },
      { email: REDACTED, name: 'C' },
    ]);
  });

  it('preserves primitives unchanged', () => {
    expect(redact(42)).toBe(42);
    expect(redact('plain')).toBe('plain');
    expect(redact(null)).toBeNull();
    expect(redact(undefined)).toBeUndefined();
    expect(redact(true)).toBe(true);
  });

  it('does not over-redact near-miss keys', () => {
    const out = redact({
      status_code: 200,
      discount_card: 'X-COUPON',
      country: 'US',
    });
    expect(out).toEqual({
      status_code: 200,
      discount_card: 'X-COUPON',
      country: 'US',
    });
  });

  it('redacts compound credit-card keys regardless of casing', () => {
    const out = redact({
      credit_card: '4111-1111-1111-1111',
      cardNumber: '4242424242424242',
      ccn: '5555555555554444',
    });
    expect(out).toEqual({
      credit_card: REDACTED,
      cardNumber: REDACTED,
      ccn: REDACTED,
    });
  });

  it('handles a typical Sentry event shape end-to-end', () => {
    const event = {
      request: {
        headers: {
          authorization: 'Bearer leaked',
          cookie: 'rt=leaked',
          'content-type': 'application/json',
        },
        data: { email: 'user@example.com', password: 'leaked' },
      },
      breadcrumbs: [{ category: 'http', data: { authorization: 'Bearer leaked', url: '/v1/me' } }],
      tags: { release: '0.1.0+abc1234' },
    };
    const out = redact(event);
    expect(out.request.headers.authorization).toBe(REDACTED);
    expect(out.request.headers.cookie).toBe(REDACTED);
    expect(out.request.headers['content-type']).toBe('application/json');
    expect(out.request.data.email).toBe(REDACTED);
    expect(out.request.data.password).toBe(REDACTED);
    expect(out.breadcrumbs[0]?.data.authorization).toBe(REDACTED);
    expect(out.breadcrumbs[0]?.data.url).toBe('/v1/me');
    expect(out.tags.release).toBe('0.1.0+abc1234');
  });
});
