import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';

import { Input } from '~/components/ui/Input';

function Controlled({ initial = '' }: { initial?: string }) {
  const [v, setV] = useState(initial);
  return <Input testID="i" value={v} onChangeText={setV} />;
}

describe('Input', () => {
  it('renders and accepts user input', () => {
    render(<Controlled />);
    const input = screen.getByTestId('i') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'hello' } });
    expect(input.value).toBe('hello');
  });

  it('forwards aria-invalid when invalid', () => {
    render(<Input testID="i" invalid />);
    const input = screen.getByTestId('i');
    expect(input).toHaveAttribute('aria-invalid', 'true');
  });

  it('forwards aria-describedby for error linkage', () => {
    render(<Input testID="i" describedBy="err-1" />);
    expect(screen.getByTestId('i')).toHaveAttribute('aria-describedby', 'err-1');
  });

  it('honours secureTextEntry on web (renders password input)', () => {
    render(<Input testID="i" secureTextEntry />);
    const input = screen.getByTestId('i') as HTMLInputElement;
    expect(input.type).toBe('password');
  });
});
