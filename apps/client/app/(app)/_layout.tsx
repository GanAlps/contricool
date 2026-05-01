import { Redirect, Stack, useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, Text, View, useWindowDimensions } from 'react-native';

import { Button } from '~/components/ui/Button';
import { NavLink } from '~/components/ui/NavLink';
import { toast } from '~/components/ui/Toaster';
import { useAuthStore } from '~/lib/auth-store';

const NAV_ITEMS: {
  to: '/dashboard' | '/friends' | '/transactions' | '/settings';
  label: string;
}[] = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/friends', label: 'Friends' },
  { to: '/transactions', label: 'Transactions' },
  { to: '/settings', label: 'Settings' },
];

// Tailwind `md` breakpoint. Below this we collapse the nav into a
// hamburger that toggles an inline dropdown so it fits on phones and
// narrow web viewports.
const MOBILE_BREAKPOINT = 768;

export default function AppLayout() {
  const user = useAuthStore((s) => s.user);
  const loading = useAuthStore((s) => s.loading);
  const signOut = useAuthStore((s) => s.signOut);
  const router = useRouter();
  const { width } = useWindowDimensions();
  const [menuOpen, setMenuOpen] = useState(false);

  if (loading) {
    return null;
  }
  if (!user) {
    return <Redirect href="/login" />;
  }

  const onSignOut = async (): Promise<void> => {
    setMenuOpen(false);
    try {
      await signOut();
    } catch {
      toast.error('Sign out failed, but you have been signed out locally.');
    }
    router.replace('/login');
  };

  const goTo = (to: '/dashboard' | '/friends' | '/transactions' | '/settings'): void => {
    setMenuOpen(false);
    router.push(to);
  };

  const isMobile = width < MOBILE_BREAKPOINT;

  return (
    <View className="flex-1">
      {/* Topbar + dropdown menu live in the same relative wrapper so
          the absolute-positioned dropdown anchors to the topbar bottom
          via `top-full`. */}
      <View className="relative z-50">
        <View
          testID="app-topbar"
          className="flex-row items-center justify-between border-b border-neutral-200 bg-white px-4 py-2"
        >
          {isMobile ? (
            <>
              <Pressable
                testID="topbar-menu-trigger"
                accessibilityRole="button"
                accessibilityLabel={menuOpen ? 'Close navigation menu' : 'Open navigation menu'}
                accessibilityState={{ expanded: menuOpen }}
                onPress={() => setMenuOpen((o) => !o)}
                className="rounded-md px-2 py-1 active:bg-neutral-100"
              >
                <Text className="text-2xl text-neutral-800">☰</Text>
              </Pressable>
              <Text testID="topbar-title" className="text-base font-semibold text-neutral-900">
                ContriCool
              </Text>
              <Text testID="topbar-user" className="text-sm text-neutral-700">
                {user.name}
              </Text>
            </>
          ) : (
            <>
              <View className="flex-row items-center gap-4">
                {NAV_ITEMS.map((item) => (
                  <NavLink key={item.to} to={item.to} testID={`navlink-${item.to.slice(1)}`}>
                    {item.label}
                  </NavLink>
                ))}
              </View>
              <View className="flex-row items-center gap-3">
                <Text testID="topbar-user" className="text-sm text-neutral-700">
                  {user.name}
                </Text>
                <Button testID="topbar-signout" variant="ghost" size="sm" onPress={onSignOut}>
                  Sign out
                </Button>
              </View>
            </>
          )}
        </View>

        {isMobile && menuOpen ? (
          <View
            testID="topbar-menu"
            className="absolute inset-x-0 top-full border-b border-neutral-200 bg-white shadow-md"
          >
            <View className="gap-1 p-2">
              {NAV_ITEMS.map((item) => (
                <Pressable
                  key={item.to}
                  testID={`topbar-menu-${item.to.slice(1)}`}
                  accessibilityRole="link"
                  onPress={() => goTo(item.to)}
                  className="rounded-md px-3 py-3 active:bg-neutral-100"
                >
                  <Text className="text-base text-neutral-800">{item.label}</Text>
                </Pressable>
              ))}
              <View className="my-1 h-px bg-neutral-200" />
              <Button testID="topbar-menu-signout" variant="ghost" onPress={onSignOut} fullWidth>
                Sign out
              </Button>
            </View>
          </View>
        ) : null}
      </View>

      <Stack screenOptions={{ headerShown: false }} />
    </View>
  );
}
