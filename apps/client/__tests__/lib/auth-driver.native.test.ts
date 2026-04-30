/**
 * Native auth driver — auth-store stays unchanged; the only platform
 * delta is that refresh tokens persist via secure-storage helpers
 * instead of riding in an HttpOnly cookie. Tests cover RED LINE 3
 * negative cases for the persistence path:
 *
 *  - login persists refresh_token from response body
 *  - signOut clears storage even if API call fails
 *  - explicit refreshSession passes the stored token to the backend
 *  - explicit refreshSession with no stored token surfaces 401
 *
 * `expo-secure-store` is mocked at the secure-storage module level so
 * the driver-under-test sees an in-memory store and we can assert on
 * the storage operations directly.
 */

import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// `vi.mock` calls are hoisted to the top of the file, so any
// references they capture must also be hoisted via `vi.hoisted`.
const { memory, storage } = vi.hoisted(() => {
  const mem = new Map<string, string>();
  return {
    memory: mem,
    storage: {
      getRefreshToken: async () => mem.get('rt') ?? null,
      setRefreshToken: async (v: string) => {
        mem.set('rt', v);
      },
      clearRefreshToken: async () => {
        mem.delete('rt');
      },
    },
  };
});

const setRefreshTokenSpy = vi.fn(storage.setRefreshToken);
const getRefreshTokenSpy = vi.fn(storage.getRefreshToken);
const clearRefreshTokenSpy = vi.fn(storage.clearRefreshToken);

vi.mock('~/lib/secure-storage', () => ({
  getRefreshToken: (...args: []) => getRefreshTokenSpy(...args),
  setRefreshToken: (...args: [string]) => setRefreshTokenSpy(...args),
  clearRefreshToken: (...args: []) => clearRefreshTokenSpy(...args),
}));

import driver from '~/lib/auth-driver.native';
import { useAuthStore } from '~/lib/auth-store';

import { server } from '../msw-handlers';

beforeEach(() => {
  memory.clear();
  getRefreshTokenSpy.mockClear();
  setRefreshTokenSpy.mockClear();
  clearRefreshTokenSpy.mockClear();
  useAuthStore.getState()._clear();
});
afterEach(() => {
  memory.clear();
  useAuthStore.getState()._clear();
});

