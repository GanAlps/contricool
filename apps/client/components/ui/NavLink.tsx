import { Link, usePathname } from 'expo-router';
import type { ReactNode } from 'react';
import { Text } from 'react-native';

import { cn } from '~/lib/utils';

export type NavLinkProps = {
  to: string;
  children: ReactNode;
  testID?: string;
};

/**
 * Top-bar nav link.  Highlights when the current pathname matches
 * `to` exactly OR is a sub-route (e.g. `/friends/<id>` activates the
 * "Friends" link).
 */
export function NavLink({ to, children, testID }: NavLinkProps) {
  const pathname = usePathname();
  const active = pathname === to || pathname.startsWith(`${to}/`);
  // RN-Web compiles NativeWind classes to opaque hashes, so tests use
  // `aria-current="page"` (the standards-aligned active marker) to
  // assert active state instead of grepping className.
  return (
    <Link
      href={to}
      testID={testID ?? `navlink-${to}`}
      {...({ 'aria-current': active ? 'page' : undefined } as Record<string, string | undefined>)}
    >
      <Text
        className={cn(
          'px-2 py-1 text-base font-medium',
          active ? 'text-primary-700 underline' : 'text-neutral-700',
        )}
      >
        {children}
      </Text>
    </Link>
  );
}
