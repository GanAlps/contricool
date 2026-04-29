import { useRouter } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { AddFriendSheet } from '~/components/friends/AddFriendSheet';
import { Button } from '~/components/ui/Button';
import { Card } from '~/components/ui/Card';
import { Spinner } from '~/components/ui/Spinner';
import { toast } from '~/components/ui/Toaster';
import { ApiErrorException } from '~/lib/api';
import { mapApiError } from '~/lib/error-mapping';
import { useFriends } from '~/lib/queries/friends';
import type { FriendItem } from '~/lib/types';

function compareByName(a: FriendItem, b: FriendItem): number {
  return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
}

export default function FriendsListScreen() {
  const router = useRouter();
  const friendsQuery = useFriends();
  const [modalOpen, setModalOpen] = useState(false);

  const items = useMemo<FriendItem[]>(() => {
    if (!friendsQuery.data) return [];
    return [...friendsQuery.data.items].sort(compareByName);
  }, [friendsQuery.data]);

  if (friendsQuery.isLoading) {
    return (
      <View className="flex-1 items-center justify-center bg-neutral-50">
        <Spinner size="large" testID="friends-spinner" />
      </View>
    );
  }

  if (friendsQuery.error) {
    return <FriendsErrorState error={friendsQuery.error} onRetry={() => friendsQuery.refetch()} />;
  }

  return (
    <View className="flex-1 bg-neutral-50 p-6">
      <View className="mb-4 flex-row items-center justify-between">
        <Text className="text-2xl font-bold text-neutral-900">Friends</Text>
        <Button testID="friends-add-cta" onPress={() => setModalOpen(true)}>
          Add friend
        </Button>
      </View>

      {items.length === 0 ? (
        <Card testID="friends-empty">
          <Text className="mb-4 text-center text-base text-neutral-700">
            No friends yet — add one to start tracking expenses.
          </Text>
          <Button testID="friends-empty-add-cta" onPress={() => setModalOpen(true)} fullWidth>
            Add friend
          </Button>
        </Card>
      ) : (
        <View testID="friends-list" className="gap-2">
          {items.map((f) => (
            <Pressable
              key={f.user_id}
              testID={`friend-row-${f.user_id}`}
              onPress={() => router.push(`/friends/${f.user_id}`)}
              className="flex-row items-center justify-between rounded-md border border-neutral-200 bg-white p-4 active:bg-neutral-100"
            >
              <View>
                <Text className="text-base font-medium text-neutral-900">{f.name}</Text>
                <Text className="text-xs text-neutral-500">{f.currency}</Text>
              </View>
              <Text className="text-sm text-neutral-700">Settled</Text>
            </Pressable>
          ))}
        </View>
      )}

      <AddFriendSheet
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onAdded={(name) => {
          setModalOpen(false);
          toast.success(`Added ${name}`);
        }}
      />
    </View>
  );
}

function FriendsErrorState({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry: () => void;
}) {
  const apiErr = error instanceof ApiErrorException ? error.error : null;
  const screenErr = apiErr ? mapApiError(apiErr) : null;

  useEffect(() => {
    if (screenErr?.kind === 'toast') {
      toast.error(screenErr.message);
    }
  }, [screenErr]);

  const banner = screenErr?.kind === 'banner' ? screenErr.message : 'Could not load friends.';
  return (
    <View className="flex-1 items-center justify-center bg-neutral-50 p-6">
      <Card testID="friends-error">
        <Text className="mb-4 text-center text-base text-neutral-800">{banner}</Text>
        <Button testID="friends-retry" onPress={onRetry} fullWidth>
          Retry
        </Button>
      </Card>
    </View>
  );
}
