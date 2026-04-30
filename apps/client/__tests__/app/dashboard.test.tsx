/**
 * Phase 4c — DashboardScreen now reads `useTransactions` so it
 * needs a TanStack QueryClient; sign-out moved to the topbar
 * (covered by `friends/nav.test.tsx`), so the old `dashboard-signout`
 * tests are removed here.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { Toaster, useToasterStore } from '~/components/ui/Toaster';
import { useAuthStore } from '~/lib/auth-store';

import { server } from '../msw-handlers';

import { mockExpoRouter, resetRouterMock } from './_router-mock';

mockExpoRouter();

const DashboardScreen = (await import('~/app/(app)/dashboard')).default;

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0, gcTime: 60_000 },
      mutations: { retry: false },
    },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function renderDashboard() {
  const Wrapper = makeWrapper();
  return render(
    <Wrapper>
      <DashboardScreen />
      <Toaster />
    </Wrapper>,
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
  it('renders user name + currency from the auth store', async () => {
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

  it('shows the seeded transaction in the recent activity list', async () => {
    useAuthStore.setState({
      user: { user_id: 'u', name: 'Alice', currency: 'USD' },
      accessToken: 't',
      idToken: 'i',
      loading: false,
    });
    renderDashboard();
    await waitFor(() => expect(screen.getByTestId('dashboard-list')).toBeInTheDocument());
    expect(screen.getByTestId('txn-row-01J0000000000000000000TX1')).toBeInTheDocument();
  });

  it('renders the Add transaction CTA', () => {
    useAuthStore.setState({
      user: { user_id: 'u', name: 'Alice', currency: 'USD' },
      accessToken: 't',
      idToken: 'i',
      loading: false,
    });
    renderDashboard();
    expect(screen.getByTestId('dashboard-add-txn')).toBeInTheDocument();
  });
});

describe('DashboardScreen — empty state', () => {
  it('renders the dashboard-empty card when no transactions', async () => {
    server.use(
      http.get('http://localhost/v1/transactions', () =>
        HttpResponse.json({ items: [], next_cursor: null }, { status: 200 }),
      ),
    );
    useAuthStore.setState({
      user: { user_id: 'u', name: 'Alice', currency: 'USD' },
      accessToken: 't',
      idToken: 'i',
      loading: false,
    });
    renderDashboard();
    await waitFor(() => expect(screen.getByTestId('dashboard-empty')).toBeInTheDocument());
    expect(screen.getByTestId('dashboard-empty-add')).toBeInTheDocument();
  });
});

describe('DashboardScreen — interactions', () => {
  it('opens the add-transaction sheet when the header CTA is tapped', async () => {
    useAuthStore.setState({
      user: { user_id: 'u', name: 'Alice', currency: 'USD' },
      accessToken: 't',
      idToken: 'i',
      loading: false,
    });
    renderDashboard();
    fireEvent.click(screen.getByTestId('dashboard-add-txn'));
    await waitFor(() => expect(screen.getByTestId('add-txn-sheet')).toBeInTheDocument());
  });

  it('routes to the txn detail page when a row is tapped', async () => {
    useAuthStore.setState({
      user: { user_id: 'u', name: 'Alice', currency: 'USD' },
      accessToken: 't',
      idToken: 'i',
      loading: false,
    });
    renderDashboard();
    await waitFor(() => expect(screen.getByTestId('dashboard-list')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('txn-row-01J0000000000000000000TX1'));
    // Router push happened — the test mock's call list includes a `push`.
    const { getRouterMock } = await import('./_router-mock');
    expect(
      getRouterMock().calls.some(
        (c) => c.kind === 'push' && c.href === '/transactions/01J0000000000000000000TX1',
      ),
    ).toBe(true);
  });
});
