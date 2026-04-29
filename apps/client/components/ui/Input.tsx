import { forwardRef } from 'react';
import { TextInput, type TextInputProps } from 'react-native';

import { cn } from '~/lib/utils';

export type InputProps = TextInputProps & {
  invalid?: boolean;
  describedBy?: string;
};

export const Input = forwardRef<TextInput, InputProps>(function Input(
  { className, invalid = false, describedBy, ...rest },
  ref,
) {
  return (
    <TextInput
      ref={ref}
      // RN-Web threads aria-* props onto the DOM <input>; cast via unknown
      // because RN's TextInputProps doesn't include them.
      {...({
        'aria-invalid': invalid || undefined,
        'aria-describedby': describedBy,
      } as unknown as Record<string, string>)}
      className={cn(
        'h-10 rounded-md border bg-white px-3 text-base text-neutral-900',
        invalid ? 'border-danger-600' : 'border-neutral-300',
        'focus:border-primary-600',
        className as string | undefined,
      )}
      placeholderTextColor="#94a3b8"
      {...rest}
    />
  );
});
