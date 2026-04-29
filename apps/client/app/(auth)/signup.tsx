import { zodResolver } from '@hookform/resolvers/zod';
import { Link, useRouter } from 'expo-router';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Text, View } from 'react-native';

import { Button } from '~/components/ui/Button';
import { Card } from '~/components/ui/Card';
import { Input } from '~/components/ui/Input';
import { Select } from '~/components/ui/Select';
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
import { SignupSchema, type SignupValues } from '~/lib/schemas';

const FRIENDLY = {
  EMAIL_EXISTS: 'An account with this email already exists.',
} as const;

export default function SignupScreen() {
  const router = useRouter();
  const signUp = useAuthStore((s) => s.signUp);
  const [banner, setBanner] = useState<string | null>(null);

  const form = useForm<SignupValues>({
    resolver: zodResolver(SignupSchema),
    defaultValues: {
      email: '',
      password: '',
      confirm_password: '',
      name: '',
      currency: 'USD',
      phone: '',
    },
  });

  const onSubmit = async (values: SignupValues): Promise<void> => {
    setBanner(null);
    const payload = {
      email: values.email,
      password: values.password,
      name: values.name,
      currency: values.currency,
      ...(values.phone ? { phone: values.phone } : {}),
    };
    try {
      await signUp(payload);
      router.replace({ pathname: '/verify-email', params: { email: values.email } });
    } catch (e) {
      if (!(e instanceof ApiErrorException)) {
        toast.error('Something went wrong. Please try again.');
        return;
      }
      const mapped = mapApiError(e.error, FRIENDLY);
      if (mapped.kind === 'banner') {
        setBanner(mapped.message);
      } else if (mapped.kind === 'toast') {
        toast.error(mapped.message);
      } else {
        for (const fe of mapped.errors) {
          form.setError(fe.field as keyof SignupValues, {
            type: 'server',
            message: fe.message,
          });
        }
      }
    }
  };

  return (
    <View className="flex-1 items-center justify-center bg-neutral-50 p-6">
      <Card testID="signup-card" className="w-full max-w-md">
        <Text className="mb-6 text-center text-2xl font-bold text-neutral-900">
          Create your account
        </Text>
        {banner ? (
          <View testID="signup-banner" className="mb-4 rounded-md bg-danger-600 p-3">
            <Text className="text-sm text-white">{banner}</Text>
            <Link
              testID="signup-login-link"
              href="/login"
              className="mt-1 text-sm text-white underline"
            >
              Log in instead
            </Link>
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
                    testID="signup-email"
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
            name="name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Name</FormLabel>
                <FormControl>
                  <Input testID="signup-name" value={field.value} onChangeText={field.onChange} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="currency"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Currency</FormLabel>
                <FormControl>
                  <Select
                    testID="signup-currency"
                    ariaLabel="Currency"
                    value={field.value}
                    onChange={field.onChange}
                    options={[
                      { label: 'US Dollar (USD)', value: 'USD' },
                      { label: 'Indian Rupee (INR)', value: 'INR' },
                    ]}
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
                    testID="signup-password"
                    secureTextEntry
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
            name="confirm_password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Confirm password</FormLabel>
                <FormControl>
                  <Input
                    testID="signup-confirm-password"
                    secureTextEntry
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
            name="phone"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Phone (optional)</FormLabel>
                <FormControl>
                  <Input
                    testID="signup-phone"
                    inputMode="tel"
                    placeholder="+14155552671"
                    value={field.value ?? ''}
                    onChangeText={field.onChange}
                  />
                </FormControl>
                <Text className="mt-1 text-xs text-neutral-500">
                  Optional. We won't verify or use this.
                </Text>
                <FormMessage />
              </FormItem>
            )}
          />
          <Button
            testID="signup-submit"
            onPress={form.handleSubmit(onSubmit)}
            loading={form.formState.isSubmitting}
            fullWidth
          >
            Create account
          </Button>
        </Form>
        <View className="mt-4 flex-row justify-center">
          <Text className="text-sm text-neutral-700">Already have an account? </Text>
          <Link
            testID="signup-bottom-login-link"
            href="/login"
            className="text-sm text-primary-600"
          >
            Sign in
          </Link>
        </View>
      </Card>
    </View>
  );
}
