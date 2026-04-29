import { zodResolver } from '@hookform/resolvers/zod';
import { useRouter } from 'expo-router';
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
import { ForgotPasswordSchema, type ForgotPasswordValues } from '~/lib/schemas';

export default function ForgotPasswordScreen() {
  const router = useRouter();
  const forgotPassword = useAuthStore((s) => s.forgotPassword);

  const form = useForm<ForgotPasswordValues>({
    resolver: zodResolver(ForgotPasswordSchema),
    defaultValues: { email: '' },
  });

  const onSubmit = async (values: ForgotPasswordValues): Promise<void> => {
    try {
      await forgotPassword(values);
    } catch (e) {
      if (e instanceof ApiErrorException) {
        const mapped = mapApiError(e.error);
        if (mapped.kind === 'toast') {
          toast.error(mapped.message);
          return;
        }
      }
      // Otherwise fall through — the backend always returns 202 to avoid
      // leaking account existence; we proceed regardless.
    }
    toast.success('If the email exists, a reset code has been sent.');
    router.replace({ pathname: '/reset-password', params: { email: values.email } });
  };

  return (
    <View className="flex-1 items-center justify-center bg-neutral-50 p-6">
      <Card testID="forgot-card" className="w-full max-w-md">
        <Text className="mb-2 text-center text-2xl font-bold text-neutral-900">
          Forgot your password?
        </Text>
        <Text className="mb-6 text-center text-sm text-neutral-700">
          Enter your email and we'll send you a reset code.
        </Text>
        <Form form={form}>
          <FormField
            control={form.control}
            name="email"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Email</FormLabel>
                <FormControl>
                  <Input
                    testID="forgot-email"
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
          <Button
            testID="forgot-submit"
            onPress={form.handleSubmit(onSubmit)}
            loading={form.formState.isSubmitting}
            fullWidth
          >
            Send reset code
          </Button>
        </Form>
      </Card>
    </View>
  );
}
