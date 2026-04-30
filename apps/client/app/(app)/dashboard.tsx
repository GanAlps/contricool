import { useRouter } from 'expo-router';
import { useState } from 'react';
import { ScrollView, Text, View } from 'react-native';

import { AddTransactionSheet } from '~/components/transactions/AddTransactionSheet';
import { SummaryCards } from '~/components/transactions/SummaryCards';
import { TransactionRow } from '~/components/transactions/TransactionRow';
import { Button } from '~/components/ui/Button';
import { Card } from '~/components/ui/Card';
import { Spinner } from '~/components/ui/Spinner';
import { useAuthStore } from '~/lib/auth-store';
import { useTransactions } from '~/lib/queries/transactions';

const RECENT_LIMIT = 10;

export default function DashboardScreen() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const [addOpen, setAddOpen] = useState(false);
  const txns = useTransactions({ limit: RECENT_LIMIT });

  const items = txns.data?.items ?? [];

  return (
    <ScrollView className="flex-1 bg-neutral-50" contentContainerClassName="p-6">
      <View className="mb-4 flex-row items-center justify-between">
        <View>
          <Text className="text-2xl font-bold text-neutral-900">
            Welcome, {user?.name ?? 'friend'}
          </Text>
          <Text testID="dashboard-currency" className="text-sm text-neutral-500">
            Currency: {user?.currency ?? '—'}
          </Text>
        </View>
        <Button testID="dashboard-add-txn" onPress={() => setAddOpen(true)}>
          Add transaction
        </Button>
      </View>

      <SummaryCards items={items} currency={user?.currency ?? 'USD'} />

      <Text className="mb-2 text-base font-semibold text-neutral-900">Recent activity</Text>
      {txns.isLoading ? (
        <View className="items-center py-8">
          <Spinner testID="dashboard-spinner" size="large" />
        </View>
      ) : items.length === 0 ? (
        <Card testID="dashboard-empty">
          <Text className="mb-4 text-center text-base text-neutral-700">
            No transactions yet — record your first one to get started.
          </Text>
          <Button testID="dashboard-empty-add" onPress={() => setAddOpen(true)} fullWidth>
            Add transaction
          </Button>
        </Card>
      ) : (
        <View testID="dashboard-list" className="gap-2">
          {items.map((item) => (
            <TransactionRow
              key={item.txn_id}
              item={item}
              onPress={() => router.push(`/transactions/${item.txn_id}`)}
            />
          ))}
        </View>
      )}

      <AddTransactionSheet open={addOpen} onClose={() => setAddOpen(false)} />
    </ScrollView>
  );
}
