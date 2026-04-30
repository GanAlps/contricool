/**
 * Top-bar nav + N16 — unauthenticated visit redirects to /login.
 *
 * The topbar owns the sign-out button (Phase 4c moved it off the
 * dashboard); this file is the home for sign-out UI tests, including
 * the network-failure path that proves a transport error still
 * clears local state, surfaces a toast, and redirects to /login.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { Toaster, useToasterStore } from '~/components/ui/Toaster';
import { useAuthStore } from '~/lib/auth-store';

import { server } from '../../msw-handlers';
import { getRouterMock, mockExpoRouter, resetRouterMock, setPathname } from '../_router-mock';

mockExpoRouter();

const AppLayout = (await import('~/app/(app)/_layout')).default;

beforeEach(() => {
  resetRouterMock();
  useAuthStore.getState()._clear();
  useAuthStore.setState({ loading: false });
  useToasterStore.getState().clear();
});
afterEach(() => {
  useAuthStore.getState()._clear();
  useToasterStore.getState().clear();
});

describe('(app)/_layout top-bar nav', () => {
  it('renders Dashboard / Friends / Sign-out when authenticated', () => {
    useAuthStore.setState({
      user: { user_id: 'me', name: 'Me', currency: 'USD' },
      loading: false,
    });
    render(<AppLayout />);
    expect(screen.getByTestId('app-topbar')).toBeInTheDocument();
    expect(screen.getByTestId('navlink-dashboard')).toBeInTheDocument();
    expect(screen.getByTestId('navlink-friends')).toBeInTheDocument();
    expect(screen.getByTestId('topbar-signout')).toBeInTheDocument();
    expect(screen.getByTestId('topbar-user')).toHaveTextContent('Me');
  });

  it('marks the Dashboard link active on /dashboard', () => {
    setPathname('/dashboard');
    useAuthStore.setState({
      user: { user_id: 'me', name: 'Me', currency: 'USD' },
      loading: false,
    });
    render(<AppLayout />);
    expect(screen.getByTestId('navlink-dashboard').getAttribute('aria-current')).toBe('page');
    expect(screen.getByTestId('navlink-friends').getAttribute('aria-current')).toBeNull();
  });

  it('marks the Friends link active on /friends/<id>', () => {
    setPathname('/friends/abc');
    useAuthStore.setState({
      user: { user_id: 'me', name: 'Me', currency: 'USD' },
      loading: false,
    });
    render(<AppLayout />);
    expect(screen.getByTestId('navlink-friends').getAttribute('aria-current')).toBe('page');
  });

  // N16 is also exercised by `auth-guards.test.tsx`; we keep an
  // in-context copy here so a future refactor of the topbar renders
  // a matching guard regression next to its companion tests.
  it('N16: unauthenticated visit redirects to /login', () => {
    render(<AppLayout />);
    expect(getRouterMock().calls).toContainEqual({ kind: 'replace', href: '/login' });
  });

  // The dashboard had a duplicate sign-out button up to Phase 3b.
  // Phase 4c removed it (the topbar is the canonical home for the
  // action). The failure-path test followed the button — this
  // regression keeps the contract honest from the topbar.
  it('N16: sign-out network failure clears state, surfaces a toast, and redirects', async () => {
    server.use(
      http.post('http://localhost/v1/auth/logout', () =>
        HttpResponse.json(
          { error: { code: 'INTERNAL', message: 'oops', request_id: 'r' } },
          { status: 500 },
        ),
      ),
    );
    useAuthStore.setState({
      user: { user_id: 'u', name: 'Alice', currency: 'USD' },
      accessToken: 't',
      idToken: 'i',
      loading: false,
    });
    render(
      <>
        <AppLayout />
        <Toaster />
      </>,
    );
    fireEvent.click(screen.getByTestId('topbar-signout'));
    expect(await screen.findByTestId('toast-error')).toBeInTheDocument();
    await waitFor(() =>
      expect(getRouterMock().calls).toContainEqual({ kind: 'replace', href: '/login' }),
    );
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().accessToken).toBeNull();
  });
});
