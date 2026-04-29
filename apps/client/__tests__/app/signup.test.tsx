import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { Toaster, useToasterStore } from '~/components/ui/Toaster';
import { useAuthStore } from '~/lib/auth-store';

import { server } from '../msw-handlers';

import { getRouterMock, mockExpoRouter, resetRouterMock } from './_router-mock';

mockExpoRouter();

const SignupScreen = (await import('~/app/(auth)/signup')).default;

function renderSignup() {
  return render(
    <>
      <SignupScreen />
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

function fill(values: Partial<Record<string, string>>): void {
  if (values.email !== undefined)
    fireEvent.change(screen.getByTestId('signup-email'), { target: { value: values.email } });
  if (values.name !== undefined)
    fireEvent.change(screen.getByTestId('signup-name'), { target: { value: values.name } });
  if (values.password !== undefined)
    fireEvent.change(screen.getByTestId('signup-password'), { target: { value: values.password } });
  if (values.confirm !== undefined)
    fireEvent.change(screen.getByTestId('signup-confirm-password'), {
      target: { value: values.confirm },
    });
  if (values.phone !== undefined)
    fireEvent.change(screen.getByTestId('signup-phone'), { target: { value: values.phone } });
  if (values.currency !== undefined)
    fireEvent.change(screen.getByTestId('signup-currency'), { target: { value: values.currency } });
}

describe('SignupScreen', () => {
  it('happy path: signs up and replaces /verify-email with email param', async () => {
    renderSignup();
    fill({
      email: 'a@b.com',
      name: 'Alice',
      password: 'P@ssword123!',
      confirm: 'P@ssword123!',
      currency: 'USD',
    });
    fireEvent.click(screen.getByTestId('signup-submit'));
    await waitFor(() => {
      expect(getRouterMock().calls).toContainEqual({
        kind: 'replace',
        href: { pathname: '/verify-email', params: { email: 'a@b.com' } },
      });
    });
  });

  it('N4: confirm mismatch is caught client-side before any network call', async () => {
    let networkCalls = 0;
    server.use(
      http.post('http://localhost/v1/auth/signup', () => {
        networkCalls++;
        return HttpResponse.json({ user_id: 'x', status: 'PENDING_VERIFICATION' }, { status: 202 });
      }),
    );
    renderSignup();
    fill({
      email: 'a@b.com',
      name: 'Alice',
      password: 'P@ssword123!',
      confirm: 'different!',
      currency: 'USD',
    });
    fireEvent.click(screen.getByTestId('signup-submit'));
    expect(await screen.findByTestId('confirm_password-error')).toBeInTheDocument();
    expect(networkCalls).toBe(0);
  });

  it('N5: EMAIL_EXISTS shows banner with login link', async () => {
    server.use(
      http.post('http://localhost/v1/auth/signup', () =>
        HttpResponse.json(
          { error: { code: 'EMAIL_EXISTS', message: 'taken', request_id: 'r' } },
          { status: 409 },
        ),
      ),
    );
    renderSignup();
    fill({
      email: 'taken@b.com',
      name: 'Alice',
      password: 'P@ssword123!',
      confirm: 'P@ssword123!',
      currency: 'USD',
    });
    fireEvent.click(screen.getByTestId('signup-submit'));
    const banner = await screen.findByTestId('signup-banner');
    expect(banner).toHaveTextContent('An account with this email already exists.');
    expect(screen.getByTestId('signup-login-link')).toBeInTheDocument();
  });

  it('N6: INVALID_PASSWORD with details maps onto the password field', async () => {
    server.use(
      http.post('http://localhost/v1/auth/signup', () =>
        HttpResponse.json(
          {
            error: {
              code: 'INVALID_PASSWORD',
              message: 'weak',
              request_id: 'r',
              details: [{ field: 'password', issue: 'Add a symbol' }],
            },
          },
          { status: 422 },
        ),
      ),
    );
    renderSignup();
    fill({
      email: 'a@b.com',
      name: 'Alice',
      password: 'simplepass',
      confirm: 'simplepass',
      currency: 'USD',
    });
    fireEvent.click(screen.getByTestId('signup-submit'));
    expect(await screen.findByTestId('password-error')).toHaveTextContent('Add a symbol');
  });

  it('5xx surfaces a generic toast', async () => {
    server.use(
      http.post('http://localhost/v1/auth/signup', () =>
        HttpResponse.json(
          { error: { code: 'INTERNAL', message: 'oops', request_id: 'r' } },
          { status: 500 },
        ),
      ),
    );
    renderSignup();
    fill({
      email: 'a@b.com',
      name: 'Alice',
      password: 'P@ssword123!',
      confirm: 'P@ssword123!',
      currency: 'USD',
    });
    fireEvent.click(screen.getByTestId('signup-submit'));
    expect(await screen.findByTestId('toast-error')).toBeInTheDocument();
  });

  it('omits empty phone from the payload', async () => {
    let received: { phone?: string } = {};
    server.use(
      http.post('http://localhost/v1/auth/signup', async ({ request }) => {
        received = (await request.json()) as { phone?: string };
        return HttpResponse.json({ user_id: 'x', status: 'PENDING_VERIFICATION' }, { status: 202 });
      }),
    );
    renderSignup();
    fill({
      email: 'a@b.com',
      name: 'Alice',
      password: 'P@ssword123!',
      confirm: 'P@ssword123!',
      currency: 'USD',
    });
    fireEvent.click(screen.getByTestId('signup-submit'));
    await waitFor(() => expect(getRouterMock().calls.length).toBeGreaterThan(0));
    expect(received.phone).toBeUndefined();
  });
});
