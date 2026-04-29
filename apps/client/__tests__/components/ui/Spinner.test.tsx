import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Spinner } from '~/components/ui/Spinner';

describe('Spinner', () => {
  it('renders with default testID', () => {
    render(<Spinner />);
    expect(screen.getByTestId('spinner')).toBeInTheDocument();
  });

  it('accepts a custom testID and size', () => {
    render(<Spinner testID="big" size="large" />);
    expect(screen.getByTestId('big')).toBeInTheDocument();
  });
});
