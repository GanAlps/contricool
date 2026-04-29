import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { useAuthStore } from '~/lib/auth-store';

import { server } from '../msw-handlers';

import { getRouterMock, mockExpoRouter, resetRouterMock } from './_router-mock';

mockExpoRouter();

const Index = (await import('~/app/index')).default;
const RootLayout = (await import('~/app/_layout')).default;

function b64url(input: string): string {
  return btoa(input).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_');
}
function makeIdToken(claims: Record<string, unknown>): string {
  return `${b64url('{}')}.${b64url(JSON.stringify(claims))}.sig`;
}

beforeEach(() => {
  resetRouterMock();
  useAuthStore.getState()._clear();
  useAuthStore.setState({ loading: true });
});
afterEach(() => {
  useAuthStore.getState()._clear();
});

describe('Index redirect', () => {
  it('shows the boot Spinner while loading=true', () => {
    render(<Index />);
    expect(screen.getByTestId('boot-spinner')).toBeInTheDocument();
    expect(getRouterMock().calls).toEqual([]);
  });

  it('N14: hard-reload with valid cookie → refreshSession 200 → redirects to /dashboard', async () => {
    const tok = makeIdToken({ 'custom:user_id': 'u-1', name: 'Alice', 'custom:currency': 'USD' });
    server.use(
      http.post('/v1/auth/refresh', () =>
        HttpResponse.json({ access_token: 'a', id_token: tok, expires_in: 3600 }),
      ),
    );
    await useAuthStore.getState().refreshSession();
    render(<Index />);
    await waitFor(() =>
      expect(getRouterMock().calls).toContainEqual({ kind: 'replace', href: '/dashboard' }),
    );
  });

  it('N13: hard-reload with no cookie → refresh 401 → redirects to /login', async () => {
    server.use(
      http.post('/v1/auth/refresh', () =>
        HttpResponse.json(
          { error: { code: 'REFRESH_FAILED', message: 'x', request_id: 'r' } },
          { status: 401 },
        ),
      ),
    );
    await useAuthStore.getState().refreshSession();
    render(<Index />);
    await waitFor(() =>
      expect(getRouterMock().calls).toContainEqual({ kind: 'replace', href: '/login' }),
    );
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().accessToken).toBeNull();
  });

  it('N15: refresh network error → store empty → /login redirect', async () => {
    server.use(
      http.post('/v1/auth/refresh', () =>
        HttpResponse.json(
          { error: { code: 'INTERNAL', message: 'x', request_id: 'r' } },
          { status: 500 },
        ),
      ),
    );
    await useAuthStore.getState().refreshSession();
    render(<Index />);
    await waitFor(() =>
      expect(getRouterMock().calls).toContainEqual({ kind: 'replace', href: '/login' }),
    );
  });
});

describe('RootLayout boot probe', () => {
  it('runs refreshSession on mount and clears loading', async () => {
    server.use(
      http.post('/v1/auth/refresh', () =>
        HttpResponse.json(
          { error: { code: 'REFRESH_FAILED', message: 'x', request_id: 'r' } },
          { status: 401 },
        ),
      ),
    );
    render(<RootLayout />);
    await waitFor(() => expect(useAuthStore.getState().loading).toBe(false));
  });
});
