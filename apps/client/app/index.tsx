import { Redirect } from 'expo-router';
import { View } from 'react-native';

import { Spinner } from '~/components/ui/Spinner';
import { useAuthStore } from '~/lib/auth-store';

export default function Index() {
  const user = useAuthStore((s) => s.user);
  const loading = useAuthStore((s) => s.loading);

  if (loading) {
    return (
      <View testID="boot-spinner" className="flex-1 items-center justify-center bg-neutral-50">
        <Spinner size="large" />
      </View>
    );
  }

  return user ? <Redirect href="/dashboard" /> : <Redirect href="/login" />;
}
