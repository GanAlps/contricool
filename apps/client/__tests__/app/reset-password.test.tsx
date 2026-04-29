import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { Toaster, useToasterStore } from '~/components/ui/Toaster';
import { useAuthStore } from '~/lib/auth-store';

import { server } from '../msw-handlers';

import { getRouterMock, mockExpoRouter, resetRouterMock, setSearchParams } from './_router-mock';

mockExpoRouter();

const ResetPasswordScreen = (await import('~/app/(auth)/reset-password')).default;

function renderReset() {
  return render(
    <>
      <ResetPasswordScreen />
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

function fill(values: { email?: string; code?: string; pw?: string; confirm?: string }): void {
  if (values.email !== undefined)
    fireEvent.change(screen.getByTestId('reset-email'), { target: { value: values.email } });
  if (values.code !== undefined)
    fireEvent.change(screen.getByTestId('reset-code'), { target: { value: values.code } });
  if (values.pw !== undefined)
    fireEvent.change(screen.getByTestId('reset-new-password'), { target: { value: values.pw } });
  if (values.confirm !== undefined)
    fireEvent.change(screen.getByTestId('reset-confirm-password'), {
      target: { value: values.confirm },
    });
}

describe('ResetPasswordScreen', () => {
  it('happy path: prefills email, replaces /login on success', async () => {
    setSearchParams({ email: 'a@b.com' });
    renderReset();
    expect((screen.getByTestId('reset-email') as HTMLInputElement).value).toBe('a@b.com');
    fill({ code: '123456', pw: 'NewP@ssword123!', confirm: 'NewP@ssword123!' });
    fireEvent.click(screen.getByTestId('reset-submit'));
    await waitFor(() =>
      expect(getRouterMock().calls).toContainEqual({ kind: 'replace', href: '/login' }),
    );
    expect(screen.getByTestId('toast-success')).toBeInTheDocument();
  });

  it('N10: INVALID_CODE shows banner', async () => {
    setSearchParams({ email: 'a@b.com' });
    server.use(
      http.post('http://localhost/v1/auth/reset-password', () =>
        HttpResponse.json(
          { error: { code: 'INVALID_CODE', message: 'wrong', request_id: 'r' } },
          { status: 401 },
        ),
      ),
    );
    renderReset();
    fill({ code: '999999', pw: 'NewP@ssword123!', confirm: 'NewP@ssword123!' });
    fireEvent.click(screen.getByTestId('reset-submit'));
    expect(await screen.findByTestId('reset-banner')).toHaveTextContent(
      'Code is wrong or expired.',
    );
  });

  it('N11: INVALID_PASSWORD with details maps onto new_password field', async () => {
    setSearchParams({ email: 'a@b.com' });
    server.use(
      http.post('http://localhost/v1/auth/reset-password', () =>
        HttpResponse.json(
          {
            error: {
              code: 'INVALID_PASSWORD',
              message: 'weak',
              request_id: 'r',
              details: [{ field: 'new_password', issue: 'Must include a digit' }],
            },
          },
          { status: 422 },
        ),
      ),
    );
    renderReset();
    fill({ code: '123456', pw: 'lowercaseonly', confirm: 'lowercaseonly' });
    fireEvent.click(screen.getByTestId('reset-submit'));
    expect(await screen.findByTestId('new_password-error')).toHaveTextContent(
      'Must include a digit',
    );
  });

  it('N12: confirm mismatch is caught client-side', async () => {
    let networkCalls = 0;
    server.use(
      http.post('http://localhost/v1/auth/reset-password', () => {
        networkCalls++;
        return HttpResponse.json({ password_reset: true }, { status: 200 });
      }),
    );
    setSearchParams({ email: 'a@b.com' });
    renderReset();
    fill({ code: '123456', pw: 'NewP@ssword123!', confirm: 'different!' });
    fireEvent.click(screen.getByTestId('reset-submit'));
    expect(await screen.findByTestId('confirm_password-error')).toBeInTheDocument();
    expect(networkCalls).toBe(0);
  });

  it('5xx surfaces a generic toast', async () => {
    setSearchParams({ email: 'a@b.com' });
    server.use(
      http.post('http://localhost/v1/auth/reset-password', () =>
        HttpResponse.json(
          { error: { code: 'INTERNAL', message: 'oops', request_id: 'r' } },
          { status: 500 },
        ),
      ),
    );
    renderReset();
    fill({ code: '123456', pw: 'NewP@ssword123!', confirm: 'NewP@ssword123!' });
    fireEvent.click(screen.getByTestId('reset-submit'));
    expect(await screen.findByTestId('toast-error')).toBeInTheDocument();
  });
});
