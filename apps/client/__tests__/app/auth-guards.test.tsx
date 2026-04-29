import { render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { useAuthStore } from '~/lib/auth-store';

import { getRouterMock, mockExpoRouter, resetRouterMock } from './_router-mock';

mockExpoRouter();

const AuthLayout = (await import('~/app/(auth)/_layout')).default;
const AppLayout = (await import('~/app/(app)/_layout')).default;
const NotFound = (await import('~/app/+not-found')).default;

beforeEach(() => {
  resetRouterMock();
  useAuthStore.getState()._clear();
  useAuthStore.setState({ loading: false });
});
afterEach(() => {
  useAuthStore.getState()._clear();
});

describe('(auth)/_layout', () => {
  it('renders children when no user', () => {
    render(<AuthLayout />);
    expect(getRouterMock().calls).toEqual([]);
  });

  it('redirects to /dashboard when a user exists', () => {
    useAuthStore.setState({
      user: { user_id: 'u', name: 'A', currency: 'USD' },
      loading: false,
    });
    render(<AuthLayout />);
    expect(getRouterMock().calls).toContainEqual({ kind: 'replace', href: '/dashboard' });
  });
});

describe('(app)/_layout', () => {
  it('redirects to /login when no user', () => {
    render(<AppLayout />);
    expect(getRouterMock().calls).toContainEqual({ kind: 'replace', href: '/login' });
  });

  it('renders children when authenticated', () => {
    useAuthStore.setState({
      user: { user_id: 'u', name: 'A', currency: 'USD' },
      loading: false,
    });
    render(<AppLayout />);
    expect(getRouterMock().calls).toEqual([]);
  });

  it('renders nothing while loading', () => {
    useAuthStore.setState({ user: null, loading: true });
    const { container } = render(<AppLayout />);
    expect(container.textContent).toBe('');
    expect(getRouterMock().calls).toEqual([]);
  });
});

describe('+not-found', () => {
  it('renders a generic 404', () => {
    const { getByText } = render(<NotFound />);
    expect(getByText('404')).toBeInTheDocument();
  });
});
