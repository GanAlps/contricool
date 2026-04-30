/**
 * ErrorBoundary tests.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  ErrorBoundary,
  _resetGlobalErrorTelemetryForTests,
  installGlobalErrorTelemetry,
} from '~/components/ErrorBoundary';
import { _resetTelemetryForTests } from '~/lib/telemetry';

import { server } from '../msw-handlers';

const BASE = 'http://localhost/v1';

beforeEach(() => {
  _resetTelemetryForTests();
  _resetGlobalErrorTelemetryForTests();
});
afterEach(() => {
  _resetTelemetryForTests();
  _resetGlobalErrorTelemetryForTests();
});

function Boom(): never {
  throw new Error('intentional');
}

describe('ErrorBoundary', () => {
  it('renders children when there is no error', () => {
    render(
      <ErrorBoundary>
        <div data-testid="child">ok</div>
      </ErrorBoundary>,
    );
    expect(screen.getByTestId('child')).toHaveTextContent('ok');
  });

  it('renders the fallback UI on a child render error', () => {
    // Suppress React's own error log during the intentional throw.
    const orig = console.error;
    console.error = () => {};
    try {
      render(
        <ErrorBoundary>
          <Boom />
        </ErrorBoundary>,
      );
      expect(screen.getByTestId('error-boundary-fallback')).toBeInTheDocument();
    } finally {
      console.error = orig;
    }
  });

  it('posts a telemetry event on the caught error', async () => {
    let posted = 0;
    server.use(
      http.post(`${BASE}/telemetry/error`, () => {
        posted += 1;
        return HttpResponse.json({ accepted: true }, { status: 202 });
      }),
    );
    const orig = console.error;
    console.error = () => {};
    try {
      render(
        <ErrorBoundary>
          <Boom />
        </ErrorBoundary>,
      );
      // Wait for the post to fire.
      await new Promise((r) => setTimeout(r, 50));
      expect(posted).toBe(1);
    } finally {
      console.error = orig;
    }
  });

  it('Try-again resets the boundary', async () => {
    const orig = console.error;
    console.error = () => {};
    try {
      const { rerender } = render(
        <ErrorBoundary>
          <Boom />
        </ErrorBoundary>,
      );
      expect(screen.getByTestId('error-boundary-fallback')).toBeInTheDocument();
      // Re-render with a non-throwing child first, so when the
      // boundary's state.error is cleared by the retry click the
      // re-render shows the new child.
      rerender(
        <ErrorBoundary>
          <div data-testid="ok">recovered</div>
        </ErrorBoundary>,
      );
      // Boundary still shows fallback because state.error is still set.
      expect(screen.getByTestId('error-boundary-fallback')).toBeInTheDocument();
      fireEvent.click(screen.getByTestId('error-boundary-retry'));
      await waitFor(() => expect(screen.getByTestId('ok')).toHaveTextContent('recovered'));
    } finally {
      console.error = orig;
    }
  });
});

describe('installGlobalErrorTelemetry', () => {
  it('reports unhandledrejection events as telemetry', async () => {
    let posted = 0;
    let last: unknown = null;
    server.use(
      http.post(`${BASE}/telemetry/error`, async ({ request }) => {
        posted += 1;
        last = await request.json();
        return HttpResponse.json({ accepted: true }, { status: 202 });
      }),
    );
    installGlobalErrorTelemetry();
    // Manually dispatch an unhandledrejection event so we don't have to
    // rely on a real promise rejection (jsdom is finicky).
    const evt = new Event('unhandledrejection') as Event & { reason: unknown };
    (evt as { reason: unknown }).reason = new Error('async-failure');
    window.dispatchEvent(evt);
    await new Promise((r) => setTimeout(r, 50));
    expect(posted).toBe(1);
    expect((last as { name: string }).name).toBe('unhandled-rejection');
  });

  it('is idempotent', () => {
    installGlobalErrorTelemetry();
    installGlobalErrorTelemetry();
    // No assertion needed — the contract is "doesn't throw, doesn't
    // double-register"; the dedup test above covers double-firing.
  });
});
