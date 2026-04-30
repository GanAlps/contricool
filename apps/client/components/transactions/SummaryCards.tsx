import { useMemo } from 'react';
import { Text, View } from 'react-native';

import { Card } from '~/components/ui/Card';
import { sumAmounts } from '~/lib/splits';
import type { TransactionListItem } from '~/lib/types';

type Props = {
  /** The requester's user_id, so we can identify their payer slot. */
  myUserId: string;
  /** Recent transactions used for the dashboard roll-up. */
  items: TransactionListItem[];
  currency: string;
  testID?: string;
};

/**
 * Dashboard summary cards (you owe / you're owed).
 *
 * The math here is **approximate** — a true cross-friend net would
 * require N pair-balance queries. For a glance card across the
 * recent-50 transactions, summing `my_owed_amount` gives a rough
 * "you owe" total: any transaction with my_owed_amount > 0 means I
 * still owe my share until either I paid it (a settlement) or the
 * payer settles up. Friend detail page is the precise source.
 */
export function SummaryCards({ myUserId, items, currency, testID }: Props) {
  const { youOwe, youAreOwed } = useMemo(() => {
    // Items in which I owe — the txn's payers don't include me, but
    // I'm a member with a positive owed_amount. Approximate with the
    // payload at hand (my_owed_amount > 0 + creator_id !== me).
    let owe = '0.00';
    let owed = '0.00';
    for (const t of items) {
      if (t.creator_id !== myUserId && Number(t.my_owed_amount) > 0) {
        owe = sumAmounts([owe, t.my_owed_amount]);
      } else if (t.creator_id === myUserId) {
        // I paid for this; rough proxy for "owed to me" = total minus my share.
        const total = Number(t.amount);
        const mine = Number(t.my_owed_amount);
        if (total > mine) {
          owed = sumAmounts([owed, (total - mine).toFixed(2)]);
        }
      }
    }
    return { youOwe: owe, youAreOwed: owed };
  }, [items, myUserId]);

  return (
    <View testID={testID ?? 'summary-cards'} className="mb-4 flex-row gap-3">
      <Card className="flex-1" testID="summary-you-owe">
        <Text className="text-xs uppercase tracking-wider text-neutral-500">You owe</Text>
        <Text className="mt-1 text-2xl font-bold text-neutral-900">
          {youOwe} <Text className="text-base font-medium">{currency}</Text>
        </Text>
      </Card>
      <Card className="flex-1" testID="summary-you-are-owed">
        <Text className="text-xs uppercase tracking-wider text-neutral-500">You're owed</Text>
        <Text className="mt-1 text-2xl font-bold text-neutral-900">
          {youAreOwed} <Text className="text-base font-medium">{currency}</Text>
        </Text>
      </Card>
    </View>
  );
}
