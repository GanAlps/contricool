import { zodResolver } from '@hookform/resolvers/zod';
import { useLocalSearchParams, useRouter } from 'expo-router';
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
import { ResetPasswordSchema, type ResetPasswordValues } from '~/lib/schemas';

const FRIENDLY = {
  INVALID_CODE: 'Code is wrong or expired.',
  PASSWORD_REUSED: 'New password must be different from your current password.',
} as const;

export default function ResetPasswordScreen() {
  const params = useLocalSearchParams<{ email?: string }>();
  const router = useRouter();
  const resetPassword = useAuthStore((s) => s.resetPassword);
  const [banner, setBanner] = useState<string | null>(null);

  const form = useForm<ResetPasswordValues>({
    resolver: zodResolver(ResetPasswordSchema),
    defaultValues: {
      email: typeof params.email === 'string' ? params.email : '',
      code: '',
      new_password: '',
      confirm_password: '',
    },
  });

  const onSubmit = async (values: ResetPasswordValues): Promise<void> => {
    setBanner(null);
    try {
      await resetPassword({
        email: values.email,
        code: values.code,
        new_password: values.new_password,
      });
      toast.success('Password reset — please log in.');
      router.replace('/login');
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
          form.setError(fe.field as keyof ResetPasswordValues, {
            type: 'server',
            message: fe.message,
          });
        }
      }
    }
  };

  return (
    <View className="flex-1 items-center justify-center bg-neutral-50 p-6">
      <Card testID="reset-card" className="w-full max-w-md">
        <Text className="mb-6 text-center text-2xl font-bold text-neutral-900">
          Reset your password
        </Text>
        {banner ? (
          <View testID="reset-banner" className="mb-4 rounded-md bg-danger-600 p-3">
            <Text className="text-sm text-white">{banner}</Text>
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
                    testID="reset-email"
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
            name="code"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Code</FormLabel>
                <FormControl>
                  <Input
                    testID="reset-code"
                    inputMode="numeric"
                    maxLength={6}
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
            name="new_password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>New password</FormLabel>
                <FormControl>
                  <Input
                    testID="reset-new-password"
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
                <FormLabel>Confirm new password</FormLabel>
                <FormControl>
                  <Input
                    testID="reset-confirm-password"
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
            testID="reset-submit"
            onPress={form.handleSubmit(onSubmit)}
            loading={form.formState.isSubmitting}
            fullWidth
          >
            Reset password
          </Button>
        </Form>
      </Card>
    </View>
  );
}
