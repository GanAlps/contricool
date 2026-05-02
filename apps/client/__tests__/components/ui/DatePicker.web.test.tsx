/**
 * Web DatePicker — wraps the browser-native `<input type="date">`.
 * Tests verify the value/onChange/min/max/testID props translate to
 * the underlying DOM input and that user input fires onChange with
 * the new ISO date.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DatePicker } from '~/components/ui/DatePicker.web';

describe('DatePicker.web', () => {
  it('renders a native `<input type="date">` reflecting the value', () => {
    render(<DatePicker testID="d" value="2026-04-29" onChange={() => {}} />);
    const input = screen.getByTestId('d') as HTMLInputElement;
    expect(input.tagName).toBe('INPUT');
    expect(input.type).toBe('date');
    expect(input.value).toBe('2026-04-29');
  });

  it('calls onChange with the new ISO date when the user picks one', () => {
    const onChange = vi.fn();
    render(<DatePicker testID="d" value="2026-04-29" onChange={onChange} />);
    fireEvent.change(screen.getByTestId('d'), { target: { value: '2026-05-01' } });
    expect(onChange).toHaveBeenCalledWith('2026-05-01');
  });

  it('threads `min` and `max` through to the DOM input attributes', () => {
    render(
      <DatePicker
        testID="d"
        value="2026-04-29"
        onChange={() => {}}
        min="2026-01-01"
        max="2026-12-31"
      />,
    );
    const input = screen.getByTestId('d') as HTMLInputElement;
    expect(input.min).toBe('2026-01-01');
    expect(input.max).toBe('2026-12-31');
  });

  it('omits `min` / `max` attributes when those props are not provided', () => {
    render(<DatePicker testID="d" value="2026-04-29" onChange={() => {}} />);
    const input = screen.getByTestId('d') as HTMLInputElement;
    expect(input.min).toBe('');
    expect(input.max).toBe('');
  });
});
