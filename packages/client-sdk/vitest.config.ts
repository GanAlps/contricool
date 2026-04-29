import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/__tests__/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      include: ['src/**'],
      exclude: ['src/__tests__/**', 'src/schema.d.ts', '**/*.d.ts'],
      thresholds: {
        'src/**': {
          lines: 99,
          branches: 95,
          functions: 99,
          statements: 99,
        },
      },
    },
  },
});
