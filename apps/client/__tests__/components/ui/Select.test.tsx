import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { Select } from '~/components/ui/Select';

describe('Select', () => {
  it('renders the options and fires onChange on selection', () => {
    const onChange = vi.fn();
    render(
      <Select
        testID="curr"
        ariaLabel="Currency"
        value="USD"
        onChange={onChange}
        options={[
          { label: 'US Dollar', value: 'USD' },
          { label: 'Indian Rupee', value: 'INR' },
        ]}
      />,
    );
    const sel = screen.getByTestId('curr') as HTMLSelectElement;
    expect(sel.value).toBe('USD');
    fireEvent.change(sel, { target: { value: 'INR' } });
    expect(onChange).toHaveBeenCalledWith('INR');
  });

  it('threads aria-invalid when invalid', () => {
    render(
      <Select
        testID="curr"
        invalid
        ariaLabel="Currency"
        value="USD"
        onChange={() => {}}
        options={[{ label: 'US Dollar', value: 'USD' }]}
      />,
    );
    expect(screen.getByTestId('curr')).toHaveAttribute('aria-invalid', 'true');
  });
});
