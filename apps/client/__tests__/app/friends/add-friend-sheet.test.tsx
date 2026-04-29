/**
 * AddFriendSheet — N1–N8 negatives + happy path.
 *
 * The sheet is rendered through the parent FriendsListScreen so it
 * reuses the same MSW + provider wiring as the list tests.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { Toaster, useToasterStore } from '~/components/ui/Toaster';
import { useAuthStore } from '~/lib/auth-store';

import { server } from '../../msw-handlers';
import { withProviders } from '../../test-utils';
import { mockExpoRouter, resetRouterMock } from '../_router-mock';

mockExpoRouter();

const FriendsListScreen = (await import('~/app/(app)/friends/index')).default;

function renderScreen() {
  return render(
    withProviders(
      <>
        <FriendsListScreen />
        <Toaster />
      </>,
    ),
  );
}

async function openSheet(): Promise<void> {
  await waitFor(() => expect(screen.getByTestId('friends-empty')).toBeInTheDocument());
  fireEvent.click(screen.getByTestId('friends-add-cta'));
  await waitFor(() => expect(screen.getByTestId('add-friend-sheet')).toBeInTheDocument());
}

function fillEmail(value: string): void {
  fireEvent.change(screen.getByTestId('add-friend-email'), { target: { value } });
}

function submit(): void {
  fireEvent.click(screen.getByTestId('add-friend-submit'));
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
  // Default the list to empty so the empty CTA is reachable.
  server.use(
    http.get('http://localhost/v1/friends', () =>
      HttpResponse.json({ items: [], next_cursor: null }, { status: 200 }),
    ),
  );
});
afterEach(() => {
  useAuthStore.getState()._clear();
  useToasterStore.getState().clear();
});

describe('AddFriendSheet — happy path', () => {
  it('on success: closes, toasts, and invalidates the list cache', async () => {
    server.use(
      http.post('http://localhost/v1/friends/add', () =>
        HttpResponse.json(
          {
            user_id: 'new',
            name: 'Alice',
            currency: 'USD',
            since: '2026-04-29T00:00:00Z',
          },
          { status: 200 },
        ),
      ),
    );
    renderScreen();
    await openSheet();
    fillEmail('alice@example.com');
    submit();
    await waitFor(() => expect(screen.queryByTestId('add-friend-sheet')).not.toBeInTheDocument());
    expect(screen.getByTestId('toast-success')).toHaveTextContent('Added Alice');
  });
});

describe('AddFriendSheet — negatives', () => {
  it('N3: empty input renders client-side Zod error and does not call the API', async () => {
    let calls = 0;
    server.use(
      http.post('http://localhost/v1/friends/add', () => {
        calls += 1;
        return HttpResponse.json(
          { error: { code: 'VALIDATION_ERROR', message: 'x', request_id: 'r' } },
          { status: 422 },
        );
      }),
    );
    renderScreen();
    await openSheet();
    submit();
    await waitFor(() =>
      expect(screen.getByTestId('add-friend-error')).toHaveTextContent('Required'),
    );
    expect(calls).toBe(0);
  });

  it('N1: phone-shape → INVALID_IDENTIFIER → "email-only" copy', async () => {
    server.use(
      http.post('http://localhost/v1/friends/add', () =>
        HttpResponse.json(
          {
            error: {
              code: 'INVALID_IDENTIFIER',
              message: 'phones not supported',
              request_id: 'r',
            },
          },
          { status: 400 },
        ),
      ),
    );
    renderScreen();
    await openSheet();
    fillEmail('+14155552671');
    submit();
    await waitFor(() =>
      expect(screen.getByTestId('add-friend-error')).toHaveTextContent(/email only/i),
    );
  });

  it('N2: malformed email → 422 → field error from details[0].issue', async () => {
    server.use(
      http.post('http://localhost/v1/friends/add', () =>
        HttpResponse.json(
          {
            error: {
              code: 'VALIDATION_ERROR',
              message: 'invalid',
              request_id: 'r',
              details: [{ field: 'email', issue: 'Enter a valid email address.' }],
            },
          },
          { status: 422 },
        ),
      ),
    );
    renderScreen();
    await openSheet();
    fillEmail('not-an-email');
    submit();
    await waitFor(() =>
      expect(screen.getByTestId('add-friend-error')).toHaveTextContent(
        'Enter a valid email address.',
      ),
    );
  });

  it('N4: USER_NOT_FOUND → "couldn\'t find" copy', async () => {
    server.use(
      http.post('http://localhost/v1/friends/add', () =>
        HttpResponse.json(
          { error: { code: 'USER_NOT_FOUND', message: 'no', request_id: 'r' } },
          { status: 404 },
        ),
      ),
    );
    renderScreen();
    await openSheet();
    fillEmail('ghost@example.com');
    submit();
    await waitFor(() =>
      expect(screen.getByTestId('add-friend-error')).toHaveTextContent(/couldn't find/i),
    );
  });

  it('N5: CONFLICT → "already friends" copy', async () => {
    server.use(
      http.post('http://localhost/v1/friends/add', () =>
        HttpResponse.json(
          { error: { code: 'CONFLICT', message: 'dup', request_id: 'r' } },
          { status: 409 },
        ),
      ),
    );
    renderScreen();
    await openSheet();
    fillEmail('alice@example.com');
    submit();
    await waitFor(() =>
      expect(screen.getByTestId('add-friend-error')).toHaveTextContent(/already friends/i),
    );
  });

  it('N6: SELF_ADD_FORBIDDEN → "can\'t add yourself" copy', async () => {
    server.use(
      http.post('http://localhost/v1/friends/add', () =>
        HttpResponse.json(
          {
            error: {
              code: 'SELF_ADD_FORBIDDEN',
              message: 'self',
              request_id: 'r',
            },
          },
          { status: 422 },
        ),
      ),
    );
    renderScreen();
    await openSheet();
    fillEmail('me@example.com');
    submit();
    await waitFor(() =>
      expect(screen.getByTestId('add-friend-error')).toHaveTextContent(/yourself/i),
    );
  });

  it('N7: RATE_LIMITED → toast with retry-after, sheet stays open', async () => {
    server.use(
      http.post('http://localhost/v1/friends/add', () =>
        HttpResponse.json(
          {
            error: {
              code: 'RATE_LIMITED',
              message: 'slow down',
              request_id: 'r',
              retry_after: 30,
            },
          },
          { status: 429 },
        ),
      ),
    );
    renderScreen();
    await openSheet();
    fillEmail('alice@example.com');
    submit();
    await waitFor(() => expect(screen.getByTestId('toast-error')).toHaveTextContent(/30 seconds/));
    expect(screen.getByTestId('add-friend-sheet')).toBeInTheDocument();
  });

  it('N8: 5xx → generic toast, modal stays open with form preserved', async () => {
    server.use(
      http.post('http://localhost/v1/friends/add', () =>
        HttpResponse.json(
          { error: { code: 'INTERNAL_ERROR', message: 'boom', request_id: 'r' } },
          { status: 500 },
        ),
      ),
    );
    renderScreen();
    await openSheet();
    fillEmail('alice@example.com');
    submit();
    await waitFor(() => expect(screen.getByTestId('toast-error')).toBeInTheDocument());
    expect(screen.getByTestId('add-friend-sheet')).toBeInTheDocument();
    expect(screen.getByTestId('add-friend-email')).toHaveValue('alice@example.com');
  });
});
