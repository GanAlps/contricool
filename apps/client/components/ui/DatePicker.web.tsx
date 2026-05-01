import { createElement } from 'react';

export type DatePickerProps = {
  /** Current value as ISO `YYYY-MM-DD`. */
  value: string;
  /** Called with the new ISO `YYYY-MM-DD` string. */
  onChange: (value: string) => void;
  /** Latest acceptable date as ISO `YYYY-MM-DD`. */
  max?: string;
  /** Earliest acceptable date as ISO `YYYY-MM-DD`. */
  min?: string;
  testID?: string;
};

/**
 * Web DatePicker — wraps the browser-native `<input type="date">`.
 * Every modern desktop and mobile browser surfaces a real picker UI
 * (calendar grid on desktop, full-screen wheel on mobile). No custom
 * styling library, no extra dependency.
 *
 * RN-Web's `TextInput` doesn't accept `type="date"` so we drop down
 * to `createElement` for a real DOM input. NativeWind classes apply
 * via the `className` prop the same way they would on a `View`.
 */
export function DatePicker({ value, onChange, max, min, testID }: DatePickerProps) {
  return createElement('input', {
    type: 'date',
    value,
    onChange: (e: { target: { value: string } }) => onChange(e.target.value),
    max,
    min,
    'data-testid': testID,
    className: 'h-10 rounded-md border border-neutral-300 px-3 text-base text-neutral-900 bg-white',
  });
}
