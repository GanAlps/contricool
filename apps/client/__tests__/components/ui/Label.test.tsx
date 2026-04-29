import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Label } from '~/components/ui/Label';

describe('Label', () => {
  it('renders children', () => {
    render(<Label testID="l">Email</Label>);
    expect(screen.getByText('Email')).toBeInTheDocument();
  });

  it('forwards htmlFor', () => {
    render(
      <Label testID="l" htmlFor="email-input">
        Email
      </Label>,
    );
    expect(screen.getByTestId('l')).toHaveAttribute('for', 'email-input');
  });
});
