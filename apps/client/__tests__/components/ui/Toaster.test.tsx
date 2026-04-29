import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Toaster, toast, useToasterStore } from '~/components/ui/Toaster';

describe('Toaster', () => {
  beforeEach(() => {
    useToasterStore.getState().clear();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows a queued success toast and auto-dismisses after duration', () => {
    render(<Toaster />);
    act(() => {
      toast.success('Saved!', 100);
    });
    expect(screen.getByTestId('toast-success')).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(screen.queryByTestId('toast-success')).toBeNull();
  });

  it('renders error and info kinds', () => {
    render(<Toaster />);
    act(() => {
      toast.error('Boom', 5000);
      toast.info('FYI', 5000);
    });
    expect(screen.getByTestId('toast-error')).toBeInTheDocument();
    expect(screen.getByTestId('toast-info')).toBeInTheDocument();
  });

  it('dismisses on press', () => {
    render(<Toaster />);
    act(() => {
      toast.success('Tap to close', 5000);
    });
    fireEvent.click(screen.getByTestId('toast-success'));
    expect(screen.queryByTestId('toast-success')).toBeNull();
  });
});
