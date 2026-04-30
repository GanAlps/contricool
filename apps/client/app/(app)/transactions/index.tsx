import { useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';

import { AddTransactionSheet } from '~/components/transactions/AddTransactionSheet';
import { TransactionRow } from '~/components/transactions/TransactionRow';
import { Button } from '~/components/ui/Button';
import { Card } from '~/components/ui/Card';
import { Spinner } from '~/components/ui/Spinner';
import { useFriends } from '~/lib/queries/friends';
import { useTransactions } from '~/lib/queries/transactions';

const PAGE_LIMIT = 20;

export default function TransactionsListScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ friend_id?: string }>();
  const friendId = typeof params.friend_id === 'string' ? params.friend_id : null;

  const friends = useFriends();
  const [addOpen, setAddOpen] = useState(false);
  const txns = useTransactions({
    limit: PAGE_LIMIT,
    friend_id: friendId,
  });

  const friend = friendId ? friends.data?.items.find((f) => f.user_id === friendId) : null;

  return (
    <ScrollView className="flex-1 bg-neutral-50" contentContainerClassName="p-6">
      <View className="mb-4 flex-row items-center justify-between">
        <Text className="text-2xl font-bold text-neutral-900">Transactions</Text>
        <Button testID="txns-add" onPress={() => setAddOpen(true)}>
          Add transaction
        </Button>
      </View>

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerClassName="gap-2 pr-6"
        className="mb-4"
        testID="txns-filter-chips"
      >
        <FilterChip
          testID="filter-chip-all"
          label="All"
          active={!friendId}
          onPress={() => router.replace('/transactions')}
        />
        {(friends.data?.items ?? []).map((f) => {
          const active = friendId === f.user_id;
          return (
            <FilterChip
              key={f.user_id}
              testID={`filter-chip-friend-${f.user_id}`}
              label={f.name}
              active={active}
              onPress={() =>
                router.replace(active ? '/transactions' : `/transactions?friend_id=${f.user_id}`)
              }
            />
          );
        })}
      </ScrollView>

      {txns.isLoading ? (
        <View className="items-center py-8">
          <Spinner testID="txns-spinner" size="large" />
        </View>
      ) : (txns.data?.items ?? []).length === 0 ? (
        <Card testID="txns-empty">
          <Text className="mb-4 text-center text-base text-neutral-700">
            No transactions {friend ? `with ${friend.name}` : 'yet'}.
          </Text>
          <Button testID="txns-empty-add" onPress={() => setAddOpen(true)} fullWidth>
            Add transaction
          </Button>
        </Card>
      ) : (
        <View testID="txns-list" className="gap-2">
          {(txns.data?.items ?? []).map((item) => (
            <TransactionRow
              key={item.txn_id}
              item={item}
              onPress={() => router.push(`/transactions/${item.txn_id}`)}
            />
          ))}
        </View>
      )}

      <AddTransactionSheet
        open={addOpen}
        onClose={() => setAddOpen(false)}
        prefillFriendId={friendId ?? undefined}
      />
    </ScrollView>
  );
}

function FilterChip({
  label,
  active,
  onPress,
  testID,
}: {
  label: string;
  active: boolean;
  onPress: () => void;
  testID: string;
}) {
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      className={
        active
          ? 'rounded-full bg-primary-600 px-4 py-1.5'
          : 'rounded-full border border-neutral-300 bg-white px-4 py-1.5 active:bg-neutral-100'
      }
    >
      <Text className={active ? 'text-sm font-medium text-white' : 'text-sm text-neutral-700'}>
        {label}
      </Text>
    </Pressable>
  );
}
