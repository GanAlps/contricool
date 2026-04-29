import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { Toaster, useToasterStore } from '~/components/ui/Toaster';
import { useAuthStore } from '~/lib/auth-store';

import { server } from '../msw-handlers';

import { getRouterMock, mockExpoRouter, resetRouterMock } from './_router-mock';

mockExpoRouter();

const DashboardScreen = (await import('~/app/(app)/dashboard')).default;

function renderDashboard() {
  return render(
    <>
      <DashboardScreen />
      <Toaster />
    </>,
  );
}

beforeEach(() => {
  resetRouterMock();
  useAuthStore.getState()._clear();
  useToasterStore.getState().clear();
});
afterEach(() => {
  useAuthStore.getState()._clear();
  useToasterStore.getState().clear();
});

describe('DashboardScreen', () => {
  it('renders user name + currency from the auth store', () => {
    useAuthStore.setState({
      user: { user_id: 'u', name: 'Alice', currency: 'USD' },
      accessToken: 't',
      idToken: 'i',
      loading: false,
    });
    renderDashboard();
    expect(screen.getByText(/Welcome, Alice/)).toBeInTheDocument();
    expect(screen.getByTestId('dashboard-currency')).toHaveTextContent('USD');
  });

  it('renders fallback "—" when currency is missing', () => {
    useAuthStore.setState({
      user: { user_id: 'u', name: 'Alice', currency: undefined as unknown as 'USD' },
      accessToken: 't',
      idToken: 'i',
      loading: false,
    });
    renderDashboard();
    expect(screen.getByTestId('dashboard-currency')).toHaveTextContent('—');
  });

  it('renders fallback "friend" when user is missing', () => {
    renderDashboard();
    expect(screen.getByText(/Welcome, friend/)).toBeInTheDocument();
  });

  it('signs out and redirects to /login on success', async () => {
    useAuthStore.setState({
      user: { user_id: 'u', name: 'Alice', currency: 'USD' },
      accessToken: 't',
      idToken: 'i',
      loading: false,
    });
    renderDashboard();
    fireEvent.click(screen.getByTestId('dashboard-signout'));
    await waitFor(() =>
      expect(getRouterMock().calls).toContainEqual({ kind: 'replace', href: '/login' }),
    );
    expect(useAuthStore.getState().user).toBeNull();
  });

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
    renderDashboard();
    fireEvent.click(screen.getByTestId('dashboard-signout'));
    expect(await screen.findByTestId('toast-error')).toBeInTheDocument();
    await waitFor(() =>
      expect(getRouterMock().calls).toContainEqual({ kind: 'replace', href: '/login' }),
    );
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().accessToken).toBeNull();
  });
});
