import { Pressable, Text, View } from 'react-native';

import type { TransactionListItem } from '~/lib/types';

type Props = {
  item: TransactionListItem;
  onPress?: () => void;
  testID?: string;
};

/**
 * One row in a transactions list. Shared between the dashboard's
 * "recent activity" stripe and the full transactions list page.
 *
 * `my_owed_amount` is the share the requester owes for this txn,
 * pre-computed by the backend. It's rendered as the secondary
 * line so the user can see "I owe X" at a glance.
 */
export function TransactionRow({ item, onPress, testID }: Props) {
  const owed = Number(item.my_owed_amount);
  const owedLabel =
    owed > 0 ? `you owe ${formatCurrency(item.my_owed_amount, item.currency)}` : 'no share';
  return (
    <Pressable
      testID={testID ?? `txn-row-${item.txn_id}`}
      onPress={onPress}
      className="flex-row items-center justify-between rounded-md border border-neutral-200 bg-white p-4 active:bg-neutral-100"
    >
      <View className="flex-1 pr-4">
        <Text className="text-base font-medium text-neutral-900" numberOfLines={1}>
          {item.name}
        </Text>
        <Text className="text-xs text-neutral-500">
          {item.txn_date} · {labelForType(item.type)}
        </Text>
      </View>
      <View className="items-end">
        <Text className="text-base font-semibold text-neutral-900">
          {formatCurrency(item.amount, item.currency)}
        </Text>
        <Text className="text-xs text-neutral-500">{owedLabel}</Text>
      </View>
    </Pressable>
  );
}

function formatCurrency(amount: string, currency: string): string {
  return `${amount} ${currency}`;
}

function labelForType(t: string): string {
  return t === 'settlement' ? 'Settlement' : 'Expense';
}
