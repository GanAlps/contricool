/**
 * Native Select — Sheet-based picker. Tests run under jsdom + RN-Web
 * aliasing (vitest config), so RN primitives (Pressable, View, Text)
 * render to DOM elements and `fireEvent.click` on a Pressable
 * triggers `onPress`. We import via the explicit `.native` suffix
 * so vitest doesn't pick the `.web.tsx` variant.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { Select } from '~/components/ui/Select.native';

const opts = [
  { label: 'US Dollar', value: 'USD' },
  { label: 'Indian Rupee', value: 'INR' },
];

describe('Select.native', () => {
  it('renders the currently-selected option label as the trigger text', () => {
    render(
      <Select testID="curr" ariaLabel="Currency" value="USD" onChange={() => {}} options={opts} />,
    );
    const trigger = screen.getByTestId('curr');
    expect(trigger).toHaveTextContent('US Dollar');
  });

  it('opens the Sheet when the trigger is pressed', () => {
    render(
      <Select testID="curr" ariaLabel="Currency" value="USD" onChange={() => {}} options={opts} />,
    );
    // Sheet is closed at mount → option is not in the DOM.
    expect(screen.queryByTestId('curr-option-INR')).toBeNull();
    fireEvent.click(screen.getByTestId('curr'));
    expect(screen.getByTestId('curr-option-INR')).toBeTruthy();
  });

  it('fires onChange with the picked value and closes the sheet', () => {
    const onChange = vi.fn();
    render(
      <Select testID="curr" ariaLabel="Currency" value="USD" onChange={onChange} options={opts} />,
    );
    fireEvent.click(screen.getByTestId('curr'));
    fireEvent.click(screen.getByTestId('curr-option-INR'));
    expect(onChange).toHaveBeenCalledWith('INR');
    // Sheet closes after selection — the option is no longer mounted.
    expect(screen.queryByTestId('curr-option-INR')).toBeNull();
  });

  it('renders an empty trigger label when value does not match any option (defensive)', () => {
    render(
      <Select testID="curr" ariaLabel="Currency" value="ZZZ" onChange={() => {}} options={opts} />,
    );
    const trigger = screen.getByTestId('curr');
    // Empty selection → trigger shows just the chevron, no label text.
    expect(trigger.textContent).toBe('▾');
  });

  it('exposes the trigger as a combobox via accessibilityRole', () => {
    render(
      <Select testID="curr" ariaLabel="Currency" value="USD" onChange={() => {}} options={opts} />,
    );
    // RN-Web maps `accessibilityRole="combobox"` → `role="combobox"`.
    // Screen readers use this to announce the dropdown semantics.
    const triggers = screen.getAllByRole('combobox');
    expect(triggers).toHaveLength(1);
  });

  it('opens the sheet under a default testID when no prop testID is given', () => {
    render(<Select ariaLabel="Currency" value="USD" onChange={() => {}} options={opts} />);
    fireEvent.click(screen.getAllByRole('combobox')[0]!);
    // Default fallback: `'select-sheet'` (see Select.native.tsx).
    expect(screen.getByTestId('select-sheet')).toBeTruthy();
  });

  it('forwards invalid styling without throwing', () => {
    render(
      <Select
        testID="curr"
        invalid
        ariaLabel="Currency"
        value="USD"
        onChange={() => {}}
        options={opts}
      />,
    );
    // Invalid is reflected in the className string; we don't assert on
    // generated CSS hashes (brittle) — just verify the component
    // doesn't crash on the invalid path and the trigger still renders.
    expect(screen.getByTestId('curr')).toBeTruthy();
  });

  // Backdrop / close-button behavior — verify the dismiss paths
  // don't accidentally fire onChange. Without this gap protection,
  // a future regression (e.g. wrapping the Sheet's onClose in an
  // onChange-firing handler) would not be caught.
  it('backdrop press closes the sheet without firing onChange', () => {
    const onChange = vi.fn();
    render(
      <Select testID="curr" ariaLabel="Currency" value="USD" onChange={onChange} options={opts} />,
    );
    fireEvent.click(screen.getByTestId('curr'));
    // Sheet builds its backdrop testID from the parent testID:
    // `${parent}-backdrop`. Our parent passes `${testID}-sheet` to
    // Sheet, so the backdrop is `curr-sheet-backdrop`.
    fireEvent.click(screen.getByTestId('curr-sheet-backdrop'));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByTestId('curr-option-INR')).toBeNull();
  });

  it('close button (×) closes the sheet without firing onChange', () => {
    const onChange = vi.fn();
    render(
      <Select testID="curr" ariaLabel="Currency" value="USD" onChange={onChange} options={opts} />,
    );
    fireEvent.click(screen.getByTestId('curr'));
    fireEvent.click(screen.getByTestId('curr-sheet-close'));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByTestId('curr-option-INR')).toBeNull();
  });

  it('tapping the already-selected option does NOT fire onChange (idempotency / double-tap guard)', () => {
    const onChange = vi.fn();
    render(
      <Select testID="curr" ariaLabel="Currency" value="USD" onChange={onChange} options={opts} />,
    );
    fireEvent.click(screen.getByTestId('curr'));
    fireEvent.click(screen.getByTestId('curr-option-USD'));
    // Same value tapped → onChange must not fire (saves a redundant
    // parent re-render and an idempotent-but-wasted network call).
    expect(onChange).not.toHaveBeenCalled();
    // Sheet still closes — the user's intent was "I'm done picking."
    expect(screen.queryByTestId('curr-option-INR')).toBeNull();
  });
});
