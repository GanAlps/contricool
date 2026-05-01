import { QueryClientProvider } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import { useEffect, useMemo } from 'react';
import { View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ErrorBoundary, installGlobalErrorTelemetry } from '~/components/ErrorBoundary';
import { Toaster } from '~/components/ui/Toaster';
import { useAuthStore } from '~/lib/auth-store';
import { makeQueryClient } from '~/lib/query-client';
import { initSentry } from '~/lib/sentry';
import { reportWebVitals } from '~/lib/web-vitals';

import '../global.css';

// Initialize Sentry at module scope, before React mounts. On web this
// is a no-op (errors flow through `/v1/telemetry/error`); on native
// it wires `@sentry/react-native` so an early crash during render is
// still captured.
initSentry();

export default function RootLayout() {
  const queryClient = useMemo(() => makeQueryClient(), []);
  const refreshSession = useAuthStore((s) => s.refreshSession);

  useEffect(() => {
    installGlobalErrorTelemetry();
    reportWebVitals();
    refreshSession();
  }, [refreshSession]);

  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <SafeAreaProvider>
          <View className="flex-1">
            <Stack screenOptions={{ headerShown: false }} />
            <Toaster />
          </View>
        </SafeAreaProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
