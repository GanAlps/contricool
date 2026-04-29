import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, vi } from 'vitest';

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
