/**
 * Top-level React error boundary.
 *
 * Wraps the app's root layout so any uncaught render-phase error
 * shows a friendly retry card AND posts a telemetry event to the
 * backend so we can debug it from CloudWatch.
 *
 * Plus a one-time installer for the global ``unhandledrejection``
 * and ``error`` events — those fire for promise rejections / async
 * failures that React's error boundary can't catch.
 */
import type { ReactNode } from 'react';
import { Component } from 'react';
import { Text, View } from 'react-native';

import { Button } from '~/components/ui/Button';
import { Card } from '~/components/ui/Card';
import { reportError } from '~/lib/telemetry';

type Props = { children: ReactNode };
type State = { error: Error | null };

export class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override componentDidCatch(error: Error): void {
    reportError('react-error-boundary', error);
  }

  reset = (): void => {
    this.setState({ error: null });
  };

  override render(): ReactNode {
    if (this.state.error) {
      return (
        <View className="flex-1 items-center justify-center bg-neutral-50 p-6">
          <Card testID="error-boundary-fallback">
            <Text className="mb-3 text-center text-lg font-semibold text-neutral-900">
              Something went wrong.
            </Text>
            <Text className="mb-4 text-center text-sm text-neutral-700">
              We've been notified. You can try again or refresh the page.
            </Text>
            <Button testID="error-boundary-retry" onPress={this.reset} fullWidth>
              Try again
            </Button>
          </Card>
        </View>
      );
    }
    return this.props.children;
  }
}

let installed = false;

/**
 * Install global handlers for unhandled-promise-rejection +
 * uncaught errors. Idempotent — calling more than once is a no-op.
 * Mounted from `app/_layout.tsx` once at bootstrap.
 */
export function installGlobalErrorTelemetry(): void {
  if (installed || typeof window === 'undefined') {
    return;
  }
  installed = true;
  window.addEventListener('unhandledrejection', (event) => {
    reportError('unhandled-rejection', event.reason);
  });
  window.addEventListener('error', (event) => {
    reportError('window-error', event.error ?? event.message);
  });
}

/** Test-only: reset the once-flag so subsequent tests re-install. */
export function _resetGlobalErrorTelemetryForTests(): void {
  installed = false;
}
