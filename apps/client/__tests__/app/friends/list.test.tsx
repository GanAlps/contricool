/**
 * Phase 3b friend list tests — happy path + N9–N11 (privacy /
 * rate-limit / network error) per requirements.md.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { Toaster, useToasterStore } from '~/components/ui/Toaster';
import { useAuthStore } from '~/lib/auth-store';

import { server } from '../../msw-handlers';
import { withProviders } from '../../test-utils';
import { getRouterMock, mockExpoRouter, resetRouterMock } from '../_router-mock';

mockExpoRouter();

const FriendsListScreen = (await import('~/app/(app)/friends/index')).default;

function renderList() {
  return render(
    withProviders(
      <>
        <FriendsListScreen />
        <Toaster />
      </>,
    ),
  );
}

beforeEach(() => {
  resetRouterMock();
  useAuthStore.setState({
    user: { user_id: 'me', name: 'Me', currency: 'USD' },
    accessToken: 'a',
    idToken: 'i',
    loading: false,
  });
  useToasterStore.getState().clear();
});
afterEach(() => {
  useAuthStore.getState()._clear();
  useToasterStore.getState().clear();
});

describe('FriendsListScreen — populated', () => {
  it('renders rows sorted alphabetically and routes on tap', async () => {
    // Lowercase 'alice' is intentional: it proves the sort is
    // case-insensitive (the screen uses `localeCompare(..., 'base')`),
    // not just a typo.
    server.use(
      http.get('http://localhost/v1/friends', () =>
        HttpResponse.json(
          {
            items: [
              {
                user_id: 'b',
                name: 'Bob',
                currency: 'USD',
                since: '2026-01-01T00:00:00Z',
              },
              {
                user_id: 'a',
                name: 'alice',
                currency: 'USD',
                since: '2026-01-02T00:00:00Z',
              },
            ],
            next_cursor: null,
          },
          { status: 200 },
        ),
      ),
    );
    renderList();
    await waitFor(() => expect(screen.getByTestId('friends-list')).toBeInTheDocument());
    const rows = screen.getAllByText(/^(alice|Bob)$/);
    expect(rows[0]).toHaveTextContent('alice');
    expect(rows[1]).toHaveTextContent('Bob');
    fireEvent.click(screen.getByTestId('friend-row-a'));
    expect(getRouterMock().calls).toEqual([{ kind: 'push', href: '/friends/a' }]);
  });
});

describe('FriendsListScreen — empty', () => {
  it('renders the empty card with CTA', async () => {
    server.use(
      http.get('http://localhost/v1/friends', () =>
        HttpResponse.json({ items: [], next_cursor: null }, { status: 200 }),
      ),
    );
    renderList();
    await waitFor(() => expect(screen.getByTestId('friends-empty')).toBeInTheDocument());
    expect(screen.getByText(/No friends yet/)).toBeInTheDocument();
  });
});

describe('FriendsListScreen — error states', () => {
  it('N10: network/5xx error renders banner + retry', async () => {
    let calls = 0;
    server.use(
      http.get('http://localhost/v1/friends', () => {
        calls += 1;
        if (calls === 1) {
          return HttpResponse.json(
            { error: { code: 'INTERNAL_ERROR', message: 'down', request_id: 'r' } },
            { status: 500 },
          );
        }
        return HttpResponse.json({ items: [], next_cursor: null }, { status: 200 });
      }),
    );
    renderList();
    await waitFor(() => expect(screen.getByTestId('friends-error')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('friends-retry'));
    await waitFor(() => expect(screen.getByTestId('friends-empty')).toBeInTheDocument());
  });

  it('N9: RATE_LIMITED on initial load surfaces a toast', async () => {
    server.use(
      http.get('http://localhost/v1/friends', () =>
        HttpResponse.json(
          {
            error: {
              code: 'RATE_LIMITED',
              message: 'slow down',
              request_id: 'r',
              retry_after: 12,
            },
          },
          { status: 429 },
        ),
      ),
    );
    renderList();
    await waitFor(() => expect(screen.getByTestId('toast-error')).toBeInTheDocument());
  });
});

describe('FriendsListScreen — privacy (N11)', () => {
  it('does not render any "@" character in the list DOM', async () => {
    server.use(
      http.get('http://localhost/v1/friends', () =>
        HttpResponse.json(
          {
            items: [
              {
                user_id: 'a',
                name: 'Alice',
                currency: 'USD',
                since: '2026-01-01T00:00:00Z',
              },
            ],
            next_cursor: null,
          },
          { status: 200 },
        ),
      ),
    );
    const { container } = renderList();
    await waitFor(() => expect(screen.getByTestId('friends-list')).toBeInTheDocument());
    expect(container.textContent ?? '').not.toContain('@');
  });
});
