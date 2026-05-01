import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { SummaryCards } from '~/components/transactions/SummaryCards';
import type { TransactionListItem } from '~/lib/types';

function txn(over: Partial<TransactionListItem>): TransactionListItem {
  return {
    txn_id: '01J0000000000000000000TX1',
    name: 'Dinner',
    type: 'expense',
    amount: '30.00',
    currency: 'USD',
    txn_date: '2026-04-29',
    split_method: 'equal',
    creator_id: '01J0000000000000000000ALI',
    my_owed_amount: '10.00',
    my_paid_amount: '0.00',
    payer_user_ids: ['01J0000000000000000000ALI'],
    created_at: '2026-04-29T20:00:00Z',
    ...over,
  };
}

describe('SummaryCards', () => {
  it('shows zeros when no transactions', () => {
    render(<SummaryCards items={[]} currency="USD" />);
    expect(screen.getByTestId('summary-you-owe')).toHaveTextContent('0.00');
    expect(screen.getByTestId('summary-you-are-owed')).toHaveTextContent('0.00');
  });

  it('aggregates "you owe" when friend paid (regression: Phase 7b dashboard fix)', () => {
    // Friend paid 30 with equal 3-way split — I owe 10. Even though
    // I might be the creator (logged the transaction on their behalf),
    // the cards must reflect that I OWE 10, not that I'm OWED 20.
    render(
      <SummaryCards
        items={[
          txn({ my_paid_amount: '0.00', my_owed_amount: '7.50' }),
          txn({
            txn_id: '01J0000000000000000000TX2',
            my_paid_amount: '0.00',
            my_owed_amount: '3.50',
          }),
        ]}
        currency="USD"
      />,
    );
    expect(screen.getByTestId('summary-you-owe')).toHaveTextContent('11.00');
    expect(screen.getByTestId('summary-you-are-owed')).toHaveTextContent('0.00');
  });

  it('aggregates owed-to-me when I paid', () => {
    render(
      <SummaryCards
        items={[txn({ amount: '30.00', my_paid_amount: '30.00', my_owed_amount: '10.00' })]}
        currency="USD"
      />,
    );
    // Net = 30 - 10 = 20 owed to me.
    expect(screen.getByTestId('summary-you-are-owed')).toHaveTextContent('20.00');
  });

  it('regression: creator who is not a payer does NOT inflate "you are owed"', () => {
    // Friend paid (so my_paid = 0, my_owed > 0) but I happen to be
    // creator_id. Old logic: incremented owed by (amount - my_owed).
    // New logic: my_paid - my_owed = -my_owed → adds to "you owe".
    render(
      <SummaryCards
        items={[
          txn({
            creator_id: '01J0000000000000000000ME0',
            my_paid_amount: '0.00',
            my_owed_amount: '100.00',
            amount: '100.00',
          }),
        ]}
        currency="USD"
      />,
    );
    expect(screen.getByTestId('summary-you-owe')).toHaveTextContent('100.00');
    expect(screen.getByTestId('summary-you-are-owed')).toHaveTextContent('0.00');
  });
});
