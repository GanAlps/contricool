import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { Toaster, useToasterStore } from '~/components/ui/Toaster';
import { useAuthStore } from '~/lib/auth-store';

import { server } from '../msw-handlers';

import { getRouterMock, mockExpoRouter, resetRouterMock } from './_router-mock';

mockExpoRouter();

const ForgotPasswordScreen = (await import('~/app/(auth)/forgot-password')).default;

function renderForgot() {
  return render(
    <>
      <ForgotPasswordScreen />
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

describe('ForgotPasswordScreen', () => {
  it('happy path: success toast + replaces /reset-password with email param', async () => {
    renderForgot();
    fireEvent.change(screen.getByTestId('forgot-email'), { target: { value: 'a@b.com' } });
    fireEvent.click(screen.getByTestId('forgot-submit'));
    await waitFor(() => {
      expect(getRouterMock().calls).toContainEqual({
        kind: 'replace',
        href: { pathname: '/reset-password', params: { email: 'a@b.com' } },
      });
    });
    expect(screen.getByTestId('toast-success')).toBeInTheDocument();
  });

  it('N9: RATE_LIMITED shows a toast and stays on the page', async () => {
    server.use(
      http.post('http://localhost/v1/auth/forgot-password', () =>
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
    renderForgot();
    fireEvent.change(screen.getByTestId('forgot-email'), { target: { value: 'a@b.com' } });
    fireEvent.click(screen.getByTestId('forgot-submit'));
    expect(await screen.findByTestId('toast-error')).toBeInTheDocument();
    expect(getRouterMock().calls).toEqual([]);
  });
});
