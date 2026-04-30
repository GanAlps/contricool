/**
 * TanStack Query hooks for the transactions feature.
 *
 * Mirrors the friends-feature hook layout. The
 * ``Idempotency-Key`` header on POST is supplied by the caller —
 * the form module owns the lifetime so a transient network retry
 * sends the same key (and the server returns the cached response
 * rather than creating a duplicate).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '~/lib/api';
import { friendsKeys } from '~/lib/queries/friends';
import type { CreateTransactionRequest, ListTransactionsResponse, Transaction } from '~/lib/types';

export const transactionsKeys = {
  all: ['transactions'] as const,
  list: (q: ListTransactionsArgs) => ['transactions', q] as const,
  one: (txnId: string) => ['transaction', txnId] as const,
};

const DEFAULT_LIST_LIMIT = 20;

export type ListTransactionsArgs = {
  limit?: number;
  cursor?: string | null;
  friend_id?: string | null;
};

export function useTransactions(args: ListTransactionsArgs = {}) {
  const limit = args.limit ?? DEFAULT_LIST_LIMIT;
  const cursor = args.cursor ?? undefined;
  const friend_id = args.friend_id ?? undefined;
  return useQuery<ListTransactionsResponse>({
    queryKey: transactionsKeys.list({ limit, cursor, friend_id }),
    queryFn: async () => {
      const r = await apiClient.GET('/transactions', {
        params: {
          query: {
            limit,
            ...(cursor ? { cursor } : {}),
            ...(friend_id ? { friend_id } : {}),
          },
        },
      });
      return r.data as ListTransactionsResponse;
    },
    staleTime: 10_000,
  });
}

export function useTransaction(txnId: string) {
  return useQuery<Transaction>({
    queryKey: transactionsKeys.one(txnId),
    queryFn: async () => {
      const r = await apiClient.GET('/transactions/{txn_id}', {
        params: { path: { txn_id: txnId } },
      });
      return r.data as Transaction;
    },
    enabled: Boolean(txnId),
    staleTime: 30_000,
  });
}

export type CreateTransactionArgs = {
  body: CreateTransactionRequest;
  idempotencyKey: string;
};

export function useCreateTransaction() {
  const qc = useQueryClient();
  return useMutation<Transaction, Error, CreateTransactionArgs>({
    mutationFn: async ({ body, idempotencyKey }) => {
      const r = await apiClient.POST('/transactions', {
        body,
        headers: { 'Idempotency-Key': idempotencyKey },
      });
      return r.data as Transaction;
    },
    onSuccess: (txn) => {
      // Every list view becomes stale (the new txn could appear in
      // any of them, depending on filters).
      qc.invalidateQueries({ queryKey: transactionsKeys.all });
      // And the precise pair-balance for every involved member.
      for (const member of txn.members) {
        qc.invalidateQueries({
          queryKey: friendsKeys.balance(member.user_id),
        });
      }
    },
  });
}

export type UpdateTransactionArgs = {
  txnId: string;
  body: CreateTransactionRequest;
  ifMatch: string;
};

export function useUpdateTransaction() {
  const qc = useQueryClient();
  return useMutation<Transaction, Error, UpdateTransactionArgs>({
    mutationFn: async ({ txnId, body, ifMatch }) => {
      const r = await apiClient.PUT('/transactions/{txn_id}', {
        params: { path: { txn_id: txnId } },
        body,
        headers: { 'If-Match': ifMatch },
      });
      return r.data as Transaction;
    },
    onSuccess: (txn) => {
      qc.invalidateQueries({ queryKey: transactionsKeys.all });
      qc.invalidateQueries({ queryKey: transactionsKeys.one(txn.txn_id) });
      for (const member of txn.members) {
        qc.invalidateQueries({
          queryKey: friendsKeys.balance(member.user_id),
        });
      }
    },
  });
}

export type DeleteTransactionArgs = {
  txnId: string;
  /** Used for cache-invalidation after the delete commits. */
  involvedMemberIds: string[];
};

export function useDeleteTransaction() {
  const qc = useQueryClient();
  return useMutation<void, Error, DeleteTransactionArgs>({
    mutationFn: async ({ txnId }) => {
      await apiClient.DELETE('/transactions/{txn_id}', {
        params: { path: { txn_id: txnId } },
      });
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: transactionsKeys.all });
      qc.invalidateQueries({ queryKey: transactionsKeys.one(vars.txnId) });
      for (const uid of vars.involvedMemberIds) {
        qc.invalidateQueries({ queryKey: friendsKeys.balance(uid) });
      }
    },
  });
}

export function useRestoreTransaction() {
  const qc = useQueryClient();
  return useMutation<Transaction, Error, string>({
    mutationFn: async (txnId) => {
      const r = await apiClient.POST('/transactions/{txn_id}/restore', {
        params: { path: { txn_id: txnId } },
      });
      return r.data as Transaction;
    },
    onSuccess: (txn) => {
      qc.invalidateQueries({ queryKey: transactionsKeys.all });
      qc.invalidateQueries({ queryKey: transactionsKeys.one(txn.txn_id) });
      for (const member of txn.members) {
        qc.invalidateQueries({
          queryKey: friendsKeys.balance(member.user_id),
        });
      }
    },
  });
}