describe('nativeAuthDriver', () => {
  it('signUp posts to /auth/signup and returns the response (parity with web)', async () => {
    const r = await driver.signUp({
      email: 'a@b.com',
      password: 'P@ssword123!',
      name: 'A',
      currency: 'USD',
    });
    expect(r.user_id).toBeTruthy();
    expect(r.status).toBe('PENDING_VERIFICATION');
  });

  it('verifyEmail posts and resolves on 200', async () => {
    const r = await driver.verifyEmail({ email: 'a@b.com', code: '123456' });
    expect(r.email_verified).toBe(true);
  });

  it('resendEmailCode posts and resolves on 202', async () => {
    const r = await driver.resendEmailCode({ email: 'a@b.com' });
    expect(r.status).toBe('RESENT');
  });

  it('signIn sends X-Client-Platform: native and persists refresh_token from body', async () => {
    let observedHeader: string | null = null;
    server.use(
      http.post('http://localhost/v1/auth/login', async ({ request }) => {
        observedHeader = request.headers.get('x-client-platform');
        return HttpResponse.json(
          {
            access_token: 'access-jwt',
            id_token: 'id-jwt',
            expires_in: 3600,
            user: { user_id: 'u1', name: 'A', currency: 'USD' },
            refresh_token: 'rt-from-server',
          },
          { status: 200 },
        );
      }),
    );
    const r = await driver.signIn({ email: 'a@b.com', password: 'P@ssword123!' });
    expect(observedHeader).toBe('native');
    expect(r.access_token).toBe('access-jwt');
    expect(r.id_token).toBe('id-jwt');
    expect(setRefreshTokenSpy).toHaveBeenCalledWith('rt-from-server');
    expect(memory.get('rt')).toBe('rt-from-server');
    // The refresh_token field must NOT be exposed to upstream callers
    // — auth-store.ts doesn't model it.
    expect((r as { refresh_token?: string }).refresh_token).toBeUndefined();
  });

  it('signIn does not persist when server omits refresh_token (defensive)', async () => {
    server.use(
      http.post('http://localhost/v1/auth/login', () =>
        HttpResponse.json(
          {
            access_token: 'a',
            id_token: 'i',
            expires_in: 3600,
            user: { user_id: 'u1', name: 'A', currency: 'USD' },
            refresh_token: null,
          },
          { status: 200 },
        ),
      ),
    );
    await driver.signIn({ email: 'a@b.com', password: 'P@ssword123!' });
    expect(setRefreshTokenSpy).not.toHaveBeenCalled();
  });

  it('refreshSession reads from secure-storage and sends body + native header', async () => {
    memory.set('rt', 'persisted-rt');
    let observedBody: { refresh_token?: string | null } | null = null;
    let observedHeader: string | null = null;
    server.use(
      http.post('http://localhost/v1/auth/refresh', async ({ request }) => {
        observedHeader = request.headers.get('x-client-platform');
        observedBody = (await request.json()) as { refresh_token: string };
        return HttpResponse.json(
          { access_token: 'a2', id_token: 'i2', expires_in: 3600 },
          { status: 200 },
        );
      }),
    );
    const r = await driver.refreshSession();
    expect(observedHeader).toBe('native');
    expect(observedBody).toEqual({ refresh_token: 'persisted-rt' });
    expect(r.access_token).toBe('a2');
    expect(getRefreshTokenSpy).toHaveBeenCalled();
  });

  it('refreshSession with no stored token surfaces 401 from backend (clean re-login signal)', async () => {
    // No setItem — getRefreshToken returns null.
    server.use(
      http.post('http://localhost/v1/auth/refresh', () =>
        HttpResponse.json(
          {
            error: { code: 'MISSING_REFRESH_TOKEN', message: 'no rt', request_id: 'r' },
          },
          { status: 401 },
        ),
      ),
    );
    await expect(driver.refreshSession()).rejects.toMatchObject({
      error: { code: 'MISSING_REFRESH_TOKEN' },
    });
  });

  it('signOut clears secure-storage even when the API call fails (RED LINE 3 — partial sign-out)', async () => {
    memory.set('rt', 'still-here');
    useAuthStore.setState({ accessToken: 'a', idToken: 'i' });
    server.use(
      http.post('http://localhost/v1/auth/logout', () =>
        HttpResponse.json(
          { error: { code: 'INTERNAL', message: 'boom', request_id: 'r' } },
          { status: 500 },
        ),
      ),
    );
    await expect(driver.signOut()).rejects.toBeDefined();
    expect(clearRefreshTokenSpy).toHaveBeenCalled();
    expect(memory.has('rt')).toBe(false);
  });

  it('signOut clears storage on the happy path too', async () => {
    memory.set('rt', 'goodbye');
    useAuthStore.setState({ accessToken: 'a', idToken: 'i' });
    await expect(driver.signOut()).resolves.toBeUndefined();
    expect(memory.has('rt')).toBe(false);
  });

  it('forgotPassword posts and resolves on 202', async () => {
    const r = await driver.forgotPassword({ email: 'a@b.com' });
    expect(r.status).toBe('RESET_CODE_SENT');
  });

  it('resetPassword posts and resolves on 200', async () => {
    const r = await driver.resetPassword({
      email: 'a@b.com',
      code: '123456',
      new_password: 'NewP@ssword123!',
    });
    expect(r.password_reset).toBe(true);
  });

  it('signUp surfaces a 409 EMAIL_EXISTS as ApiErrorException (parity with web)', async () => {
    server.use(
      http.post('http://localhost/v1/auth/signup', () =>
        HttpResponse.json(
          { error: { code: 'EMAIL_EXISTS', message: 'taken', request_id: 'r1' } },
          { status: 409 },
        ),
      ),
    );
    await expect(
      driver.signUp({
        email: 'taken@b.com',
        password: 'P@ssword123!',
        name: 'X',
        currency: 'USD',
      }),
    ).rejects.toMatchObject({ error: { code: 'EMAIL_EXISTS' } });
  });
});
