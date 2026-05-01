/**
 * QaTools is gated on Platform.OS !== 'web' AND
 * EXPO_PUBLIC_ENV !== 'production'. Vitest runs in jsdom under
 * EXPO_OS='web' (defined in vitest.config.ts), so the component
 * normally returns null. To exercise both branches we mock
 * react-native's Platform export per test.
 *
 * The button onPress handlers are smoke-only — they call into
 * `reportError` (which is mocked here so we can assert without
 * actually hitting Sentry) or throw synchronously. We don't assert
 * on the Sentry round-trip because the underlying telemetry tests
 * already cover that path; we just lock the surface contract.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const reportErrorSpy = vi.hoisted(() => vi.fn());

vi.mock('~/lib/telemetry', () => ({
  reportError: reportErrorSpy,
  reportMetric: vi.fn(),
}));

const platformMock = vi.hoisted(() => ({ OS: 'web' as 'web' | 'ios' | 'android' }));
vi.mock('react-native', async () => {
  const actual = await vi.importActual<typeof import('react-native')>('react-native');
  return {
    ...actual,
    get Platform() {
      return new Proxy(actual.Platform, {
        get(target, key) {
          if (key === 'OS') {
            return platformMock.OS;
          }
          return Reflect.get(target, key);
        },
      });
    },
  };
});

const SAVED_ENV = { ...process.env };

beforeEach(() => {
  reportErrorSpy.mockClear();
  platformMock.OS = 'web';
  // biome-ignore lint/performance/noDelete: tests need to clear, not stringify
  delete process.env.EXPO_PUBLIC_ENV;
});
afterEach(() => {
  process.env = { ...SAVED_ENV };
});

describe('QaTools', () => {
  it('renders nothing on web (the web bundle should not surface debug crash buttons)', async () => {
    platformMock.OS = 'web';
    // Reset modules so the env-var snapshot from a previous test
    // (e.g. one that set EXPO_PUBLIC_ENV=production) cannot make this
    // test pass for the wrong reason — without the reset, the
    // module-evaluation cache could yield `null` due to the env-var
    // guard rather than the Platform.OS === 'web' guard we're
    // actually verifying here.
    vi.resetModules();
    const { QaTools } = await import('~/components/dev/QaTools');
    render(<QaTools />);
    expect(screen.queryByTestId('qa-tools')).toBeNull();
  });

  it('renders nothing on native production builds (debug buttons must not ship to real users)', async () => {
    platformMock.OS = 'android';
    process.env.EXPO_PUBLIC_ENV = 'production';
    vi.resetModules();
    const { QaTools } = await import('~/components/dev/QaTools');
    render(<QaTools />);
    expect(screen.queryByTestId('qa-tools')).toBeNull();
  });

  it('renders the QA card on native dev builds (no env var)', async () => {
    platformMock.OS = 'android';
    vi.resetModules();
    const { QaTools } = await import('~/components/dev/QaTools');
    render(<QaTools />);
    expect(screen.getByTestId('qa-tools')).toBeTruthy();
    expect(screen.getByTestId('qa-tools-throw-js')).toBeTruthy();
    expect(screen.getByTestId('qa-tools-fetch-fail')).toBeTruthy();
  });

  it('renders the QA card on native preview builds (EXPO_PUBLIC_ENV=preview)', async () => {
    platformMock.OS = 'android';
    process.env.EXPO_PUBLIC_ENV = 'preview';
    vi.resetModules();
    const { QaTools } = await import('~/components/dev/QaTools');
    render(<QaTools />);
    expect(screen.getByTestId('qa-tools')).toBeTruthy();
  });

  it('Trigger JS error button calls reportError with a stable name', async () => {
    platformMock.OS = 'ios';
    vi.resetModules();
    const { QaTools } = await import('~/components/dev/QaTools');
    render(<QaTools />);
    fireEvent.click(screen.getByTestId('qa-tools-throw-js'));
    expect(reportErrorSpy).toHaveBeenCalledTimes(1);
    const [name, err] = reportErrorSpy.mock.calls[0]!;
    expect(name).toBe('qa-tools-deliberate-js-error');
    expect(err).toBeInstanceOf(Error);
    expect((err as Error).message).toBe('QA: deliberate JS error');
  });

  it('Trigger fetch error button reports the network failure (does not throw)', async () => {
    platformMock.OS = 'ios';
    vi.resetModules();
    const { QaTools } = await import('~/components/dev/QaTools');
    render(<QaTools />);
    // The runtime fetch goes to a `.invalid` host (RFC 6761 — always
    // NXDOMAIN). On-device that's a real network rejection; in jsdom
    // / Node the fetch also rejects (no DNS resolution). `waitFor`
    // polls until the catch handler has reported, replacing the
    // brittle fixed-timeout we had before.
    fireEvent.click(screen.getByTestId('qa-tools-fetch-fail'));
    await waitFor(() => {
      expect(reportErrorSpy).toHaveBeenCalledTimes(1);
    });
    expect(reportErrorSpy.mock.calls[0]?.[0]).toBe('qa-tools-deliberate-fetch-error');
  });
});
