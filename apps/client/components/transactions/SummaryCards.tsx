import { useMemo } from 'react';
import { Text, View } from 'react-native';

import { Card } from '~/components/ui/Card';
import { sumAmounts } from '~/lib/splits';
import type { TransactionListItem } from '~/lib/types';

type Props = {
  /** Recent transactions used for the dashboard roll-up. */
  items: TransactionListItem[];
  currency: string;
  testID?: string;
};

/**
 * Dashboard summary cards (you owe / you're owed).
 *
 * Per-transaction net = my_paid_amount - my_owed_amount.
 *  - net > 0 → I'm owed for this transaction by ``net``.
 *  - net < 0 → I owe ``|net|`` for this transaction.
 *
 * Summed across the recent-list, the cards reflect every transaction
 * direction faithfully. ``creator_id`` is intentionally NOT consulted:
 * who *logged* a transaction is unrelated to who paid for it (a user
 * can record a friend's payment), so the prior implementation that
 * keyed on ``creator_id`` produced wrong numbers when a friend was the
 * payer.
 */
export function SummaryCards({ items, currency, testID }: Props) {
  const { youOwe, youAreOwed } = useMemo(() => {
    let owe = '0.00';
    let owed = '0.00';
    for (const t of items) {
      const paid = Number(t.my_paid_amount ?? 0);
      const owedAmt = Number(t.my_owed_amount ?? 0);
      const net = paid - owedAmt;
      if (net > 0) {
        owed = sumAmounts([owed, net.toFixed(2)]);
      } else if (net < 0) {
        owe = sumAmounts([owe, Math.abs(net).toFixed(2)]);
      }
    }
    return { youOwe: owe, youAreOwed: owed };
  }, [items]);

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
