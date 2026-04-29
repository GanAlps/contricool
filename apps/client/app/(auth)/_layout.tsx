import { Redirect, Stack } from 'expo-router';

import { useAuthStore } from '~/lib/auth-store';

export default function AuthLayout() {
  const user = useAuthStore((s) => s.user);
  const loading = useAuthStore((s) => s.loading);

  if (!loading && user) {
    return <Redirect href="/dashboard" />;
  }

  return <Stack screenOptions={{ headerShown: false }} />;
}
