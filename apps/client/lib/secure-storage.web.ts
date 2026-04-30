/**
 * Secure-storage stub for the web target.
 *
 * Web persists the refresh token in an HttpOnly Set-Cookie set by
 * `/v1/auth/login` (Design 4) — JavaScript cannot read or write that
 * value, so every helper here is a no-op. The SDK's `getRefreshToken`
 * callback returns `null`, which makes the auth-refresh middleware
 * fall back to its cookie-based path.
 *
 * The `.native.ts` sibling provides the real implementation backed by
 * `expo-secure-store` (iOS Keychain / Android EncryptedSharedPreferences).
 * Metro's platform resolver picks the right file at bundle time.
 */

export async function getRefreshToken(): Promise<string | null> {
  return null;
}

export async function setRefreshToken(_value: string): Promise<void> {
  // Intentional no-op on web.
}

export async function clearRefreshToken(): Promise<void> {
  // Intentional no-op on web.
}
