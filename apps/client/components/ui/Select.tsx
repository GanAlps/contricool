import { Platform } from 'react-native';

import { cn } from '~/lib/utils';

export type SelectOption = { label: string; value: string };

export type SelectProps = {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  invalid?: boolean;
  describedBy?: string;
  ariaLabel?: string;
  testID?: string;
  className?: string;
};

/**
 * Web-only Select for Phase 2d.  RN-Web doesn't ship a native picker,
 * so we render an actual DOM `<select>` on web.  Native phase will
 * swap in a sheet-based picker.
 */
export function Select({
  value,
  onChange,
  options,
  invalid = false,
  describedBy,
  ariaLabel,
  testID,
  className,
}: SelectProps) {
  if (Platform.OS !== 'web') {
    // Native fallback intentionally absent in 2d.
    return null;
  }

  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-invalid={invalid || undefined}
      aria-describedby={describedBy}
      aria-label={ariaLabel}
      data-testid={testID}
      className={cn(
        'h-10 rounded-md border bg-white px-3 text-base text-neutral-900',
        invalid ? 'border-danger-600' : 'border-neutral-300',
        className,
      )}
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  );
}
