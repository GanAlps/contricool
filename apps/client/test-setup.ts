import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, vi } from 'vitest';

// SafeAreaProvider lives in the root `app/_layout.tsx`, but tests mount
// inner layouts (e.g. `(app)/_layout.tsx`) directly without the root
// wrapper. Stub the package so `SafeAreaView` is a pass-through `View`
// and the hooks return zero insets — equivalent to what RN-Web defaults
// to in a desktop browser.
vi.mock('react-native-safe-area-context', async () => {
  const rn = await vi.importActual<typeof import('react-native')>('react-native');
  const passthrough = ({ children }: { children: React.ReactNode }) => children;
  return {
    SafeAreaProvider: passthrough,
    SafeAreaView: rn.View,
    SafeAreaInsetsContext: { Provider: passthrough, Consumer: passthrough },
    useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
    useSafeAreaFrame: () => ({ x: 0, y: 0, width: 0, height: 0 }),
    initialWindowMetrics: {
      insets: { top: 0, bottom: 0, left: 0, right: 0 },
      frame: { x: 0, y: 0, width: 0, height: 0 },
    },
  };
});

// openapi-fetch builds URLs via `new URL(baseUrl + path)` and rejects
// relative bases.  In jsdom the page origin is `http://localhost`, so
// pin the absolute equivalent of `/v1` here for tests.
process.env.EXPO_PUBLIC_API_BASE_URL = 'http://localhost/v1';

if (typeof window !== 'undefined' && !window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

let server: { listen: () => void; resetHandlers: () => void; close: () => void } | null = null;

beforeAll(async () => {
  const mod = await import('./__tests__/msw-handlers');
  if (mod.server) {
    server = mod.server;
    server.listen();
  }
});

afterEach(() => {
  cleanup();
  if (server) {
    server.resetHandlers();
  }
});

afterAll(() => {
  if (server) {
    server.close();
  }
});
