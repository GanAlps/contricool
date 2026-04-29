import { type VariantProps, cva } from 'class-variance-authority';
import type { ReactNode } from 'react';
import { type AccessibilityRole, Pressable, Text } from 'react-native';

import { cn } from '~/lib/utils';

import { Spinner } from './Spinner';

const buttonStyles = cva('flex-row items-center justify-center rounded-md border-0 select-none', {
  variants: {
    variant: {
      primary: 'bg-primary-600 active:bg-primary-700',
      secondary: 'bg-neutral-100 active:bg-neutral-200',
      ghost: 'bg-transparent active:bg-neutral-100',
      destructive: 'bg-danger-600 active:opacity-90',
    },
    size: {
      sm: 'h-8 px-3',
      md: 'h-10 px-4',
      lg: 'h-12 px-6',
    },
    fullWidth: {
      true: 'w-full',
      false: '',
    },
    disabled: {
      true: 'opacity-50',
      false: '',
    },
  },
  defaultVariants: {
    variant: 'primary',
    size: 'md',
    fullWidth: false,
    disabled: false,
  },
});

const labelStyles = cva('font-semibold', {
  variants: {
    variant: {
      primary: 'text-white',
      secondary: 'text-neutral-900',
      ghost: 'text-neutral-900',
      destructive: 'text-white',
    },
    size: {
      sm: 'text-sm',
      md: 'text-base',
      lg: 'text-lg',
    },
  },
  defaultVariants: { variant: 'primary', size: 'md' },
});

type ButtonVariants = VariantProps<typeof buttonStyles>;

export type ButtonProps = {
  children: ReactNode;
  onPress?: () => void;
  loading?: boolean;
  disabled?: boolean;
  testID?: string;
  accessibilityLabel?: string;
  accessibilityRole?: AccessibilityRole;
  type?: 'button' | 'submit';
} & Pick<ButtonVariants, 'variant' | 'size' | 'fullWidth'>;

export function Button({
  children,
  onPress,
  loading = false,
  disabled = false,
  variant = 'primary',
  size = 'md',
  fullWidth = false,
  testID,
  accessibilityLabel,
  accessibilityRole = 'button',
  type = 'button',
}: ButtonProps) {
  const isDisabled = disabled || loading;
  return (
    <Pressable
      onPress={isDisabled ? undefined : onPress}
      disabled={isDisabled}
      accessibilityRole={accessibilityRole}
      accessibilityState={{ disabled: isDisabled, busy: loading }}
      accessibilityLabel={accessibilityLabel}
      testID={testID}
      // RN-Web maps `type` to the underlying <button type="..."> attribute.
      // Cast through unknown so TS doesn't complain on native.
      {...({ type } as unknown as Record<string, string>)}
      className={cn(buttonStyles({ variant, size, fullWidth, disabled: isDisabled }))}
    >
      {loading ? (
        <Spinner size="small" color="#fff" testID={testID ? `${testID}-spinner` : undefined} />
      ) : null}
      <Text className={cn(labelStyles({ variant, size }), loading ? 'ml-2' : null)}>
        {children}
      </Text>
    </Pressable>
  );
}
