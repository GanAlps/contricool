import DateTimePicker, { type DateTimePickerEvent } from '@react-native-community/datetimepicker';
import { useState } from 'react';
import { Platform, Pressable, Text } from 'react-native';

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
 * Native DatePicker — opens the platform-native picker on tap.
 *
 * iOS uses `display="inline"` (always-visible embedded wheel that
 * lives next to the trigger). Each spin fires `onChange` with
 * `event.type === 'set'`, so the row commits incrementally as the
 * user spins; the picker doesn't have its own dismiss button —
 * closing the surrounding Sheet is the dismiss path. Intentional
 * UX trade-off: simpler than juggling a separate "Done" button.
 *
 * Android uses `display="default"` which pops a one-shot dialog
 * (`DialogAndroid`). The picker dismisses itself on confirm or
 * cancel and `onChange` fires with `event.type === 'set'`
 * (confirm) or `'dismissed'` (cancel) — we collapse the modal in
 * both cases to match Android UX expectations.
 */
export function DatePicker({ value, onChange, max, min, testID }: DatePickerProps) {
  const [show, setShow] = useState(false);
  const date = parseIsoDate(value);
  const minDate = min ? parseIsoDate(min) : undefined;
  const maxDate = max ? parseIsoDate(max) : undefined;

  const handleChange = (event: DateTimePickerEvent, picked?: Date): void => {
    // Android: dismiss the modal regardless of confirm/cancel.
    // iOS:     keep it inline; the wheel commits on each spin.
    if (Platform.OS === 'android') {
      setShow(false);
    }
    if (event.type === 'set' && picked) {
      onChange(formatIsoDate(picked));
    }
  };

  return (
    <>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`Pick date, currently ${value}`}
        onPress={() => setShow(true)}
        testID={testID}
        className="h-10 justify-center rounded-md border border-neutral-300 bg-white px-3 active:bg-neutral-50"
      >
        <Text className="text-base text-neutral-900">{value}</Text>
      </Pressable>
      {show ? (
        <DateTimePicker
          value={date}
          mode="date"
          display={Platform.OS === 'ios' ? 'inline' : 'default'}
          onChange={handleChange}
          minimumDate={minDate}
          maximumDate={maxDate}
          testID={testID ? `${testID}-picker` : undefined}
        />
      ) : null}
    </>
  );
}

function parseIsoDate(s: string): Date {
  // `new Date('YYYY-MM-DD')` parses as UTC midnight which can shift the
  // displayed day across timezones. Build a local-time date instead so
  // the picker shows the same day the user typed.
  const [y, m, d] = s.split('-').map(Number);
  if (!y || !m || !d) {
    return new Date();
  }
  return new Date(y, m - 1, d);
}

function formatIsoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}
