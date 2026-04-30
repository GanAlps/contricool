import { Redirect, Stack, useRouter } from 'expo-router';
import { Text, View } from 'react-native';

import { Button } from '~/components/ui/Button';
import { NavLink } from '~/components/ui/NavLink';
import { toast } from '~/components/ui/Toaster';
import { useAuthStore } from '~/lib/auth-store';

export default function AppLayout() {
  const user = useAuthStore((s) => s.user);
  const loading = useAuthStore((s) => s.loading);
  const signOut = useAuthStore((s) => s.signOut);
  const router = useRouter();

  if (loading) {
    return null;
  }
  if (!user) {
    return <Redirect href="/login" />;
  }

  const onSignOut = async (): Promise<void> => {
    try {
      await signOut();
    } catch {
      toast.error('Sign out failed, but you have been signed out locally.');
    }
    router.replace('/login');
  };

  return (
    <View className="flex-1">
      <View
        testID="app-topbar"
        className="flex-row items-center justify-between border-b border-neutral-200 bg-white px-4 py-2"
      >
        <View className="flex-row items-center gap-4">
          <NavLink to="/dashboard" testID="navlink-dashboard">
            Dashboard
          </NavLink>
          <NavLink to="/friends" testID="navlink-friends">
            Friends
          </NavLink>
          <NavLink to="/transactions" testID="navlink-transactions">
            Transactions
          </NavLink>
        </View>
        <View className="flex-row items-center gap-3">
          <Text testID="topbar-user" className="text-sm text-neutral-700">
            {user.name}
          </Text>
          <Button testID="topbar-signout" variant="ghost" size="sm" onPress={onSignOut}>
            Sign out
          </Button>
        </View>
      </View>
      <Stack screenOptions={{ headerShown: false }} />
    </View>
  );
}
