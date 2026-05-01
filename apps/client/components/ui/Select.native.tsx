import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { cn } from '~/lib/utils';

import { Sheet } from './Sheet';

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
 * Native Select — renders a tappable input that opens a Sheet-based
 * picker. Same prop surface as `Select.web.tsx` so call sites
 * (currently only the signup currency picker) work unchanged via
 * Metro's platform suffix resolution.
 *
 * Why Sheet (already in the codebase) over `@gorhom/bottom-sheet`:
 * the existing Sheet handles the modal + backdrop already, has zero
 * peer-dep cost, and works on both Android and iOS without
 * Reanimated/Worklets version pinning. The plan flagged
 * `@gorhom/bottom-sheet` as an option — keeping deps tight is the
 * better trade-off at MVP, and we can swap later if dropdown UX is
 * a problem in user testing.
 *
 * Accessibility: the trigger uses `accessibilityRole="combobox"` so
 * screen readers (TalkBack on Android, VoiceOver on iOS) announce
 * the control as a dropdown. Each option uses `accessibilityRole=
 * "menuitem"` (closest fit; RN doesn't have a `option` role).
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
  const [open, setOpen] = useState(false);
  const selected = options.find((o) => o.value === value);
  return (
    <>
      <Pressable
        accessibilityRole="combobox"
        accessibilityLabel={ariaLabel}
        accessibilityState={{ expanded: open }}
        accessibilityHint={describedBy}
        onPress={() => setOpen(true)}
        testID={testID}
        className={cn(
          'h-10 flex-row items-center justify-between rounded-md border bg-white px-3',
          invalid ? 'border-danger-600' : 'border-neutral-300',
          className,
        )}
      >
        <Text className="text-base text-neutral-900">{selected?.label ?? ''}</Text>
        <Text className="text-base text-neutral-500">▾</Text>
      </Pressable>
      <Sheet
        open={open}
        onClose={() => setOpen(false)}
        title={ariaLabel ?? 'Select'}
        testID={testID ? `${testID}-sheet` : 'select-sheet'}
      >
        <View className="p-2">
          {options.map((opt) => {
            const isSelected = opt.value === value;
            return (
              <Pressable
                key={opt.value}
                accessibilityRole="menuitem"
                accessibilityState={{ selected: isSelected }}
                onPress={() => {
                  // Don't fire onChange when the user taps the already-
                  // selected option — saves a needless re-render in the
                  // parent and a no-op network call if the consumer
                  // treats onChange as "user picked something new."
                  // Also covers the double-tap case: the second tap of a
                  // rapid double-tap on an already-fired option arrives
                  // when this option is now the selected one, so the
                  // guard keeps onChange idempotent.
                  if (!isSelected) {
                    onChange(opt.value);
                  }
                  setOpen(false);
                }}
                testID={testID ? `${testID}-option-${opt.value}` : undefined}
                className={cn(
                  'rounded-md px-3 py-3',
                  isSelected ? 'bg-primary-50' : 'bg-transparent',
                )}
              >
                <Text
                  className={cn(
                    'text-base',
                    isSelected ? 'font-semibold text-primary-700' : 'text-neutral-900',
                  )}
                >
                  {opt.label}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </Sheet>
    </>
  );
}
