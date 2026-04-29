import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react-native';
import { afterAll, afterEach, beforeAll, vi } from 'vitest';

process.env.EXPO_PUBLIC_API_BASE_URL = '/v1';

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
