import { Redirect, Stack } from 'expo-router';
import { Keyboard, KeyboardAvoidingView, Platform, Pressable } from 'react-native';

import { useAuthStore } from '~/lib/auth-store';

export default function AuthLayout() {
  const user = useAuthStore((s) => s.user);
  const loading = useAuthStore((s) => s.loading);

  if (!loading && user) {
    return <Redirect href="/dashboard" />;
  }

  // KeyboardAvoidingView lifts content above the on-screen keyboard so
  // error banners + toasts beneath the inputs stay visible. The
  // surrounding Pressable lets the user dismiss the keyboard by
  // tapping anywhere off an input — iOS doesn't provide this by
  // default, and without it the keyboard otherwise hides errors with
  // no way to read them. Android's `windowSoftInputMode` already
  // handles the layout shift, so the Platform-gated `behavior` is
  // iOS-only by design.
  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <Pressable style={{ flex: 1 }} onPress={Keyboard.dismiss} accessible={false}>
        <Stack screenOptions={{ headerShown: false }} />
      </Pressable>
    </KeyboardAvoidingView>
  );
}
