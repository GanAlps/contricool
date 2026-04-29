import { useLocalSearchParams, useRouter } from 'expo-router';
import { useMemo, useState } from 'react';
import { Text, View } from 'react-native';

import { Button } from '~/components/ui/Button';
import { Card } from '~/components/ui/Card';
import { Sheet } from '~/components/ui/Sheet';
import { Spinner } from '~/components/ui/Spinner';
import { toast } from '~/components/ui/Toaster';
import { ApiErrorException } from '~/lib/api';
import { useFriendBalance, useFriends, useRemoveFriend } from '~/lib/queries/friends';
import type { FriendItem } from '~/lib/types';

function isApiError(err: unknown): err is ApiErrorException {
  return err instanceof ApiErrorException;
}

export default function FriendDetailScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ userId: string }>();
  const userId = typeof params.userId === 'string' ? params.userId : '';

  const friendsList = useFriends();
  const balance = useFriendBalance(userId);
  const remove = useRemoveFriend();
  const [confirmOpen, setConfirmOpen] = useState(false);

  const friend = useMemo<FriendItem | undefined>(
    () => friendsList.data?.items.find((f) => f.user_id === userId),
    [friendsList.data, userId],
  );

  const balanceErr = balance.error instanceof ApiErrorException ? balance.error.error : null;
  if (balanceErr?.code === 'USER_NOT_FOUND') {
    return <NotFriendsState onBack={() => router.replace('/friends')} />;
  }

  const onConfirmRemove = async (): Promise<void> => {
    setConfirmOpen(false);
    try {
      await remove.mutateAsync(userId);
      toast.success(`Removed ${friend?.name ?? 'friend'}`);
      router.back();
    } catch (err) {
      if (isApiError(err) && err.error.code === 'USER_NOT_FOUND') {
        toast.info('Already removed');
        router.back();
        return;
      }
      toast.error('Could not remove friend. Please try again.');
    }
  };

  return (
    <View className="flex-1 bg-neutral-50 p-6">
      <Card testID="friend-detail">
        <Text className="mb-1 text-2xl font-bold text-neutral-900">{friend?.name ?? '—'}</Text>
        <Text testID="friend-detail-currency" className="mb-4 text-xs text-neutral-500">
          {friend?.currency ?? '—'}
        </Text>

        {balance.isLoading ? (
          <View className="items-center py-6">
            <Spinner testID="friend-detail-spinner" size="small" />
          </View>
        ) : (
          <View className="items-center rounded-md bg-neutral-100 p-6">
            <Text className="text-base font-semibold text-neutral-900">Settled</Text>
            <Text testID="friend-detail-balance" className="mt-1 text-sm text-neutral-700">
              0.00 {balance.data?.currency ?? friend?.currency ?? '—'}
            </Text>
            <Text className="mt-2 text-xs text-neutral-500">last activity: —</Text>
          </View>
        )}

        <View className="mt-4 gap-2">
          <Button testID="friend-settle-up" disabled>
            Settle up (coming soon)
          </Button>
          <Button
            testID="friend-remove"
            variant="destructive"
            onPress={() => setConfirmOpen(true)}
            loading={remove.isPending}
          >
            Remove friend
          </Button>
        </View>
      </Card>

      <Sheet
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title="Remove friend?"
        testID="confirm-remove"
      >
        <Text className="mb-4 text-sm text-neutral-700">
          You will no longer share expenses with {friend?.name ?? 'this friend'}.
        </Text>
        <View className="flex-row justify-end gap-2">
          <Button
            testID="confirm-remove-cancel"
            variant="secondary"
            onPress={() => setConfirmOpen(false)}
          >
            Cancel
          </Button>
          <Button testID="confirm-remove-confirm" variant="destructive" onPress={onConfirmRemove}>
            Remove
          </Button>
        </View>
      </Sheet>
    </View>
  );
}

function NotFriendsState({ onBack }: { onBack: () => void }) {
  return (
    <View className="flex-1 items-center justify-center bg-neutral-50 p-6">
      <Card testID="friend-not-found">
        <Text className="mb-4 text-center text-base text-neutral-800">
          This friend doesn't exist or you're no longer friends.
        </Text>
        <Button testID="friend-not-found-back" onPress={onBack} fullWidth>
          Back to friends list
        </Button>
      </Card>
    </View>
  );
}
