import path from 'node:path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./test-setup.ts'],
    include: ['__tests__/**/*.test.{ts,tsx}'],
    passWithNoTests: true,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      include: ['lib/**', 'app/**', 'components/**'],
      exclude: ['**/__tests__/**', '**/*.d.ts', '**/*.config.*', 'app/+not-found.tsx'],
      thresholds: {
        'lib/**': {
          lines: 99,
          branches: 99,
          functions: 99,
          statements: 99,
        },
        'app/**': {
          lines: 80,
          branches: 70,
          functions: 80,
          statements: 80,
        },
        'components/**': {
          lines: 80,
          branches: 70,
          functions: 80,
          statements: 80,
        },
      },
    },
  },
  resolve: {
    alias: {
      '~': path.resolve(__dirname, '.'),
      'react-native': 'react-native-web',
    },
  },
  define: {
    __DEV__: 'true',
    'process.env.EXPO_OS': JSON.stringify('web'),
  },
});
