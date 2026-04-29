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
      http.post('/v1/auth/login', () =>
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

  it('signOut clears state even when driver throws (N16)', async () => {
    server.use(
      http.post('/v1/auth/logout', () =>
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
    await useAuthStore.getState().signOut();
    expect(useAuthStore.getState().user).toBeNull();
  });

  it('refreshSession populates tokens + user on success (N14)', async () => {
    const tok = makeIdToken({ 'custom:user_id': 'u-1', name: 'Alice', 'custom:currency': 'USD' });
    server.use(
      http.post('/v1/auth/refresh', () =>
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
      http.post('/v1/auth/refresh', () =>
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

  it('apiFetch 401-retry uses store.accessToken as bearer', async () => {
    useAuthStore.setState({
      accessToken: 'old-tok',
      idToken: makeIdToken({ 'custom:user_id': 'u', name: 'A', 'custom:currency': 'USD' }),
      user: { user_id: 'u', name: 'A', currency: 'USD' },
      loading: false,
    });
    const bearers: (string | null)[] = [];
    server.use(
      http.get('/v1/protected', ({ request }) => {
        bearers.push(request.headers.get('authorization'));
        const auth = request.headers.get('authorization');
        if (auth === 'Bearer new-tok') {
          return HttpResponse.json({ ok: true });
        }
        return HttpResponse.json(
          { error: { code: 'UNAUTHENTICATED', message: 'x', request_id: 'r' } },
          { status: 401 },
        );
      }),
      http.post('/v1/auth/refresh', () =>
        HttpResponse.json({
          access_token: 'new-tok',
          id_token: makeIdToken({ 'custom:user_id': 'u', name: 'A2', 'custom:currency': 'USD' }),
          expires_in: 3600,
        }),
      ),
    );
    const { apiFetch } = await import('~/lib/api');
    const r = await apiFetch('/protected');
    expect(r).toEqual({ ok: true });
    expect(useAuthStore.getState().accessToken).toBe('new-tok');
    expect(useAuthStore.getState().user?.name).toBe('A2');
    expect(bearers).toEqual(['Bearer old-tok', 'Bearer new-tok']);
  });

  it('forceSignOut accessor clears the store', async () => {
    useAuthStore.setState({
      user: { user_id: 'u', name: 'A', currency: 'USD' },
      accessToken: 't',
      idToken: 'i',
      loading: false,
    });
    server.use(
      http.get('/v1/protected', () =>
        HttpResponse.json(
          { error: { code: 'UNAUTHENTICATED', message: 'x', request_id: 'r' } },
          { status: 401 },
        ),
      ),
      http.post('/v1/auth/refresh', () =>
        HttpResponse.json(
          { error: { code: 'REFRESH_FAILED', message: 'x', request_id: 'r' } },
          { status: 401 },
        ),
      ),
    );
    const { apiFetch } = await import('~/lib/api');
    await expect(apiFetch('/protected')).rejects.toMatchObject({
      error: { code: 'UNAUTHENTICATED' },
    });
    expect(useAuthStore.getState().user).toBeNull();
  });
});
