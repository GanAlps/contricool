import { Redirect, Stack } from 'expo-router';

import { useAuthStore } from '~/lib/auth-store';

export default function AppLayout() {
  const user = useAuthStore((s) => s.user);
  const loading = useAuthStore((s) => s.loading);

  if (loading) {
    return null;
  }
  if (!user) {
    return <Redirect href="/login" />;
  }

  return <Stack screenOptions={{ headerShown: false }} />;
}
