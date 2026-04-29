import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Toaster, useToasterStore } from '~/components/ui/Toaster';
import { useAuthStore } from '~/lib/auth-store';

import { server } from '../msw-handlers';

import { getRouterMock, mockExpoRouter, resetRouterMock, setSearchParams } from './_router-mock';

mockExpoRouter();

const VerifyEmailScreen = (await import('~/app/(auth)/verify-email')).default;

function renderVerify() {
  return render(
    <>
      <VerifyEmailScreen />
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

describe('VerifyEmailScreen', () => {
  it('prefills email from query and routes to /login on success', async () => {
    setSearchParams({ email: 'a@b.com' });
    renderVerify();
    expect((screen.getByTestId('verify-email') as HTMLInputElement).value).toBe('a@b.com');
    fireEvent.change(screen.getByTestId('verify-code'), { target: { value: '123456' } });
    fireEvent.click(screen.getByTestId('verify-submit'));
    await waitFor(() =>
      expect(getRouterMock().calls).toContainEqual({ kind: 'replace', href: '/login' }),
    );
  });

  it('N7: INVALID_CODE shows banner', async () => {
    setSearchParams({ email: 'a@b.com' });
    server.use(
      http.post('http://localhost/v1/auth/verify-email', () =>
        HttpResponse.json(
          { error: { code: 'INVALID_CODE', message: 'wrong', request_id: 'r' } },
          { status: 401 },
        ),
      ),
    );
    renderVerify();
    fireEvent.change(screen.getByTestId('verify-code'), { target: { value: '999999' } });
    fireEvent.click(screen.getByTestId('verify-submit'));
    expect(await screen.findByTestId('verify-banner')).toHaveTextContent(
      'Code is wrong or expired',
    );
  });

  it('N8: USER_NOT_FOUND shows the configured friendly banner', async () => {
    setSearchParams({ email: 'ghost@b.com' });
    server.use(
      http.post('http://localhost/v1/auth/verify-email', () =>
        HttpResponse.json(
          { error: { code: 'USER_NOT_FOUND', message: 'nope', request_id: 'r' } },
          { status: 404 },
        ),
      ),
    );
    renderVerify();
    fireEvent.change(screen.getByTestId('verify-code'), { target: { value: '123456' } });
    fireEvent.click(screen.getByTestId('verify-submit'));
    expect(await screen.findByTestId('verify-banner')).toHaveTextContent("can't find that account");
  });

  it('Resend button calls resendEmailCode and disables for 30s', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      setSearchParams({ email: 'a@b.com' });
      renderVerify();
      const resend = screen.getByTestId('verify-resend');
      fireEvent.click(resend);
      await waitFor(() =>
        expect(screen.getByTestId('verify-resend')).toHaveAttribute('aria-disabled', 'true'),
      );
      await waitFor(() => expect(screen.getByTestId('toast-success')).toBeInTheDocument());
      vi.advanceTimersByTime(31_000);
      await waitFor(() =>
        expect(screen.getByTestId('verify-resend').textContent).toContain('Resend code'),
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it('Resend rate-limited surfaces a toast', async () => {
    setSearchParams({ email: 'a@b.com' });
    server.use(
      http.post('http://localhost/v1/auth/resend-email-code', () =>
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
    renderVerify();
    fireEvent.click(screen.getByTestId('verify-resend'));
    expect(await screen.findByTestId('toast-error')).toBeInTheDocument();
  });
});
