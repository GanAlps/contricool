import { fireEvent, render, screen } from '@testing-library/react';
import { Text } from 'react-native';
import { describe, expect, it, vi } from 'vitest';

import { Sheet } from '~/components/ui/Sheet';

describe('Sheet', () => {
  it('renders nothing when closed', () => {
    render(
      <Sheet open={false} onClose={() => {}} testID="s">
        <Text>body</Text>
      </Sheet>,
    );
    expect(screen.queryByTestId('s')).not.toBeInTheDocument();
  });

  it('renders title and children when open', () => {
    render(
      <Sheet open onClose={() => {}} title="Add friend" testID="s">
        <Text>body</Text>
      </Sheet>,
    );
    expect(screen.getByTestId('s')).toBeInTheDocument();
    expect(screen.getByText('Add friend')).toBeInTheDocument();
    expect(screen.getByText('body')).toBeInTheDocument();
  });

  it('fires onClose when backdrop is pressed', () => {
    const onClose = vi.fn();
    render(
      <Sheet open onClose={onClose} testID="s">
        <Text>body</Text>
      </Sheet>,
    );
    fireEvent.click(screen.getByTestId('s-backdrop'));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('fires onClose when close button is pressed', () => {
    const onClose = vi.fn();
    render(
      <Sheet open onClose={onClose} testID="s">
        <Text>body</Text>
      </Sheet>,
    );
    fireEvent.click(screen.getByTestId('s-close'));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('uses default testID when none provided', () => {
    render(
      <Sheet open onClose={() => {}}>
        <Text>body</Text>
      </Sheet>,
    );
    expect(screen.getByTestId('sheet')).toBeInTheDocument();
    expect(screen.getByTestId('sheet-backdrop')).toBeInTheDocument();
    expect(screen.getByTestId('sheet-close')).toBeInTheDocument();
  });
});
