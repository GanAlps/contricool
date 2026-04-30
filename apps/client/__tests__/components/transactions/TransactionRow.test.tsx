import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { TransactionRow } from '~/components/transactions/TransactionRow';
import type { TransactionListItem } from '~/lib/types';

const baseItem: TransactionListItem = {
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
  created_at: '2026-04-29T20:00:00Z',
};

describe('TransactionRow', () => {
  it('renders name + amount + owed share for expenses', () => {
    render(<TransactionRow item={baseItem} />);
    expect(screen.getByText('Dinner')).toBeInTheDocument();
    expect(screen.getByText('30.00 USD')).toBeInTheDocument();
    expect(screen.getByText('you owe 10.00 USD')).toBeInTheDocument();
    expect(screen.getByText(/Expense/)).toBeInTheDocument();
  });

  it('renders "no share" when my_owed_amount is zero', () => {
    render(<TransactionRow item={{ ...baseItem, my_owed_amount: '0.00' }} />);
    expect(screen.getByText('no share')).toBeInTheDocument();
  });

  it('labels settlements distinctly', () => {
    render(<TransactionRow item={{ ...baseItem, type: 'settlement' }} />);
    expect(screen.getByText(/Settlement/)).toBeInTheDocument();
  });
});
