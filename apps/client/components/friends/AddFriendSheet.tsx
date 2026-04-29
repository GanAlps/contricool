import { useEffect } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { Text, TextInput, View } from 'react-native';

import { zodResolver } from '@hookform/resolvers/zod';

import { Button } from '~/components/ui/Button';
import { Sheet } from '~/components/ui/Sheet';
import { toast } from '~/components/ui/Toaster';
import { ApiErrorException } from '~/lib/api';
import type { ApiError } from '~/lib/api';
import { useAddFriend } from '~/lib/queries/friends';
import { AddFriendSchema, type AddFriendValues } from '~/lib/schemas';

type Props = {
  open: boolean;
  onClose: () => void;
  onAdded: (name: string) => void;
};

const FRIENDLY_FIELD: Record<string, string> = {
  INVALID_IDENTIFIER: "Friends are added by email only — phones aren't supported yet.",
  USER_NOT_FOUND: "We couldn't find anyone with that email.",
  CONFLICT: "You're already friends.",
  SELF_ADD_FORBIDDEN: "You can't add yourself.",
};

function isApiError(err: unknown): err is ApiErrorException {
  return err instanceof ApiErrorException;
}

function pickValidationIssue(e: ApiError): string {
  const first = e.details[0];
  return first?.issue ?? 'Invalid input.';
}

export function AddFriendSheet({ open, onClose, onAdded }: Props) {
  const addFriend = useAddFriend();

  const {
    control,
    handleSubmit,
    setError,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<AddFriendValues>({
    resolver: zodResolver(AddFriendSchema),
    defaultValues: { email: '' },
    mode: 'onSubmit',
  });

  // Reset email + clear server errors whenever the sheet re-opens, so
  // a previous attempt's stale value/error doesn't leak across
  // open/close cycles (cancel-then-reopen, error-then-reopen).
  useEffect(() => {
    if (open) {
      reset({ email: '' });
    }
  }, [open, reset]);

  const submit = handleSubmit(async (values) => {
    try {
      const friend = await addFriend.mutateAsync({ email: values.email });
      reset({ email: '' });
      onAdded(friend.name);
    } catch (err) {
      if (!isApiError(err)) {
        toast.error('Something went wrong. Please try again.');
        return;
      }
      const code = err.error.code;
      const message = FRIENDLY_FIELD[code];
      if (message) {
        setError('email', { type: 'server', message });
        return;
      }
      if (code === 'VALIDATION_ERROR') {
        setError('email', { type: 'server', message: pickValidationIssue(err.error) });
        return;
      }
      if (code === 'RATE_LIMITED') {
        const wait = err.error.retry_after;
        toast.error(
          wait
            ? `Too many attempts — try again in ${wait} seconds.`
            : 'Too many attempts — please wait and try again.',
        );
        return;
      }
      toast.error('Something went wrong. Please try again.');
    }
  });

  return (
    <Sheet open={open} onClose={onClose} title="Add friend" testID="add-friend-sheet">
      <View className="gap-4">
        <View>
          <Text className="mb-1 text-sm text-neutral-700">Email</Text>
          <Controller
            control={control}
            name="email"
            render={({ field }) => (
              <TextInput
                testID="add-friend-email"
                value={field.value}
                onChangeText={field.onChange}
                onBlur={field.onBlur}
                autoCapitalize="none"
                autoCorrect={false}
                keyboardType="email-address"
                inputMode="email"
                placeholder="friend@example.com"
                className="h-10 rounded-md border border-neutral-300 px-3 text-base text-neutral-900"
              />
            )}
          />
          {errors.email ? (
            <Text testID="add-friend-error" className="mt-1 text-sm text-danger-600">
              {errors.email.message}
            </Text>
          ) : null}
        </View>

        <View className="flex-row justify-end gap-2">
          <Button testID="add-friend-cancel" variant="secondary" onPress={onClose}>
            Cancel
          </Button>
          <Button
            testID="add-friend-submit"
            onPress={submit}
            loading={isSubmitting || addFriend.isPending}
          >
            Add friend
          </Button>
        </View>
      </View>
    </Sheet>
  );
}
