import { useRouter } from 'expo-router';
import { Text, View } from 'react-native';

import { Button } from '~/components/ui/Button';
import { Card } from '~/components/ui/Card';
import { toast } from '~/components/ui/Toaster';
import { useAuthStore } from '~/lib/auth-store';

export default function DashboardScreen() {
  const user = useAuthStore((s) => s.user);
  const signOut = useAuthStore((s) => s.signOut);
  const router = useRouter();

  const onSignOut = async (): Promise<void> => {
    try {
      await signOut();
    } catch {
      toast.error('Sign out failed, but you have been signed out locally.');
    }
    router.replace('/login');
  };

  return (
    <View className="flex-1 items-center justify-center bg-neutral-50 p-6">
      <Card testID="dashboard-card" className="w-full max-w-md">
        <Text className="mb-2 text-center text-2xl font-bold text-neutral-900">
          Welcome, {user?.name ?? 'friend'}
        </Text>
        <Text testID="dashboard-currency" className="mb-6 text-center text-sm text-neutral-700">
          Currency: {user?.currency ?? '—'}
        </Text>
        <Button testID="dashboard-signout" onPress={onSignOut} variant="secondary" fullWidth>
          Sign out
        </Button>
      </Card>
    </View>
  );
}
