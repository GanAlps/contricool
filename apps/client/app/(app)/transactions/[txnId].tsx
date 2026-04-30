import { useLocalSearchParams, useRouter } from 'expo-router';
import { useMemo, useState } from 'react';
import { ScrollView, Text, View } from 'react-native';

import { AddTransactionSheet } from '~/components/transactions/AddTransactionSheet';
import { Button } from '~/components/ui/Button';
import { Card } from '~/components/ui/Card';
import { Sheet } from '~/components/ui/Sheet';
import { Spinner } from '~/components/ui/Spinner';
import { toast } from '~/components/ui/Toaster';
import { ApiErrorException } from '~/lib/api';
import { useAuthStore } from '~/lib/auth-store';
import { useFriends } from '~/lib/queries/friends';
import {
  useDeleteTransaction,
  useRestoreTransaction,
  useTransaction,
} from '~/lib/queries/transactions';
import type { TransactionMember, TransactionPayer } from '~/lib/types';

export default function TransactionDetailScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ txnId: string }>();
  const txnId = typeof params.txnId === 'string' ? params.txnId : '';

  const me = useAuthStore((s) => s.user);
  const friends = useFriends();
  const txn = useTransaction(txnId);
  const deleteTxn = useDeleteTransaction();
  const restoreTxn = useRestoreTransaction();
  const [editOpen, setEditOpen] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  const nameByUserId = useMemo(() => {
    const map: Record<string, string> = {};
    if (me) {
      map[me.user_id] = me.name;
    }
    for (const f of friends.data?.items ?? []) {
      map[f.user_id] = f.name;
    }
    return map;
  }, [friends.data, me]);

  if (txn.isLoading) {
    return (
      <View className="flex-1 items-center justify-center bg-neutral-50">
        <Spinner testID="txn-detail-spinner" size="large" />
      </View>
    );
  }

  const apiErr = txn.error instanceof ApiErrorException ? txn.error.error : null;
  if (apiErr?.code === 'NOT_FOUND') {
    return (
      <View className="flex-1 items-center justify-center bg-neutral-50 p-6">
        <Card testID="txn-not-found">
          <Text className="mb-4 text-center text-base text-neutral-800">
            This transaction doesn't exist or you can't see it.
          </Text>
          <Button testID="txn-not-found-back" onPress={() => router.back()} fullWidth>
            Back
          </Button>
        </Card>
      </View>
    );
  }

  const t = txn.data;
  if (!t) {
    return null;
  }

  return (
    <ScrollView className="flex-1 bg-neutral-50" contentContainerClassName="p-6">
      <Card testID="txn-detail">
        <Text className="text-2xl font-bold text-neutral-900">{t.name}</Text>
        <Text testID="txn-detail-amount" className="mt-1 text-xl text-neutral-900">
          {t.amount} {t.currency}
        </Text>
        <Text className="mt-1 text-xs text-neutral-500">
          {t.txn_date} · {t.type === 'settlement' ? 'Settlement' : 'Expense'} · split{' '}
          {t.split_method}
        </Text>
        {t.note ? (
          <Text testID="txn-detail-note" className="mt-3 text-sm text-neutral-700">
            {t.note}
          </Text>
        ) : null}

        <Text className="mt-6 mb-2 text-xs font-semibold uppercase tracking-wider text-neutral-500">
          Members
        </Text>
        <View testID="txn-detail-members" className="gap-1">
          {t.members.map((m) => (
            <MemberLine
              key={m.user_id}
              member={m}
              currency={t.currency}
              displayName={nameByUserId[m.user_id] ?? shortenId(m.user_id)}
            />
          ))}
        </View>

        <Text className="mt-6 mb-2 text-xs font-semibold uppercase tracking-wider text-neutral-500">
          Paid by
        </Text>
        <View testID="txn-detail-payers" className="gap-1">
          {t.payers.map((p) => (
            <PayerLine
              key={p.user_id}
              payer={p}
              currency={t.currency}
              displayName={nameByUserId[p.user_id] ?? shortenId(p.user_id)}
            />
          ))}
        </View>

        <View className="mt-6 gap-2">
          {me && t.creator_id === me.user_id ? (
            <>
              <Button testID="txn-detail-edit" onPress={() => setEditOpen(true)}>
                Edit
              </Button>
              <Button
                testID="txn-detail-delete"
                variant="destructive"
                onPress={() => setConfirmDeleteOpen(true)}
                loading={deleteTxn.isPending}
              >
                Delete
              </Button>
            </>
          ) : null}
          <Button
            testID="txn-detail-back"
            variant="secondary"
            onPress={() => router.back()}
            fullWidth
          >
            Back
          </Button>
        </View>
      </Card>

      <AddTransactionSheet open={editOpen} onClose={() => setEditOpen(false)} existing={t} />

      <Sheet
        open={confirmDeleteOpen}
        onClose={() => setConfirmDeleteOpen(false)}
        title="Delete this transaction?"
        testID="txn-confirm-delete"
      >
        <Text className="mb-4 text-sm text-neutral-700">
          This will remove the transaction from everyone's lists. You have 30 days to restore it.
        </Text>
        <View className="flex-row justify-end gap-2">
          <Button
            testID="txn-confirm-delete-cancel"
            variant="secondary"
            onPress={() => setConfirmDeleteOpen(false)}
          >
            Cancel
          </Button>
          <Button
            testID="txn-confirm-delete-confirm"
            variant="destructive"
            onPress={async () => {
              setConfirmDeleteOpen(false);
              const memberIds = t.members.map((m) => m.user_id);
              try {
                await deleteTxn.mutateAsync({
                  txnId: t.txn_id,
                  involvedMemberIds: memberIds,
                });
              } catch (err) {
                if (err instanceof ApiErrorException) {
                  toast.error(
                    err.error.code === 'FORBIDDEN'
                      ? "You can't delete this transaction."
                      : 'Could not delete. Try again.',
                  );
                } else {
                  toast.error('Could not delete. Try again.');
                }
                return;
              }
              // Toast-based undo is a follow-up; for now the user
              // restores from the detail page's restore bar (visible
              // on a soft-deleted txn) within the 30-day window.
              toast.success(`Deleted "${t.name}".`);
              router.back();
            }}
          >
            Delete
          </Button>
        </View>
      </Sheet>

      {t.deleted_at ? (
        <Card testID="txn-detail-restore-bar" className="mt-3">
          <Text className="mb-2 text-sm text-neutral-700">
            This transaction is deleted. You can restore it within 30 days.
          </Text>
          <Button
            testID="txn-detail-restore"
            onPress={async () => {
              try {
                await restoreTxn.mutateAsync(t.txn_id);
                toast.success('Restored');
              } catch (err) {
                if (err instanceof ApiErrorException) {
                  toast.error(
                    err.error.code === 'GONE'
                      ? 'The 30-day restore window has expired.'
                      : 'Could not restore.',
                  );
                } else {
                  toast.error('Could not restore.');
                }
              }
            }}
            loading={restoreTxn.isPending}
            fullWidth
          >
            Restore
          </Button>
        </Card>
      ) : null}
    </ScrollView>
  );
}

function MemberLine({
  member,
  currency,
  displayName,
}: {
  member: TransactionMember;
  currency: string;
  displayName: string;
}) {
  return (
    <View className="flex-row justify-between rounded-md border border-neutral-200 bg-white p-3">
      <Text className="text-sm text-neutral-900">{displayName}</Text>
      <Text className="text-sm text-neutral-700">
        {member.owed_amount} {currency}
      </Text>
    </View>
  );
}

function PayerLine({
  payer,
  currency,
  displayName,
}: {
  payer: TransactionPayer;
  currency: string;
  displayName: string;
}) {
  return (
    <View className="flex-row justify-between rounded-md border border-neutral-200 bg-white p-3">
      <Text className="text-sm text-neutral-900">{displayName}</Text>
      <Text className="text-sm text-neutral-700">
        {payer.paid_amount} {currency}
      </Text>
    </View>
  );
}

function shortenId(id: string): string {
  return id.length > 10 ? `${id.slice(0, 6)}…${id.slice(-4)}` : id;
}
