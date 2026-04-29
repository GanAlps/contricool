import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { Button } from '~/components/ui/Button';

describe('Button', () => {
  it('renders children and triggers onPress when enabled', () => {
    const onPress = vi.fn();
    render(
      <Button testID="b" onPress={onPress}>
        Click me
      </Button>,
    );
    expect(screen.getByText('Click me')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('b'));
    expect(onPress).toHaveBeenCalledOnce();
  });

  it('does not fire onPress when disabled', () => {
    const onPress = vi.fn();
    render(
      <Button testID="b" onPress={onPress} disabled>
        Disabled
      </Button>,
    );
    fireEvent.click(screen.getByTestId('b'));
    expect(onPress).not.toHaveBeenCalled();
  });

  it('shows a Spinner and blocks press while loading', () => {
    const onPress = vi.fn();
    render(
      <Button testID="b" onPress={onPress} loading>
        Submitting
      </Button>,
    );
    expect(screen.getByTestId('b-spinner')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('b'));
    expect(onPress).not.toHaveBeenCalled();
  });

  it('renders the destructive variant', () => {
    render(
      <Button testID="b" variant="destructive">
        Delete
      </Button>,
    );
    expect(screen.getByTestId('b')).toBeInTheDocument();
  });

  it('renders the secondary variant at lg size full width', () => {
    render(
      <Button testID="b" variant="secondary" size="lg" fullWidth>
        Big
      </Button>,
    );
    expect(screen.getByTestId('b')).toBeInTheDocument();
  });

  it('renders the ghost variant at sm size', () => {
    render(
      <Button testID="b" variant="ghost" size="sm">
        Tiny
      </Button>,
    );
    expect(screen.getByTestId('b')).toBeInTheDocument();
  });

  it('forwards accessibilityLabel', () => {
    render(
      <Button testID="b" accessibilityLabel="Sign in to your account">
        Sign in
      </Button>,
    );
    expect(screen.getByLabelText('Sign in to your account')).toBeInTheDocument();
  });
});
