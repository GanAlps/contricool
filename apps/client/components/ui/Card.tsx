import type { ReactNode } from 'react';
import { View } from 'react-native';

import { cn } from '~/lib/utils';

export function Card({
  children,
  className,
  testID,
}: { children: ReactNode; className?: string; testID?: string }) {
  return (
    <View
      className={cn('rounded-lg border border-neutral-200 bg-white p-6 shadow-sm', className)}
      testID={testID}
    >
      {children}
    </View>
  );
}
