import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import driver from '~/lib/auth-driver.web';
import { useAuthStore } from '~/lib/auth-store';

import { server } from '../msw-handlers';

beforeEach(() => {
  useAuthStore.getState()._clear();
});
afterEach(() => {
  useAuthStore.getState()._clear();
});

describe('webAuthDriver', () => {
  it('signUp posts to /auth/signup and returns the response', async () => {
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

  it('signIn posts and returns tokens + user', async () => {
    const r = await driver.signIn({ email: 'a@b.com', password: 'P@ssword123!' });
    expect(r.access_token).toBe('access-jwt');
    expect(r.id_token).toBe('id-jwt');
    expect(r.user.user_id).toBeTruthy();
  });

  it('refreshSession posts and returns new tokens', async () => {
    const r = await driver.refreshSession();
    expect(r.access_token).toBe('access-jwt-2');
    expect(r.id_token).toBe('id-jwt-2');
  });

  it('signOut posts with both id-token Authorization + access-token header and resolves on 204', async () => {
    useAuthStore.setState({ accessToken: 'access-jwt', idToken: 'id-jwt' });
    await expect(driver.signOut()).resolves.toBeUndefined();
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

  it('signUp surfaces a 409 EMAIL_EXISTS as ApiErrorException', async () => {
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
