import { Pressable, Text, View } from 'react-native';

import type { TransactionListItem } from '~/lib/types';

type Props = {
  item: TransactionListItem;
  /** ULID of the requester so we can render "you" when they paid. */
  myUserId?: string | null;
  /** Map of user_id → display name (friends + self). Optional;
   * unresolved ids fall back to a short suffix of the ULID. */
  nameByUserId?: Record<string, string>;
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
 *
 * `payer_user_ids` is also surfaced as a "Paid by …" hint so the
 * user can scan who covered an expense without opening detail. We
 * lean on the existing friends + auth caches for name resolution
 * (no extra round-trip), and collapse to "Multiple" once we cross
 * two payers because the row's horizontal budget runs out fast on
 * a phone width.
 */
export function TransactionRow({ item, myUserId, nameByUserId, onPress, testID }: Props) {
  const owed = Number(item.my_owed_amount);
  const owedLabel =
    owed > 0 ? `you owe ${formatCurrency(item.my_owed_amount, item.currency)}` : 'no share';
  const paidLabel = formatPaidBy(item.payer_user_ids, myUserId, nameByUserId);
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
        {paidLabel ? (
          <Text
            testID={`${testID ?? `txn-row-${item.txn_id}`}-paid-by`}
            className="text-xs text-neutral-500"
          >
            {paidLabel}
          </Text>
        ) : null}
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

function formatPaidBy(
  payerUserIds: readonly string[] | undefined,
  myUserId?: string | null,
  nameByUserId?: Record<string, string>,
): string | null {
  // The SDK types mark `payer_user_ids` as required, but the deployed
  // dev/prod API only starts returning it after the backend redeploy
  // that ships with this change. Until that lands, `undefined` is a
  // valid runtime shape — handle it as "no payer hint" instead of
  // crashing the whole list with `undefined.length`.
  if (!payerUserIds || payerUserIds.length === 0) {
    return null;
  }
  if (payerUserIds.length > 1) {
    return 'Paid by Multiple';
  }
  const only = payerUserIds[0];
  if (!only) {
    return null;
  }
  if (myUserId && only === myUserId) {
    return 'Paid by you';
  }
  const name = nameByUserId?.[only];
  if (name) {
    return `Paid by ${name}`;
  }
  // Unknown payer (rare — would mean a non-friend ex-member who has
  // since been unfriended). Show a short suffix of the ULID instead
  // of an empty label so the row never silently drops information.
  return `Paid by ${only.slice(-4)}`;
}
