import { zodResolver } from '@hookform/resolvers/zod';
import { Link, useRouter } from 'expo-router';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Text, View } from 'react-native';

import { Button } from '~/components/ui/Button';
import { Card } from '~/components/ui/Card';
import { Input } from '~/components/ui/Input';
import { toast } from '~/components/ui/Toaster';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '~/components/ui/form';
import { ApiErrorException } from '~/lib/api';
import { useAuthStore } from '~/lib/auth-store';
import { mapApiError } from '~/lib/error-mapping';
import { LoginSchema, type LoginValues } from '~/lib/schemas';

const FRIENDLY = {
  INVALID_CREDENTIALS: 'Email or password is incorrect.',
  ACCOUNT_NOT_ACTIVE: 'Please verify your email first.',
} as const;

export default function LoginScreen() {
  const router = useRouter();
  const signIn = useAuthStore((s) => s.signIn);
  const [banner, setBanner] = useState<{ message: string; verifyEmail?: string } | null>(null);

  const form = useForm<LoginValues>({
    resolver: zodResolver(LoginSchema),
    defaultValues: { email: '', password: '' },
  });

  const onSubmit = async (values: LoginValues): Promise<void> => {
    setBanner(null);
    try {
      await signIn(values);
      router.replace('/dashboard');
    } catch (e) {
      if (!(e instanceof ApiErrorException)) {
        toast.error('Something went wrong. Please try again.');
        return;
      }
      const mapped = mapApiError(e.error, FRIENDLY);
      if (mapped.kind === 'banner') {
        setBanner({
          message: mapped.message,
          ...(e.error.code === 'ACCOUNT_NOT_ACTIVE' ? { verifyEmail: values.email } : {}),
        });
      } else if (mapped.kind === 'toast') {
        toast.error(mapped.message);
      } else {
        for (const fe of mapped.errors) {
          form.setError(fe.field as keyof LoginValues, {
            type: 'server',
            message: fe.message,
          });
        }
      }
    }
  };

  return (
    <View className="flex-1 items-center justify-center bg-neutral-50 p-6">
      <Card testID="login-card" className="w-full max-w-md">
        <Text className="mb-6 text-center text-2xl font-bold text-neutral-900">
          Sign in to ContriCool
        </Text>
        {banner ? (
          <View testID="login-banner" className="mb-4 rounded-md bg-danger-600 p-3">
            <Text className="text-sm text-white">{banner.message}</Text>
            {banner.verifyEmail ? (
              <Link
                testID="login-verify-link"
                href={{ pathname: '/verify-email', params: { email: banner.verifyEmail } }}
                className="mt-1 text-sm text-white underline"
              >
                Verify your email
              </Link>
            ) : null}
          </View>
        ) : null}
        <Form form={form}>
          <FormField
            control={form.control}
            name="email"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Email</FormLabel>
                <FormControl>
                  <Input
                    testID="login-email"
                    autoCapitalize="none"
                    autoCorrect={false}
                    inputMode="email"
                    value={field.value}
                    onChangeText={field.onChange}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Password</FormLabel>
                <FormControl>
                  <Input
                    testID="login-password"
                    secureTextEntry
                    value={field.value}
                    onChangeText={field.onChange}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <Button
            testID="login-submit"
            onPress={form.handleSubmit(onSubmit)}
            loading={form.formState.isSubmitting}
            fullWidth
          >
            Sign in
          </Button>
        </Form>
        <View className="mt-4 flex-row justify-between">
          <Link
            testID="login-forgot-link"
            href="/forgot-password"
            className="text-sm text-primary-600"
          >
            Forgot password?
          </Link>
          <Link testID="login-signup-link" href="/signup" className="text-sm text-primary-600">
            Sign up
          </Link>
        </View>
      </Card>
    </View>
  );
}
