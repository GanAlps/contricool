import { useEffect, useMemo, useRef, useState } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { Pressable, ScrollView, Text, TextInput, View } from 'react-native';

import { zodResolver } from '@hookform/resolvers/zod';

import { Button } from '~/components/ui/Button';
import { Sheet } from '~/components/ui/Sheet';
import { toast } from '~/components/ui/Toaster';
import { ApiErrorException } from '~/lib/api';
import type { ApiError } from '~/lib/api';
import { useAuthStore } from '~/lib/auth-store';
import { useFriends } from '~/lib/queries/friends';
import { useCreateTransaction } from '~/lib/queries/transactions';
import { AddTransactionSchema, type AddTransactionValues } from '~/lib/schemas';
import type { CreateTransactionRequest } from '~/lib/types';

type Props = {
  open: boolean;
  onClose: () => void;
  /** Optional: pre-select this friend in the member list. */
  prefillFriendId?: string;
};

const FORM_FIELD_ERRORS: Record<string, { field: keyof AddTransactionValues; message: string }> = {
  OWED_SUM: { field: 'members', message: 'Member owed amounts must sum to the total.' },
  PERCENT_SUM: { field: 'members', message: 'Percents must sum to 100.' },
  PAID_SUM: { field: 'payers', message: 'Payer amounts must sum to the total.' },
  PAYER_NOT_MEMBER: { field: 'payers', message: 'Every payer must be a member.' },
  INVALID_AMOUNT: { field: 'amount', message: 'Amount must be positive.' },
  INVALID_DATE: { field: 'txn_date', message: 'Date is out of the accepted window.' },
};

const BANNER_ERRORS: Record<string, string> = {
  NOT_FRIEND: "One or more selected members aren't your friend anymore.",
  CURRENCY_MISMATCH: 'A selected friend uses a different currency.',
  SELF_NOT_MEMBER: 'You must be one of the members.',
  MIN_MEMBERS: 'Add at least one friend.',
  SETTLEMENT_SHAPE: 'Settlements need exactly two members.',
  MAX_MEMBERS: 'Too many members (max 10).',
};

const TOAST_ERRORS: Record<string, string> = {
  IDEMPOTENCY_KEY_REUSED: 'This transaction was already created. Refresh to see it.',
};

function isApiError(err: unknown): err is ApiErrorException {
  return err instanceof ApiErrorException;
}

