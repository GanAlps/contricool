/**
 * Phase 4c — transactions list screen integration tests.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { useAuthStore } from '~/lib/auth-store';

import { withProviders } from '../../test-utils';
import { mockExpoRouter, resetRouterMock, setSearchParams } from '../_router-mock';

mockExpoRouter();

const TransactionsListScreen = (await import('~/app/(app)/transactions/index')).default;

beforeEach(() => {
  resetRouterMock();
  setSearchParams({});
  useAuthStore.setState({
    user: { user_id: 'me', name: 'Me', currency: 'USD' },
    accessToken: 'a',
    idToken: 'i',
    loading: false,
  });
});
afterEach(() => {
  useAuthStore.getState()._clear();
});

describe('TransactionsListScreen', () => {
  it('renders the seeded transaction', async () => {
    render(withProviders(<TransactionsListScreen />));
    await waitFor(() => expect(screen.getByTestId('txns-list')).toBeInTheDocument());
    expect(screen.getByText('Dinner')).toBeInTheDocument();
  });

  it('shows the All filter chip and an Add CTA', async () => {
    render(withProviders(<TransactionsListScreen />));
    expect(screen.getByTestId('filter-chip-all')).toBeInTheDocument();
    expect(screen.getByTestId('txns-add')).toBeInTheDocument();
  });
});
