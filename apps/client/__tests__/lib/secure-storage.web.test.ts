/**
 * Web target stub — every helper is a no-op (refresh token lives in
 * the HttpOnly cookie, JS can't read it). The point of these tests is
 * to lock the contract so the SDK middleware sees `null` from
 * `getRefreshToken()` and falls back to its cookie path.
 */

import { describe, expect, it } from 'vitest';

import { clearRefreshToken, getRefreshToken, setRefreshToken } from '~/lib/secure-storage.web';

describe('secure-storage (web stub)', () => {
  it('getRefreshToken always resolves null', async () => {
    expect(await getRefreshToken()).toBeNull();
  });

  it('setRefreshToken is a no-op (does not throw, does not persist anything readable)', async () => {
    await expect(setRefreshToken('value-the-stub-ignores')).resolves.toBeUndefined();
    expect(await getRefreshToken()).toBeNull();
  });

  it('clearRefreshToken is a no-op', async () => {
    await expect(clearRefreshToken()).resolves.toBeUndefined();
  });
});
