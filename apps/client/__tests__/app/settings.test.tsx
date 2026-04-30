/**
 * Phase 7 — SettingsScreen tests.
 *
 * Covers:
 * - profile rendering
 * - export happy path (web download)
 * - export rate-limit toast
 * - delete confirm flow + sign-out + redirect
 * - delete cancel
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Toaster, useToasterStore } from '~/components/ui/Toaster';
import { useAuthStore } from '~/lib/auth-store';

import { server } from '../msw-handlers';

import { getRouterMock, mockExpoRouter, resetRouterMock } from './_router-mock';

mockExpoRouter();

const SettingsScreen = (await import('~/app/(app)/settings')).default;

const BASE = 'http://localhost/v1';

function renderSettings() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return render(
    <Wrapper>
      <SettingsScreen />
      <Toaster />
    </Wrapper>,
  );
}

beforeEach(() => {
  resetRouterMock();
  useAuthStore.setState({
    user: { user_id: '01J0000000000000000000ALI', name: 'Alice', currency: 'USD' },
    accessToken: 'access-jwt',
    idToken: 'id-jwt',
    loading: false,
  } as never);
  useToasterStore.getState().clear();
});

afterEach(() => {
  useAuthStore.getState()._clear();
  useToasterStore.getState().clear();
});

describe('SettingsScreen — profile', () => {
  it('shows the user name and currency', () => {
    renderSettings();
    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.getByText(/Default currency: USD/)).toBeInTheDocument();
  });

  it('falls back to em-dash when name is missing', () => {
    useAuthStore.setState({
      user: { user_id: 'u', name: undefined as unknown as string, currency: 'USD' },
      accessToken: 't',
      idToken: 'i',
      loading: false,
    } as never);
    renderSettings();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });
});

describe('SettingsScreen — edit name', () => {
  it('saves the new name and patches the auth store', async () => {
    server.use(
      http.patch(`${BASE}/me/profile`, async ({ request }) => {
        const body = (await request.json()) as { name: string };
        return HttpResponse.json(
          { user_id: '01J0000000000000000000ALI', name: body.name, currency: 'USD' },
          { status: 200 },
        );
      }),
    );
    renderSettings();
    fireEvent.click(screen.getByTestId('settings-name-edit'));
    fireEvent.change(screen.getByTestId('settings-name-input'), {
      target: { value: 'Alicia' },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('settings-name-save'));
    });
    await waitFor(() => {
      expect(useAuthStore.getState().user?.name).toBe('Alicia');
    });
    expect(useToasterStore.getState().toasts.some((t) => t.kind === 'success')).toBe(true);
  });

  it('shows an error toast when the server rejects the new name', async () => {
    server.use(
      http.patch(`${BASE}/me/profile`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'VALIDATION_ERROR',
              message: 'name must not be blank.',
              request_id: 'r',
              details: [{ field: 'name', issue: 'must not be blank' }],
            },
          },
          { status: 422 },
        ),
      ),
    );
    renderSettings();
    fireEvent.click(screen.getByTestId('settings-name-edit'));
    fireEvent.change(screen.getByTestId('settings-name-input'), {
      target: { value: 'X' },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('settings-name-save'));
    });
    await waitFor(() => {
      expect(useToasterStore.getState().toasts.some((t) => t.kind === 'error')).toBe(true);
    });
  });

  it('skips the network call when the name is unchanged', async () => {
    let called = false;
    server.use(
      http.patch(`${BASE}/me/profile`, () => {
        called = true;
        return HttpResponse.json(
          { user_id: '01J0000000000000000000ALI', name: 'Alice', currency: 'USD' },
          { status: 200 },
        );
      }),
    );
    renderSettings();
    fireEvent.click(screen.getByTestId('settings-name-edit'));
    // draftName starts as user.name, no change made.
    await act(async () => {
      fireEvent.click(screen.getByTestId('settings-name-save'));
    });
    expect(called).toBe(false);
  });

  it('blocks empty name with a toast and no network call', async () => {
    let called = false;
    server.use(
      http.patch(`${BASE}/me/profile`, () => {
        called = true;
        return HttpResponse.json(
          { user_id: '01J0000000000000000000ALI', name: '', currency: 'USD' },
          { status: 200 },
        );
      }),
    );
    renderSettings();
    fireEvent.click(screen.getByTestId('settings-name-edit'));
    fireEvent.change(screen.getByTestId('settings-name-input'), {
      target: { value: '   ' },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('settings-name-save'));
    });
    expect(called).toBe(false);
    expect(useToasterStore.getState().toasts.some((t) => t.kind === 'error')).toBe(true);
  });

  it('cancel restores the original name and exits edit mode', async () => {
    renderSettings();
    fireEvent.click(screen.getByTestId('settings-name-edit'));
    fireEvent.change(screen.getByTestId('settings-name-input'), {
      target: { value: 'Bob' },
    });
    fireEvent.click(screen.getByTestId('settings-name-cancel'));
    await waitFor(() =>
      expect(screen.queryByTestId('settings-name-input')).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId('settings-name')).toHaveTextContent('Alice');
  });
});

describe('SettingsScreen — export', () => {
  it('downloads a JSON blob on success (web)', async () => {
    server.use(
      http.get(`${BASE}/me/export`, () =>
        HttpResponse.json(
          {
            profile: {
              user_id: '01J0000000000000000000ALI',
              name: 'Alice',
              currency: 'USD',
              status: 'active',
              created_at: '2026-04-29T20:00:00Z',
            },
            friendships: [],
            transactions: [],
            exported_at: '2026-04-29T20:00:00Z',
          },
          { status: 200 },
        ),
      ),
    );
    const createObjectURL = vi.fn(() => 'blob:fake');
    const revokeObjectURL = vi.fn();
    Object.defineProperty(global.URL, 'createObjectURL', {
      configurable: true,
      value: createObjectURL,
    });
    Object.defineProperty(global.URL, 'revokeObjectURL', {
      configurable: true,
      value: revokeObjectURL,
    });

    renderSettings();
    fireEvent.click(screen.getByTestId('settings-export'));
    await waitFor(() => expect(createObjectURL).toHaveBeenCalled());
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalled());
  });

  it('shows a rate-limit toast on 429', async () => {
    server.use(
      http.get(`${BASE}/me/export`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'RATE_LIMITED',
              message: 'Try again later',
              request_id: 'r',
              retry_after_seconds: 86400,
            },
          },
          { status: 429 },
        ),
      ),
    );
    renderSettings();
    fireEvent.click(screen.getByTestId('settings-export'));
    await waitFor(() => {
      expect(useToasterStore.getState().toasts.some((t) => t.kind === 'error')).toBe(true);
    });
  });

  it('shows a generic error toast on 500', async () => {
    server.use(
      http.get(`${BASE}/me/export`, () =>
        HttpResponse.json(
          { error: { code: 'INTERNAL', message: 'oops', request_id: 'r' } },
          { status: 500 },
        ),
      ),
    );
    renderSettings();
    fireEvent.click(screen.getByTestId('settings-export'));
    await waitFor(() => {
      expect(useToasterStore.getState().toasts.some((t) => t.kind === 'error')).toBe(true);
    });
  });
});

describe('SettingsScreen — delete account', () => {
  it('opens and cancels the confirm sheet', async () => {
    renderSettings();
    fireEvent.click(screen.getByTestId('settings-delete'));
    expect(screen.getByTestId('settings-delete-cancel')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('settings-delete-cancel'));
    await waitFor(() =>
      expect(screen.queryByTestId('settings-delete-cancel')).not.toBeInTheDocument(),
    );
  });

  it('confirm → DELETE /me → sign-out → /login redirect', async () => {
    server.use(http.delete(`${BASE}/me`, () => new HttpResponse(null, { status: 204 })));

    renderSettings();
    fireEvent.click(screen.getByTestId('settings-delete'));
    await act(async () => {
      fireEvent.click(screen.getByTestId('settings-delete-confirm-btn'));
    });

    await waitFor(() => {
      const calls = getRouterMock().calls;
      expect(calls.some((c) => c.kind === 'replace' && c.href === '/login')).toBe(true);
    });
  });

  it('shows error toast when DELETE /me fails', async () => {
    server.use(
      http.delete(`${BASE}/me`, () =>
        HttpResponse.json(
          { error: { code: 'INTERNAL', message: 'oops', request_id: 'r' } },
          { status: 500 },
        ),
      ),
    );

    renderSettings();
    fireEvent.click(screen.getByTestId('settings-delete'));
    await act(async () => {
      fireEvent.click(screen.getByTestId('settings-delete-confirm-btn'));
    });
    await waitFor(() => {
      expect(useToasterStore.getState().toasts.some((t) => t.kind === 'error')).toBe(true);
    });
  });
});
