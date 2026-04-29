/**
 * Decode a Cognito ID token's claims **without** verifying the
 * signature.  The backend re-verifies the access token on every
 * authenticated request (Phase 2c NFR1.1) — this helper is purely
 * a UX convenience for hard-reload re-hydration.  Never trust these
 * claims for any authorization decision.
 */

import type { AuthUser, Currency } from './types';

function base64UrlDecode(input: string): string {
  let s = input.replace(/-/g, '+').replace(/_/g, '/');
  while (s.length % 4 !== 0) {
    s += '=';
  }
  if (typeof atob === 'function') {
    return atob(s);
  }
  // Node fallback (e.g. for tests in non-jsdom contexts).
  return Buffer.from(s, 'base64').toString('binary');
}

function isValidCurrency(v: unknown): v is Currency {
  return v === 'USD' || v === 'INR';
}

export function decodeIdToken(token: string): AuthUser | null {
  const parts = token.split('.');
  if (parts.length !== 3) {
    return null;
  }
  let payload: unknown;
  try {
    const json = base64UrlDecode(parts[1] ?? '');
    payload = JSON.parse(json);
  } catch {
    return null;
  }
  if (!payload || typeof payload !== 'object') {
    return null;
  }
  const claims = payload as Record<string, unknown>;
  const userId = claims['custom:user_id'];
  const name = claims.name;
  const currencyClaim = claims['custom:currency'];
  if (typeof userId !== 'string' || typeof name !== 'string') {
    return null;
  }
  const currency: Currency = isValidCurrency(currencyClaim) ? currencyClaim : 'USD';
  return { user_id: userId, name, currency };
}
