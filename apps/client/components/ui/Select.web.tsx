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
 * Web Select — renders an actual DOM `<select>` for keyboard
 * accessibility and native browser dropdown behavior. Native uses
 * `Select.native.tsx` (Sheet-based picker) since RN-Web has no
 * built-in picker primitive.
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
