/**
 * Native secure-storage helpers — `expo-secure-store` is mocked so
 * tests stay in jsdom. The contract under test is:
 *   - `getRefreshToken` returns whatever SecureStore has, or null on
 *     read error (corruption, key missing, biometric denial).
 *   - `setRefreshToken` writes the value verbatim.
 *   - `clearRefreshToken` deletes the key and swallows
 *     "key not found" errors.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockStore = new Map<string, string>();
const ss = {
  getItemAsync: vi.fn<(k: string) => Promise<string | null>>(async (k) => mockStore.get(k) ?? null),
  setItemAsync: vi.fn<(k: string, v: string) => Promise<void>>(async (k, v) => {
    mockStore.set(k, v);
  }),
  deleteItemAsync: vi.fn<(k: string) => Promise<void>>(async (k) => {
    mockStore.delete(k);
  }),
};

vi.mock('expo-secure-store', () => ({
  getItemAsync: (...args: Parameters<typeof ss.getItemAsync>) => ss.getItemAsync(...args),
  setItemAsync: (...args: Parameters<typeof ss.setItemAsync>) => ss.setItemAsync(...args),
  deleteItemAsync: (...args: Parameters<typeof ss.deleteItemAsync>) => ss.deleteItemAsync(...args),
}));

import {
  REFRESH_TOKEN_KEY,
  clearRefreshToken,
  getRefreshToken,
  setRefreshToken,
} from '~/lib/secure-storage.native';

beforeEach(() => {
  mockStore.clear();
  ss.getItemAsync.mockClear();
  ss.setItemAsync.mockClear();
  ss.deleteItemAsync.mockClear();
});
afterEach(() => {
  mockStore.clear();
});

describe('secure-storage (native, expo-secure-store backed)', () => {
  it('round-trips: set → get returns the same value', async () => {
    await setRefreshToken('rt-abc');
    expect(await getRefreshToken()).toBe('rt-abc');
    expect(ss.setItemAsync).toHaveBeenCalledWith(REFRESH_TOKEN_KEY, 'rt-abc');
    expect(ss.getItemAsync).toHaveBeenLastCalledWith(REFRESH_TOKEN_KEY);
  });

  it('getRefreshToken returns null when no token has been stored', async () => {
    expect(await getRefreshToken()).toBeNull();
  });

  it('getRefreshToken returns null when SecureStore.getItemAsync throws (corrupted store / biometric denied)', async () => {
    ss.getItemAsync.mockRejectedValueOnce(new Error('keychain locked'));
    expect(await getRefreshToken()).toBeNull();
  });

  it('clearRefreshToken removes the value', async () => {
    await setRefreshToken('rt');
    await clearRefreshToken();
    expect(await getRefreshToken()).toBeNull();
    expect(ss.deleteItemAsync).toHaveBeenCalledWith(REFRESH_TOKEN_KEY);
  });

  it('clearRefreshToken swallows delete errors (idempotent)', async () => {
    ss.deleteItemAsync.mockRejectedValueOnce(new Error('not found'));
    await expect(clearRefreshToken()).resolves.toBeUndefined();
  });
});
