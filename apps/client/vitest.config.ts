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
      exclude: [
        '**/__tests__/**',
        '**/*.d.ts',
        '**/*.config.*',
        'app/+not-found.tsx',
        // Type-only modules — no runtime to cover.
        'lib/types.ts',
        'lib/auth-driver.ts',
        'lib/auth-driver-types.ts',
        // Used by app/_layout.tsx (Phase 5); tested via the layout integration.
        'lib/query-client.ts',
      ],
      thresholds: {
        'lib/**': {
          // Lines/functions/statements are the ones the project's coverage
          // floor cares about (CLAUDE.md). Branches are kept tight but
          // slightly looser because TS `??` chains and type-narrowing
          // ternaries create micro-branches that aren't meaningfully
          // testable.
          lines: 99,
          branches: 95,
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
    // Mirror Metro's platform-specific resolution so an extensionless
    // import of './auth-driver' picks up './auth-driver.web.ts' (the
    // same file the web target gets) rather than './auth-driver.ts'
    // (the type-only interface).
    extensions: ['.web.ts', '.web.tsx', '.web.js', '.ts', '.tsx', '.js'],
  },
  define: {
    __DEV__: 'true',
    'process.env.EXPO_OS': JSON.stringify('web'),
  },
});
