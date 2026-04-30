import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { CommentList } from '~/components/transactions/CommentList';
import { useAuthStore } from '~/lib/auth-store';

import { server } from '../../msw-handlers';
import { withProviders } from '../../test-utils';

const BASE = 'http://localhost/v1';
const ME = '01J0000000000000000000ME0';
const FRIEND = '01J0000000000000000000FRD';
const TXN = '01J0000000000000000000TX1';

beforeEach(() => {
  useAuthStore.setState({
    user: { user_id: ME, name: 'Me', currency: 'USD' },
    accessToken: 'a',
    idToken: 'i',
    loading: false,
  });
});
afterEach(() => {
  useAuthStore.getState()._clear();
});

describe('CommentList', () => {
  it('renders user + system comments with distinct labels', async () => {
    server.use(
      http.get(`${BASE}/transactions/${TXN}/comments`, async () =>
        HttpResponse.json({
          items: [
            {
              comment_id: 'c1',
              txn_id: TXN,
              author_id: FRIEND,
              body: 'Thanks!',
              kind: 'user',
              created_at: '2026-04-29T20:00:00Z',
            },
            {
              comment_id: 'c2',
              txn_id: TXN,
              author_id: 'system',
              body: 'Updated transaction:\n- amount: 10.00 → 12.00',
              kind: 'system',
              created_at: '2026-04-29T20:01:00Z',
            },
          ],
          next_cursor: null,
        }),
      ),
    );

    render(
      withProviders(
        <CommentList txnId={TXN} memberIds={[ME, FRIEND]} nameByUserId={{ [FRIEND]: 'Bob' }} />,
      ),
    );

    await waitFor(() => {
      expect(screen.getByText('Thanks!')).toBeInTheDocument();
    });
    expect(screen.getByText('Bob')).toBeInTheDocument();
    expect(screen.getByText('System')).toBeInTheDocument();
    expect(screen.getByText(/Updated transaction/)).toBeInTheDocument();
  });

  it('hides composer for non-members', async () => {
    server.use(
      http.get(`${BASE}/transactions/${TXN}/comments`, async () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
    );
    render(
      withProviders(
        <CommentList
          txnId={TXN}
          // ME is NOT in memberIds — non-member view.
          memberIds={[FRIEND]}
          nameByUserId={{}}
        />,
      ),
    );
    await waitFor(() => {
      expect(screen.getByTestId('txn-comments-empty')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('txn-comment-input')).toBeNull();
  });

  it('posts a comment and clears the input on success', async () => {
    server.use(
      http.get(`${BASE}/transactions/${TXN}/comments`, async () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
      http.post(`${BASE}/transactions/${TXN}/comments`, async ({ request }) => {
        const body = (await request.json()) as { body: string };
        return HttpResponse.json(
          {
            comment_id: 'c-new',
            txn_id: TXN,
            author_id: ME,
            body: body.body,
            kind: 'user',
            created_at: '2026-04-29T20:02:00Z',
          },
          { status: 201 },
        );
      }),
    );
    render(
      withProviders(
        <CommentList txnId={TXN} memberIds={[ME, FRIEND]} nameByUserId={{ [ME]: 'Me' }} />,
      ),
    );
    await waitFor(() => {
      expect(screen.getByTestId('txn-comments-empty')).toBeInTheDocument();
    });
    const input = screen.getByTestId('txn-comment-input');
    fireEvent.change(input, { target: { value: 'Hi all!' } });
    fireEvent.click(screen.getByTestId('txn-comment-post'));
    await waitFor(() => {
      expect((screen.getByTestId('txn-comment-input') as HTMLInputElement).value).toBe('');
    });
  });
});