function pickValidationIssue(e: ApiError): string {
  const first = e.details[0];
  return first?.issue ?? 'Invalid input.';
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  // Tests + older runtimes: cryptographic-quality not required for an
  // idempotency token, just uniqueness within a session.
  return `key-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function AddTransactionSheet({ open, onClose, prefillFriendId }: Props) {
  const me = useAuthStore((s) => s.user);
  const friends = useFriends();
  const create = useCreateTransaction();
  const idempotencyKeyRef = useRef<string>(newIdempotencyKey());
  const [bannerMessage, setBannerMessage] = useState<string | null>(null);

  const myCurrency = me?.currency ?? 'USD';
  const myUserId = me?.user_id ?? '';

  // Friends in the same currency are pickable; cross-currency friends
  // are filtered out (the server would reject anyway).
  const pickableFriends = useMemo(
    () => (friends.data?.items ?? []).filter((f) => f.currency === myCurrency),
    [friends.data, myCurrency],
  );

  const {
    control,
    handleSubmit,
    reset,
    setValue,
    watch,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<AddTransactionValues>({
    resolver: zodResolver(AddTransactionSchema),
    defaultValues: defaultValues(myUserId, myCurrency, prefillFriendId),
    mode: 'onSubmit',
  });

  // Reset everything when the sheet (re-)opens. Mint a fresh idempotency
  // key per open so cancel-then-reopen never collides server-side.
  useEffect(() => {
    if (open) {
      idempotencyKeyRef.current = newIdempotencyKey();
      reset(defaultValues(myUserId, myCurrency, prefillFriendId));
      setBannerMessage(null);
    }
  }, [open, reset, myUserId, myCurrency, prefillFriendId]);

  const watchedMembers = watch('members');
  const watchedAmount = watch('amount');
  const watchedType = watch('type');

  const memberIds = new Set(watchedMembers.map((m) => m.user_id));

  const toggleMember = (userId: string): void => {
    if (userId === myUserId) {
      return; // creator stays in the list
    }
    const next = memberIds.has(userId)
      ? watchedMembers.filter((m) => m.user_id !== userId)
      : [...watchedMembers, { user_id: userId }];
    if (next.length > 10) {
      return;
    }
    setValue('members', next, { shouldValidate: false });
  };

  const submit = handleSubmit(async (values) => {
    setBannerMessage(null);
    try {
      const body: CreateTransactionRequest = {
        name: values.name,
        type: values.type,
        amount: values.amount,
        currency: values.currency,
        txn_date: values.txn_date,
        note: values.note ?? '',
        split_method: values.split_method,
        members: values.members.map((m) => ({
          user_id: m.user_id,
          share: m.share ?? null,
          percent: m.percent ?? null,
          owed_amount: m.owed_amount ?? null,
        })),
        // Single-payer expense at MVP: requester paid the full amount.
        // Multi-payer / per-member-amount editing is a Phase 4c follow-up.
        payers: [{ user_id: myUserId, paid_amount: values.amount }],
      };
      await create.mutateAsync({ body, idempotencyKey: idempotencyKeyRef.current });
      toast.success('Transaction added');
      onClose();
    } catch (err) {
      if (!isApiError(err)) {
        toast.error("Couldn't save the transaction. Try again.");
        return;
      }
      const code = err.error.code;
      const fieldErr = FORM_FIELD_ERRORS[code];
      if (fieldErr) {
        setError(fieldErr.field as keyof AddTransactionValues, {
          type: 'server',
          message: fieldErr.message,
        });
        return;
      }
      const banner = BANNER_ERRORS[code];
      if (banner) {
        setBannerMessage(banner);
        return;
      }
      const toastMsg = TOAST_ERRORS[code];
      if (toastMsg) {
        toast.error(toastMsg);
        return;
      }
      if (code === 'VALIDATION_ERROR') {
        setBannerMessage(pickValidationIssue(err.error));
        return;
      }
      toast.error("Couldn't save the transaction. Try again.");
    }
  });

  return (
    <Sheet open={open} onClose={onClose} title="Add transaction" testID="add-txn-sheet">
      <ScrollView className="max-h-[70vh]" contentContainerClassName="gap-4">
        {bannerMessage ? (
          <View
            testID="add-txn-banner"
            className="rounded-md border border-danger-300 bg-danger-50 p-3"
          >
            <Text className="text-sm text-danger-700">{bannerMessage}</Text>
          </View>
        ) : null}

        <View>
          <Text className="mb-1 text-sm text-neutral-700">Name</Text>
          <Controller
            control={control}
            name="name"
            render={({ field }) => (
              <TextInput
                testID="add-txn-name"
                value={field.value}
                onChangeText={field.onChange}
                onBlur={field.onBlur}
                placeholder="Dinner at Joe's"
                className="h-10 rounded-md border border-neutral-300 px-3 text-base text-neutral-900"
              />
            )}
          />
          {errors.name ? (
            <Text testID="add-txn-name-error" className="mt-1 text-sm text-danger-600">
              {errors.name.message}
            </Text>
          ) : null}
        </View>

        <View className="flex-row gap-3">
          <View className="flex-1">
            <Text className="mb-1 text-sm text-neutral-700">Amount</Text>
            <Controller
              control={control}
              name="amount"
              render={({ field }) => (
                <TextInput
                  testID="add-txn-amount"
                  value={field.value}
                  onChangeText={field.onChange}
                  onBlur={field.onBlur}
                  keyboardType="decimal-pad"
                  inputMode="decimal"
                  placeholder="0.00"
                  className="h-10 rounded-md border border-neutral-300 px-3 text-base text-neutral-900"
                />
              )}
            />
            {errors.amount ? (
              <Text testID="add-txn-amount-error" className="mt-1 text-sm text-danger-600">
                {errors.amount.message}
              </Text>
            ) : null}
          </View>
          <View className="w-20">
            <Text className="mb-1 text-sm text-neutral-700">Currency</Text>
            <View
              testID="add-txn-currency"
              className="h-10 items-center justify-center rounded-md border border-neutral-300 bg-neutral-50"
            >
              <Text className="text-base text-neutral-700">{myCurrency}</Text>
            </View>
          </View>
        </View>

        <View>
          <Text className="mb-1 text-sm text-neutral-700">Date</Text>
          <Controller
            control={control}
            name="txn_date"
            render={({ field }) => (
              <TextInput
                testID="add-txn-date"
                value={field.value}
                onChangeText={field.onChange}
                onBlur={field.onBlur}
                placeholder="YYYY-MM-DD"
                className="h-10 rounded-md border border-neutral-300 px-3 text-base text-neutral-900"
              />
            )}
          />
          {errors.txn_date ? (
            <Text testID="add-txn-date-error" className="mt-1 text-sm text-danger-600">
              {errors.txn_date.message}
            </Text>
          ) : null}
        </View>

        <View>
          <Text className="mb-1 text-sm text-neutral-700">Members</Text>
          <View className="flex-row flex-wrap gap-2" testID="add-txn-members">
            <View className="rounded-full bg-primary-100 px-3 py-1.5">
              <Text className="text-sm text-primary-800">You</Text>
            </View>
            {pickableFriends.map((f) => {
              const selected = memberIds.has(f.user_id);
              return (
                <Pressable
                  key={f.user_id}
                  testID={`add-txn-member-${f.user_id}`}
                  onPress={() => toggleMember(f.user_id)}
                  className={
                    selected
                      ? 'rounded-full bg-primary-600 px-3 py-1.5'
                      : 'rounded-full border border-neutral-300 bg-white px-3 py-1.5 active:bg-neutral-100'
                  }
                >
                  <Text
                    className={
                      selected ? 'text-sm font-medium text-white' : 'text-sm text-neutral-700'
                    }
                  >
                    {f.name}
                  </Text>
                </Pressable>
              );
            })}
          </View>
          {pickableFriends.length === 0 ? (
            <Text className="mt-1 text-xs text-neutral-500">
              No friends in {myCurrency} yet — add one first.
            </Text>
          ) : null}
          {errors.members ? (
            <Text testID="add-txn-members-error" className="mt-1 text-sm text-danger-600">
              {(errors.members as { message?: string }).message ?? 'Invalid members'}
            </Text>
          ) : null}
        </View>

        <View>
          <Text className="mb-1 text-sm text-neutral-700">Note (optional)</Text>
          <Controller
            control={control}
            name="note"
            render={({ field }) => (
              <TextInput
                testID="add-txn-note"
                value={field.value ?? ''}
                onChangeText={field.onChange}
                onBlur={field.onBlur}
                placeholder=""
                className="h-10 rounded-md border border-neutral-300 px-3 text-base text-neutral-900"
              />
            )}
          />
        </View>

        <View>
          <Text className="text-xs text-neutral-500">
            Type: {watchedType === 'settlement' ? 'Settlement' : 'Expense'} · Split: equal · You
            paid {watchedAmount} {myCurrency}
          </Text>
          {errors.payers ? (
            <Text testID="add-txn-payers-error" className="mt-1 text-sm text-danger-600">
              {(errors.payers as { message?: string }).message ?? 'Invalid payers'}
            </Text>
          ) : null}
        </View>

        <View className="flex-row justify-end gap-2 pt-2">
          <Button testID="add-txn-cancel" variant="secondary" onPress={onClose}>
            Cancel
          </Button>
          <Button
            testID="add-txn-submit"
            onPress={submit}
            loading={isSubmitting || create.isPending}
          >
            Add transaction
          </Button>
        </View>
      </ScrollView>
    </Sheet>
  );
}

function defaultValues(
  myUserId: string,
  currency: 'USD' | 'INR',
  prefillFriendId?: string,
): AddTransactionValues {
  const members = [{ user_id: myUserId, share: null, percent: null, owed_amount: null }];
  if (prefillFriendId) {
    members.push({ user_id: prefillFriendId, share: null, percent: null, owed_amount: null });
  }
  return {
    name: '',
    type: 'expense',
    amount: '',
    currency,
    txn_date: todayIso(),
    note: '',
    split_method: 'equal',
    members,
    payers: [{ user_id: myUserId, paid_amount: '0' }],
  };
}
