/**
 * Top-bar nav + N16 — unauthenticated visit redirects to /login.
 */
import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { useAuthStore } from '~/lib/auth-store';

import { getRouterMock, mockExpoRouter, resetRouterMock, setPathname } from '../_router-mock';

mockExpoRouter();

const AppLayout = (await import('~/app/(app)/_layout')).default;

beforeEach(() => {
  resetRouterMock();
  useAuthStore.getState()._clear();
  useAuthStore.setState({ loading: false });
});
afterEach(() => {
  useAuthStore.getState()._clear();
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
});
