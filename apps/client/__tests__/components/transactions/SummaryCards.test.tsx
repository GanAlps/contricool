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
    created_at: '2026-04-29T20:00:00Z',
    ...over,
  };
}

const ME = '01J0000000000000000000ME0';
const OTHER = '01J0000000000000000000OTH';

describe('SummaryCards', () => {
  it('shows zeros when no transactions', () => {
    render(<SummaryCards myUserId={ME} items={[]} currency="USD" />);
    expect(screen.getByTestId('summary-you-owe')).toHaveTextContent('0.00');
    expect(screen.getByTestId('summary-you-are-owed')).toHaveTextContent('0.00');
  });

  it('aggregates owed when other paid', () => {
    render(
      <SummaryCards
        myUserId={ME}
        items={[
          txn({ creator_id: OTHER, my_owed_amount: '7.50' }),
          txn({ txn_id: '01J0000000000000000000TX2', creator_id: OTHER, my_owed_amount: '3.50' }),
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
        myUserId={ME}
        items={[txn({ creator_id: ME, amount: '30.00', my_owed_amount: '10.00' })]}
        currency="USD"
      />,
    );
    // Roll-up: total - my share = 20.00 owed to me.
    expect(screen.getByTestId('summary-you-are-owed')).toHaveTextContent('20.00');
  });
});
