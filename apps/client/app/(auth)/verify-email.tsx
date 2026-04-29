import { zodResolver } from '@hookform/resolvers/zod';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
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
import { VerifyEmailSchema, type VerifyEmailValues } from '~/lib/schemas';

const FRIENDLY = {
  INVALID_CODE: 'Code is wrong or expired. Try again or request a new one.',
  USER_NOT_FOUND: "We can't find that account.",
} as const;

const RESEND_COOLDOWN_MS = 30_000;

export default function VerifyEmailScreen() {
  const params = useLocalSearchParams<{ email?: string }>();
  const router = useRouter();
  const verifyEmail = useAuthStore((s) => s.verifyEmail);
  const resendEmailCode = useAuthStore((s) => s.resendEmailCode);
  const [banner, setBanner] = useState<string | null>(null);
  const [cooldownUntil, setCooldownUntil] = useState<number>(0);
  const [, force] = useState(0);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const form = useForm<VerifyEmailValues>({
    resolver: zodResolver(VerifyEmailSchema),
    defaultValues: {
      email: typeof params.email === 'string' ? params.email : '',
      code: '',
    },
  });

  useEffect(() => {
    if (cooldownUntil > Date.now()) {
      tickRef.current = setInterval(() => force((n) => n + 1), 500);
      return () => {
        if (tickRef.current) clearInterval(tickRef.current);
      };
    }
    return undefined;
  }, [cooldownUntil]);

  const cooldownRemaining = Math.max(0, cooldownUntil - Date.now());

  const onSubmit = async (values: VerifyEmailValues): Promise<void> => {
    setBanner(null);
    try {
      await verifyEmail(values);
      toast.success('Email verified — please log in.');
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
      }
    }
  };

  const onResend = async (): Promise<void> => {
    setCooldownUntil(Date.now() + RESEND_COOLDOWN_MS);
    try {
      await resendEmailCode({ email: form.getValues('email') });
      toast.success('A new code is on its way.');
    } catch (e) {
      if (e instanceof ApiErrorException) {
        const mapped = mapApiError(e.error);
        if (mapped.kind === 'toast') {
          toast.error(mapped.message);
        } else if (mapped.kind === 'banner') {
          setBanner(mapped.message);
        }
      }
    }
  };

  return (
    <View className="flex-1 items-center justify-center bg-neutral-50 p-6">
      <Card testID="verify-card" className="w-full max-w-md">
        <Text className="mb-2 text-center text-2xl font-bold text-neutral-900">
          Verify your email
        </Text>
        <Text className="mb-6 text-center text-sm text-neutral-700">
          Enter the 6-digit code we sent to your inbox.
        </Text>
        {banner ? (
          <View testID="verify-banner" className="mb-4 rounded-md bg-danger-600 p-3">
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
                    testID="verify-email"
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
                    testID="verify-code"
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
          <Button
            testID="verify-submit"
            onPress={form.handleSubmit(onSubmit)}
            loading={form.formState.isSubmitting}
            fullWidth
          >
            Verify email
          </Button>
        </Form>
        <View className="mt-4">
          <Button
            testID="verify-resend"
            onPress={onResend}
            disabled={cooldownRemaining > 0}
            variant="ghost"
            fullWidth
          >
            {cooldownRemaining > 0
              ? `Resend code in ${Math.ceil(cooldownRemaining / 1000)}s`
              : 'Resend code'}
          </Button>
        </View>
      </Card>
    </View>
  );
}
