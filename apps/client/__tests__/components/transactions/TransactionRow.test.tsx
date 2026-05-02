import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { TransactionRow } from '~/components/transactions/TransactionRow';
import type { TransactionListItem } from '~/lib/types';

const ME = '01J0000000000000000000ME0';
const FRIEND_A = '01J0000000000000000000ALI';
const FRIEND_B = '01J0000000000000000000BOB';

const baseItem: TransactionListItem = {
  txn_id: '01J0000000000000000000TX1',
  name: 'Dinner',
  type: 'expense',
  amount: '30.00',
  currency: 'USD',
  txn_date: '2026-04-29',
  split_method: 'equal',
  creator_id: FRIEND_A,
  my_owed_amount: '10.00',
  my_paid_amount: '0.00',
  payer_user_ids: [FRIEND_A],
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

  it('renders "Paid by you" when the requester is the sole payer', () => {
    render(<TransactionRow item={{ ...baseItem, payer_user_ids: [ME] }} myUserId={ME} />);
    expect(screen.getByText('Paid by you')).toBeInTheDocument();
  });

  it('renders "Paid by <name>" for a single non-self payer when the name is known', () => {
    render(
      <TransactionRow
        item={{ ...baseItem, payer_user_ids: [FRIEND_A] }}
        myUserId={ME}
        nameByUserId={{ [FRIEND_A]: 'Alice' }}
      />,
    );
    expect(screen.getByText('Paid by Alice')).toBeInTheDocument();
  });

  it('renders "Paid by Multiple" when more than one payer is recorded', () => {
    render(
      <TransactionRow
        item={{ ...baseItem, payer_user_ids: [ME, FRIEND_B] }}
        myUserId={ME}
        nameByUserId={{ [ME]: 'Me', [FRIEND_B]: 'Bob' }}
      />,
    );
    expect(screen.getByText('Paid by Multiple')).toBeInTheDocument();
  });

  it('falls back to a short ULID suffix when the payer name is unresolvable', () => {
    render(
      <TransactionRow
        item={{ ...baseItem, payer_user_ids: ['01J00000000000000000000XYZ'] }}
        myUserId={ME}
        nameByUserId={{}}
      />,
    );
    expect(screen.getByText(/Paid by 0XYZ$/)).toBeInTheDocument();
  });
});
