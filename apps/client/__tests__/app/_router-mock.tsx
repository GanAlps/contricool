/**
 * Shared expo-router mock for screen tests.
 *
 *   import { mockExpoRouter, getRouterMock } from './_router-mock';
 *
 * Call `mockExpoRouter()` at the top of each screen test file (before
 * the component under test imports expo-router) and use
 * `getRouterMock()` to assert navigations.
 */

import type { ReactNode } from 'react';
import { vi } from 'vitest';

export type RouterCall =
  | { kind: 'replace'; href: unknown }
  | { kind: 'push'; href: unknown }
  | { kind: 'back' };

const state: {
  calls: RouterCall[];
  params: Record<string, string | undefined>;
} = {
  calls: [],
  params: {},
};

export function getRouterMock(): typeof state {
  return state;
}

export function setSearchParams(params: Record<string, string | undefined>): void {
  state.params = params;
}

export function resetRouterMock(): void {
  state.calls = [];
  state.params = {};
}

export function mockExpoRouter(): void {
  vi.mock('expo-router', () => {
    const router = {
      replace: (href: unknown) => state.calls.push({ kind: 'replace', href }),
      push: (href: unknown) => state.calls.push({ kind: 'push', href }),
      back: () => state.calls.push({ kind: 'back' }),
      navigate: (href: unknown) => state.calls.push({ kind: 'push', href }),
      canGoBack: () => false,
      setParams: () => {},
    };

    type LinkProps = {
      href: unknown;
      children?: ReactNode;
      testID?: string;
      className?: string;
    };
    const Link = ({ href, children, testID, className }: LinkProps) => {
      const target = typeof href === 'string' ? href : JSON.stringify(href);
      return (
        <a
          href={target}
          data-testid={testID}
          className={className}
          onClick={(e) => {
            e.preventDefault();
            state.calls.push({ kind: 'push', href });
          }}
        >
          {children}
        </a>
      );
    };

    const Redirect = ({ href }: { href: unknown }) => {
      state.calls.push({ kind: 'replace', href });
      return null;
    };

    const Stack = ({ children }: { children?: ReactNode }) => <>{children}</>;
    const Tabs = ({ children }: { children?: ReactNode }) => <>{children}</>;

    return {
      useRouter: () => router,
      useLocalSearchParams: () => state.params,
      useSegments: () => [],
      usePathname: () => '/',
      useNavigation: () => ({ goBack: () => state.calls.push({ kind: 'back' }) }),
      Link,
      Redirect,
      Stack,
      Tabs,
    };
  });
}
