import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { useAuthStore } from '~/lib/auth-store';

import { server } from '../msw-handlers';

function b64url(input: string): string {
  return btoa(input).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_');
}
function makeIdToken(claims: Record<string, unknown>): string {
  return `${b64url('{}')}.${b64url(JSON.stringify(claims))}.sig`;
}

describe('useAuthStore', () => {
  beforeEach(() => {
    useAuthStore.getState()._clear();
    useAuthStore.setState({ loading: true });
  });
  afterEach(() => {
    useAuthStore.getState()._clear();
  });

  it('signIn populates user + tokens on success', async () => {
    await useAuthStore.getState().signIn({ email: 'a@b.com', password: 'P@ssword123!' });
    const s = useAuthStore.getState();
    expect(s.accessToken).toBe('access-jwt');
    expect(s.idToken).toBe('id-jwt');
    expect(s.user?.user_id).toBeTruthy();
    expect(s.loading).toBe(false);
  });

  it('signIn surfaces ApiErrorException on bad credentials', async () => {
    server.use(
      http.post('http://localhost/v1/auth/login', () =>
        HttpResponse.json(
          { error: { code: 'INVALID_CREDENTIALS', message: 'nope', request_id: 'r' } },
          { status: 401 },
        ),
      ),
    );
    await expect(
      useAuthStore.getState().signIn({ email: 'a@b.com', password: 'wrong' }),
    ).rejects.toMatchObject({ error: { code: 'INVALID_CREDENTIALS' } });
    expect(useAuthStore.getState().user).toBeNull();
  });

  it('signOut clears state on driver success', async () => {
    useAuthStore.setState({
      user: { user_id: 'u', name: 'A', currency: 'USD' },
      accessToken: 't',
      idToken: 'i',
      loading: false,
    });
    await useAuthStore.getState().signOut();
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().accessToken).toBeNull();
  });

  it('signOut clears state and re-throws when driver throws (N16)', async () => {
    server.use(
      http.post('http://localhost/v1/auth/logout', () =>
        HttpResponse.json(
          { error: { code: 'INTERNAL', message: 'x', request_id: 'r' } },
          { status: 500 },
        ),
      ),
    );
    useAuthStore.setState({
      user: { user_id: 'u', name: 'A', currency: 'USD' },
      accessToken: 't',
      idToken: 'i',
      loading: false,
    });
    await expect(useAuthStore.getState().signOut()).rejects.toMatchObject({
      error: { code: 'INTERNAL' },
    });
    // State must still be cleared regardless.
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().accessToken).toBeNull();
  });

  it('refreshSession populates tokens + user on success (N14)', async () => {
    const tok = makeIdToken({ 'custom:user_id': 'u-1', name: 'Alice', 'custom:currency': 'USD' });
    server.use(
      http.post('http://localhost/v1/auth/refresh', () =>
        HttpResponse.json({ access_token: 'a-1', id_token: tok, expires_in: 3600 }),
      ),
    );
    await useAuthStore.getState().refreshSession();
    const s = useAuthStore.getState();
    expect(s.accessToken).toBe('a-1');
    expect(s.user).toEqual({ user_id: 'u-1', name: 'Alice', currency: 'USD' });
    expect(s.loading).toBe(false);
  });

  it('refreshSession leaves store empty on failure (N13)', async () => {
    server.use(
      http.post('http://localhost/v1/auth/refresh', () =>
        HttpResponse.json(
          { error: { code: 'REFRESH_FAILED', message: 'x', request_id: 'r' } },
          { status: 401 },
        ),
      ),
    );
    await useAuthStore.getState().refreshSession();
    const s = useAuthStore.getState();
    expect(s.user).toBeNull();
    expect(s.accessToken).toBeNull();
    expect(s.loading).toBe(false);
  });

  it('signUp / verifyEmail / resendEmailCode / forgot / reset are pass-throughs', async () => {
    await useAuthStore.getState().signUp({
      email: 'a@b.com',
      password: 'P@ssword123!',
      name: 'A',
      currency: 'USD',
    });
    await useAuthStore.getState().verifyEmail({ email: 'a@b.com', code: '123456' });
    await useAuthStore.getState().resendEmailCode({ email: 'a@b.com' });
    await useAuthStore.getState().forgotPassword({ email: 'a@b.com' });
    await useAuthStore.getState().resetPassword({
      email: 'a@b.com',
      code: '123456',
      new_password: 'NewP@ssword123!',
    });
  });

  it('SDK 401-retry replays with new id token + writes new tokens to store', async () => {
    const oldId = makeIdToken({ 'custom:user_id': 'u', name: 'A', 'custom:currency': 'USD' });
    const newId = makeIdToken({ 'custom:user_id': 'u', name: 'A2', 'custom:currency': 'USD' });
    useAuthStore.setState({
      accessToken: 'old-tok',
      idToken: oldId,
      user: { user_id: 'u', name: 'A', currency: 'USD' },
      loading: false,
    });
    const bearers: (string | null)[] = [];
    server.use(
      http.get('http://localhost/v1/protected', ({ request }) => {
        const auth = request.headers.get('authorization');
        bearers.push(auth);
        if (auth === `Bearer ${newId}`) {
          return HttpResponse.json({ ok: true });
        }
        return HttpResponse.json(
          { error: { code: 'UNAUTHENTICATED', message: 'x', request_id: 'r' } },
          { status: 401 },
        );
      }),
      http.post('http://localhost/v1/auth/refresh', () =>
        HttpResponse.json({
          access_token: 'new-tok',
          id_token: newId,
          expires_in: 3600,
        }),
      ),
    );
    const { apiClient } = await import('~/lib/api');
    await (
      apiClient as unknown as {
        GET: (p: string) => Promise<{ data?: unknown }>;
      }
    ).GET('/protected');
    expect(useAuthStore.getState().accessToken).toBe('new-tok');
    expect(useAuthStore.getState().user?.name).toBe('A2');
    // Phase 2c two-token contract: id token rides in Authorization,
    // not the access token.
    expect(bearers).toEqual([`Bearer ${oldId}`, `Bearer ${newId}`]);
  });

  it('SDK clears store when refresh-and-retry fails', async () => {
    useAuthStore.setState({
      user: { user_id: 'u', name: 'A', currency: 'USD' },
      accessToken: 't',
      idToken: 'i',
      loading: false,
    });
    server.use(
      http.get('http://localhost/v1/protected', () =>
        HttpResponse.json(
          { error: { code: 'UNAUTHENTICATED', message: 'x', request_id: 'r' } },
          { status: 401 },
        ),
      ),
      http.post('http://localhost/v1/auth/refresh', () =>
        HttpResponse.json(
          { error: { code: 'REFRESH_FAILED', message: 'x', request_id: 'r' } },
          { status: 401 },
        ),
      ),
    );
    const { apiClient } = await import('~/lib/api');
    await expect(
      (
        apiClient as unknown as {
          GET: (p: string) => Promise<{ data?: unknown }>;
        }
      ).GET('/protected'),
    ).rejects.toMatchObject({ error: { code: 'UNAUTHENTICATED' } });
    expect(useAuthStore.getState().user).toBeNull();
  });
});
