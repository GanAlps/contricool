import type { ReactNode } from 'react';
import { Platform, Text } from 'react-native';

import { cn } from '~/lib/utils';

export type LabelProps = {
  htmlFor?: string;
  children: ReactNode;
  className?: string;
  testID?: string;
};

export function Label({ htmlFor, children, className, testID }: LabelProps) {
  const classes = cn('mb-1 text-sm font-medium text-neutral-900', className);

  if (Platform.OS === 'web') {
    // Render an actual <label> so screen readers and click-to-focus
    // associate with the matching input.
    return (
      <label htmlFor={htmlFor} className={classes} data-testid={testID}>
        {children}
      </label>
    );
  }

  return (
    <Text className={classes} testID={testID}>
      {children}
    </Text>
  );
}
