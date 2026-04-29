import { render, screen } from '@testing-library/react';
import { Text } from 'react-native';
import { describe, expect, it } from 'vitest';

import { Card } from '~/components/ui/Card';

describe('Card', () => {
  it('renders children inside the surface', () => {
    render(
      <Card testID="c">
        <Text>hello</Text>
      </Card>,
    );
    expect(screen.getByTestId('c')).toBeInTheDocument();
    expect(screen.getByText('hello')).toBeInTheDocument();
  });
});
