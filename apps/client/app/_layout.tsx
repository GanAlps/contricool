import { QueryClientProvider } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import { useEffect, useMemo } from 'react';
import { View } from 'react-native';

import { ErrorBoundary, installGlobalErrorTelemetry } from '~/components/ErrorBoundary';
import { Toaster } from '~/components/ui/Toaster';
import { useAuthStore } from '~/lib/auth-store';
import { makeQueryClient } from '~/lib/query-client';
import { reportWebVitals } from '~/lib/web-vitals';

import '../global.css';

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
        <View className="flex-1">
          <Stack screenOptions={{ headerShown: false }} />
          <Toaster />
        </View>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
