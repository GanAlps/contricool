import { afterEach, describe, expect, it, vi } from 'vitest';

import { decodeIdToken } from '~/lib/id-token';

function b64url(input: string): string {
  return btoa(input).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_');
}

function makeJwt(claims: Record<string, unknown>): string {
  const header = b64url(JSON.stringify({ alg: 'RS256', typ: 'JWT' }));
  const payload = b64url(JSON.stringify(claims));
  return `${header}.${payload}.signature`;
}

describe('decodeIdToken', () => {
  it('extracts user_id, name, currency from valid claims', () => {
    const t = makeJwt({
      'custom:user_id': '01J0000',
      name: 'Alice',
      'custom:currency': 'INR',
    });
    expect(decodeIdToken(t)).toEqual({
      user_id: '01J0000',
      name: 'Alice',
      currency: 'INR',
    });
  });

  it('defaults currency to USD when claim is missing', () => {
    const t = makeJwt({ 'custom:user_id': 'u', name: 'A' });
    expect(decodeIdToken(t)).toEqual({ user_id: 'u', name: 'A', currency: 'USD' });
  });

  it('defaults currency to USD when claim is invalid', () => {
    const t = makeJwt({ 'custom:user_id': 'u', name: 'A', 'custom:currency': 'EUR' });
    expect(decodeIdToken(t)).toEqual({ user_id: 'u', name: 'A', currency: 'USD' });
  });

  it('returns null when token has wrong number of parts', () => {
    expect(decodeIdToken('not-a-jwt')).toBeNull();
  });

  it('returns null when payload is not valid JSON', () => {
    const t = `${b64url('{}')}.${b64url('{not json')}.sig`;
    expect(decodeIdToken(t)).toBeNull();
  });

  it('returns null when required claims are missing', () => {
    const t = makeJwt({ name: 'A' });
    expect(decodeIdToken(t)).toBeNull();
  });

  it('returns null when payload is not an object (string)', () => {
    const header = b64url(JSON.stringify({}));
    const payload = b64url('"a string"');
    const t = `${header}.${payload}.sig`;
    expect(decodeIdToken(t)).toBeNull();
  });

  describe('Node fallback (no atob)', () => {
    const realAtob = globalThis.atob;
    afterEach(() => {
      // Restore.
      Object.defineProperty(globalThis, 'atob', {
        value: realAtob,
        configurable: true,
        writable: true,
      });
    });

    it('uses Buffer when atob is unavailable', async () => {
      // Force the fallback path by removing atob.
      Object.defineProperty(globalThis, 'atob', {
        value: undefined,
        configurable: true,
        writable: true,
      });
      const { decodeIdToken: redecode } =
        await vi.importActual<typeof import('~/lib/id-token')>('~/lib/id-token');
      const t = makeJwt({ 'custom:user_id': 'u', name: 'A', 'custom:currency': 'USD' });
      const r = redecode(t);
      expect(r).toEqual({ user_id: 'u', name: 'A', currency: 'USD' });
    });
  });
});
