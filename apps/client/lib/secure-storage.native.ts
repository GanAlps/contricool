/**
 * Native refresh-token persistence via `expo-secure-store`.
 *
 * On iOS this maps to the Keychain; on Android, to
 * EncryptedSharedPreferences. Both are wiped on app uninstall and on
 * an OS-level credential reset, which is exactly the security model we
 * want — a refresh token that can't be lifted by another app on the
 * device.
 *
 * `getRefreshToken` swallows read errors and returns `null` so a
 * corrupted secure store surfaces as "not signed in" rather than
 * crashing the app at boot. The auth driver's higher-level flow
 * already treats a null/expired refresh as a clean re-login prompt.
 */

import * as SecureStore from 'expo-secure-store';

export const REFRESH_TOKEN_KEY = 'contricool.refresh_token';

export async function getRefreshToken(): Promise<string | null> {
  try {
    return await SecureStore.getItemAsync(REFRESH_TOKEN_KEY);
  } catch {
    return null;
  }
}

export async function setRefreshToken(value: string): Promise<void> {
  await SecureStore.setItemAsync(REFRESH_TOKEN_KEY, value);
}

export async function clearRefreshToken(): Promise<void> {
  try {
    await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
  } catch {
    // Best-effort: deleting a non-existent key throws on some platforms.
  }
}
