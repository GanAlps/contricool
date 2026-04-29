import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { Toaster, useToasterStore } from '~/components/ui/Toaster';
import { useAuthStore } from '~/lib/auth-store';

import { server } from '../msw-handlers';

import { getRouterMock, mockExpoRouter, resetRouterMock } from './_router-mock';

mockExpoRouter();

const LoginScreen = (await import('~/app/(auth)/login')).default;

function renderLogin() {
  return render(
    <>
      <LoginScreen />
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

async function fillAndSubmit(email: string, password: string): Promise<void> {
  fireEvent.change(screen.getByTestId('login-email'), { target: { value: email } });
  fireEvent.change(screen.getByTestId('login-password'), { target: { value: password } });
  fireEvent.click(screen.getByTestId('login-submit'));
}

describe('LoginScreen', () => {
  it('happy path: signs in and replaces /dashboard', async () => {
    renderLogin();
    await fillAndSubmit('a@b.com', 'P@ssword123!');
    await waitFor(() => {
      expect(getRouterMock().calls).toContainEqual({ kind: 'replace', href: '/dashboard' });
    });
    expect(useAuthStore.getState().accessToken).toBe('access-jwt');
  });

  it('N1: wrong password → banner with INVALID_CREDENTIALS friendly copy', async () => {
    server.use(
      http.post('/v1/auth/login', () =>
        HttpResponse.json(
          { error: { code: 'INVALID_CREDENTIALS', message: 'nope', request_id: 'r' } },
          { status: 401 },
        ),
      ),
    );
    renderLogin();
    await fillAndSubmit('a@b.com', 'wrong');
    const banner = await screen.findByTestId('login-banner');
    expect(banner).toHaveTextContent('Email or password is incorrect.');
  });

  it('N2: ACCOUNT_NOT_ACTIVE shows banner with verify-email link', async () => {
    server.use(
      http.post('/v1/auth/login', () =>
        HttpResponse.json(
          { error: { code: 'ACCOUNT_NOT_ACTIVE', message: 'pending', request_id: 'r' } },
          { status: 403 },
        ),
      ),
    );
    renderLogin();
    await fillAndSubmit('pending@b.com', 'P@ssword123!');
    const banner = await screen.findByTestId('login-banner');
    expect(banner).toHaveTextContent('Please verify your email first.');
    const link = screen.getByTestId('login-verify-link');
    expect(link).toBeInTheDocument();
    fireEvent.click(link);
    expect(getRouterMock().calls).toContainEqual({
      kind: 'push',
      href: { pathname: '/verify-email', params: { email: 'pending@b.com' } },
    });
  });

  it('N3: RATE_LIMITED shows a toast', async () => {
    server.use(
      http.post('/v1/auth/login', () =>
        HttpResponse.json(
          {
            error: {
              code: 'RATE_LIMITED',
              message: 'slow',
              request_id: 'r',
              retry_after: 60,
            },
          },
          { status: 429 },
        ),
      ),
    );
    renderLogin();
    await fillAndSubmit('a@b.com', 'P@ssword123!');
    expect(await screen.findByTestId('toast-error')).toBeInTheDocument();
  });

  it('client-side Zod rejects invalid email before submit', async () => {
    renderLogin();
    fireEvent.change(screen.getByTestId('login-email'), { target: { value: 'not-an-email' } });
    fireEvent.change(screen.getByTestId('login-password'), { target: { value: 'pw' } });
    fireEvent.click(screen.getByTestId('login-submit'));
    expect(await screen.findByTestId('email-error')).toBeInTheDocument();
    expect(getRouterMock().calls).toEqual([]);
  });
});
