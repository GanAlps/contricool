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
import { useCreateTransaction, useUpdateTransaction } from '~/lib/queries/transactions';
import { AddTransactionSchema, type AddTransactionValues } from '~/lib/schemas';
import type { CreateTransactionRequest, Transaction } from '~/lib/types';

type Props = {
  open: boolean;
  onClose: () => void;
  /** Optional: pre-select this friend in the member list. */
  prefillFriendId?: string;
  /**
   * Edit mode. When provided, the form pre-fills from this
   * transaction and submit calls ``PUT`` (with ``If-Match``)
   * instead of ``POST``. Currency is locked.
   */
  existing?: Transaction;
};

type SplitMethod = 'equal' | 'amount' | 'share' | 'percent';
type TxnType = 'expense' | 'settlement';
type PayerMode = 'single' | 'multiple';

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
  // Edit-mode errors:
  PRECONDITION_FAILED: 'Someone else changed this transaction. Refresh and try again.',
  FORBIDDEN: "You can't edit this transaction.",
};

const TOAST_ERRORS: Record<string, string> = {
  IDEMPOTENCY_KEY_REUSED: 'This transaction was already created. Refresh to see it.',
  // Should never reach here in practice — the form always supplies the
  // header — but defensively map it so a regression in the wiring
  // surfaces a useful message instead of the generic catch-all.
  IDEMPOTENCY_KEY_REQUIRED: 'Please retry the request.',
};

const SPLIT_METHODS: { value: SplitMethod; label: string }[] = [
  { value: 'equal', label: 'Equal' },
  { value: 'amount', label: 'Amount' },
  { value: 'share', label: 'Share' },
  { value: 'percent', label: 'Percent' },
];

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

export function AddTransactionSheet({ open, onClose, prefillFriendId, existing }: Props) {
  const me = useAuthStore((s) => s.user);
  const friends = useFriends();
  const create = useCreateTransaction();
  const update = useUpdateTransaction();
  const idempotencyKeyRef = useRef<string>(newIdempotencyKey());
  const [bannerMessage, setBannerMessage] = useState<string | null>(null);
  const [payerMode, setPayerMode] = useState<PayerMode>('single');
  const [payerAmounts, setPayerAmounts] = useState<Record<string, string>>({});

  const isEdit = Boolean(existing);

  const myCurrency = me?.currency ?? 'USD';
  const myUserId = me?.user_id ?? '';

  // Friends in the same currency are pickable; cross-currency friends
  // are filtered out (the server would reject anyway).
  const pickableFriends = useMemo(
    () => (friends.data?.items ?? []).filter((f) => f.currency === myCurrency),
    [friends.data, myCurrency],
  );

  const friendNameById = useMemo(() => {
    const map: Record<string, string> = {};
    for (const f of pickableFriends) map[f.user_id] = f.name;
    return map;
  }, [pickableFriends]);

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

  // Reset everything when the sheet (re-)opens. Mint a fresh
  // idempotency key per open so cancel-then-reopen never collides
  // server-side.
  //
  // ``prefillFriendId`` is gated on ``pickableFriends`` so a
  // cross-currency friend passed in via the prop doesn't bypass the
  // same-currency picker filter and land silently in the submitted
  // body (server would 422 on CURRENCY_MISMATCH and the user
  // couldn't remove the invisible chip).
  // Re-init when the sheet opens *or* when the underlying existing
  // transaction's identity changes. Within an open lifetime, a
  // re-render that hands us a fresh-but-equivalent ``existing``
  // (same ``txn_id``) or a refetch of the friends list must NOT
  // wipe in-flight typing — that would reset every keystroke.
  // We dedup via ``existingId`` and intentionally exclude
  // ``pickableFriends`` from the deps; the latest snapshot is
  // captured at effect time via the closure.
  const existingId = existing?.txn_id ?? null;
  const pickableFriendsRef = useRef(pickableFriends);
  pickableFriendsRef.current = pickableFriends;
  useEffect(() => {
    if (open) {
      idempotencyKeyRef.current = newIdempotencyKey();
      if (existing) {
        reset(editValuesFrom(existing));
        const isMulti = existing.payers.length !== 1 || existing.payers[0]?.user_id !== myUserId;
        setPayerMode(isMulti ? 'multiple' : 'single');
        setPayerAmounts(
          isMulti
            ? Object.fromEntries(existing.payers.map((p) => [p.user_id, String(p.paid_amount)]))
            : {},
        );
      } else {
        const safePrefill = pickableFriendsRef.current.some((f) => f.user_id === prefillFriendId)
          ? prefillFriendId
          : undefined;
        reset(defaultValues(myUserId, myCurrency, safePrefill));
        setPayerMode('single');
        setPayerAmounts({});
      }
      setBannerMessage(null);
    }
    // ``existing`` and ``pickableFriends`` are intentionally not in
    // the deps. See comment above.
    // biome-ignore lint/correctness/useExhaustiveDependencies: see comment above
  }, [open, reset, myUserId, myCurrency, prefillFriendId, existingId]);

  const watchedMembers = watch('members');
  const watchedAmount = watch('amount');
  const watchedType = watch('type');
  const watchedSplitMethod = watch('split_method');

  const memberIds = new Set(watchedMembers.map((m) => m.user_id));

  const toggleMember = (userId: string): void => {
    if (userId === myUserId) {
      return; // creator stays in the list
    }
    if (watchedType === 'settlement') {
      // Exactly one other member at a time for settlement.
      const next = memberIds.has(userId)
        ? watchedMembers.filter((m) => m.user_id === myUserId)
        : [
            ...watchedMembers.filter((m) => m.user_id === myUserId),
            { user_id: userId, share: null, percent: null, owed_amount: null },
          ];
      setValue('members', next, { shouldValidate: false });
      // Clear any payer-amount entries for the deselected friend.
      setPayerAmounts((prev) => {
        const filtered: Record<string, string> = {};
        for (const m of next) {
          const v = prev[m.user_id];
          if (v) filtered[m.user_id] = v;
        }
        return filtered;
      });
      return;
    }
    const next = memberIds.has(userId)
      ? watchedMembers.filter((m) => m.user_id !== userId)
      : [...watchedMembers, { user_id: userId, share: null, percent: null, owed_amount: null }];
    if (next.length > 10) {
      return;
    }
    setValue('members', next, { shouldValidate: false });
    setPayerAmounts((prev) => {
      const filtered: Record<string, string> = {};
      for (const m of next) {
        const v = prev[m.user_id];
        if (v) filtered[m.user_id] = v;
      }
      return filtered;
    });
  };

  const setMemberField = (
    userId: string,
    field: 'share' | 'percent' | 'owed_amount',
    value: string,
  ): void => {
    setValue(
      'members',
      watchedMembers.map((m) =>
        m.user_id === userId ? { ...m, [field]: value === '' ? null : value } : m,
      ),
      { shouldValidate: false },
    );
  };

  const onTypeChange = (next: TxnType): void => {
    setValue('type', next, { shouldValidate: false });
    if (next === 'settlement') {
      // Settlement: exactly two members + amount split + single payer.
      const otherMember = watchedMembers.find((m) => m.user_id !== myUserId);
      const trimmed = otherMember
        ? [
            { user_id: myUserId, share: null, percent: null, owed_amount: null },
            { user_id: otherMember.user_id, share: null, percent: null, owed_amount: null },
          ]
        : [{ user_id: myUserId, share: null, percent: null, owed_amount: null }];
      setValue('members', trimmed, { shouldValidate: false });
      setValue('split_method', 'amount', { shouldValidate: false });
      setPayerMode('single');
      setPayerAmounts({});
      return;
    }
    // Reverting to expense: the settlement flow forced split_method
    // to 'amount'. Reset to the default so the user doesn't see
    // surprise per-member input rows from the previous mode.
    setValue('split_method', 'equal', { shouldValidate: false });
  };

  const onPayerModeChange = (next: PayerMode): void => {
    setPayerMode(next);
    if (next === 'single') {
      setPayerAmounts({});
    }
  };

  const submit = handleSubmit(async (values) => {
    setBannerMessage(null);

    // For settlements, the server requires `owed_amount` per member:
    // payer member = "0.00", the other member = the full transaction
    // amount (see service.validate_create_payload). The form hides
    // the per-member rows for settlement, so we compute the values
    // here. Single payer = creator (settlement is always single-payer).
    const settlementOwed = (memberId: string): string =>
      memberId === myUserId ? '0.00' : values.amount;

    const memberRows = values.members.map((m) => {
      if (values.type === 'settlement') {
        return {
          user_id: m.user_id,
          share: null,
          percent: null,
          owed_amount: settlementOwed(m.user_id),
        };
      }
      return {
        user_id: m.user_id,
        share: values.split_method === 'share' && m.share != null ? m.share : null,
        percent: values.split_method === 'percent' && m.percent != null ? m.percent : null,
        owed_amount:
          values.split_method === 'amount' && m.owed_amount != null ? m.owed_amount : null,
      };
    });

    // Build payers based on mode. Settlement is always single-payer
    // (settlement collapse forces payerMode='single' on type change).
    let payers: { user_id: string; paid_amount: string }[];
    if (values.type === 'expense' && payerMode === 'multiple') {
      const entries = Object.entries(payerAmounts).filter(
        ([uid, amt]) => memberIds.has(uid) && amt.trim() !== '' && Number(amt) > 0,
      );
      if (entries.length === 0) {
        setError('payers', { type: 'manual', message: 'Enter at least one payer amount.' });
        return;
      }
      payers = entries.map(([uid, amt]) => ({ user_id: uid, paid_amount: amt }));
    } else {
      payers = [{ user_id: myUserId, paid_amount: values.amount }];
    }

    try {
      const body: CreateTransactionRequest = {
        name: values.name,
        type: values.type,
        amount: values.amount,
        currency: values.currency,
        txn_date: values.txn_date,
        note: values.note ?? '',
        split_method: values.split_method,
        members: memberRows,
        payers,
      };
      if (existing) {
        await update.mutateAsync({
          txnId: existing.txn_id,
          body,
          ifMatch: String(existing.updated_at),
        });
        toast.success('Transaction updated');
      } else {
        await create.mutateAsync({
          body,
          idempotencyKey: idempotencyKeyRef.current,
        });
        toast.success('Transaction added');
      }
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

        {/* Type segmented control */}
        <View>
          <Text className="mb-1 text-sm text-neutral-700">Type</Text>
          <View className="flex-row rounded-md border border-neutral-300" testID="add-txn-type">
            {(['expense', 'settlement'] as TxnType[]).map((t, idx) => {
              const selected = watchedType === t;
              return (
                <Pressable
                  key={t}
                  testID={`add-txn-type-${t}`}
                  onPress={() => onTypeChange(t)}
                  className={`flex-1 items-center py-2 ${idx === 0 ? '' : 'border-l border-neutral-300'} ${
                    selected ? 'bg-primary-600' : 'bg-white active:bg-neutral-100'
                  }`}
                >
                  <Text
                    className={
                      selected ? 'text-sm font-medium text-white' : 'text-sm text-neutral-700'
                    }
                  >
                    {t === 'expense' ? 'Expense' : 'Settlement'}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </View>

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

        {/* Members picker */}
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

        {/* Split method segmented — hidden for settlement (always amount). */}
        {watchedType === 'expense' ? (
          <View>
            <Text className="mb-1 text-sm text-neutral-700">Split method</Text>
            <View className="flex-row rounded-md border border-neutral-300" testID="add-txn-split">
              {SPLIT_METHODS.map((m, idx) => {
                const selected = watchedSplitMethod === m.value;
                return (
                  <Pressable
                    key={m.value}
                    testID={`add-txn-split-${m.value}`}
                    onPress={() => setValue('split_method', m.value, { shouldValidate: false })}
                    className={`flex-1 items-center py-2 ${idx === 0 ? '' : 'border-l border-neutral-300'} ${
                      selected ? 'bg-primary-600' : 'bg-white active:bg-neutral-100'
                    }`}
                  >
                    <Text
                      className={
                        selected ? 'text-sm font-medium text-white' : 'text-sm text-neutral-700'
                      }
                    >
                      {m.label}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          </View>
        ) : null}

        {/* Per-member input rows for amount/share/percent. */}
        {(watchedSplitMethod === 'amount' ||
          watchedSplitMethod === 'share' ||
          watchedSplitMethod === 'percent') &&
        watchedType === 'expense' ? (
          <View testID="add-txn-member-inputs" className="gap-2">
            <Text className="text-sm text-neutral-700">
              {watchedSplitMethod === 'amount'
                ? 'Owed amount per member'
                : watchedSplitMethod === 'share'
                  ? 'Shares per member'
                  : 'Percent per member'}
            </Text>
            {watchedMembers.map((m) => {
              const label = m.user_id === myUserId ? 'You' : (friendNameById[m.user_id] ?? '—');
              const fieldKey: 'owed_amount' | 'share' | 'percent' =
                watchedSplitMethod === 'amount'
                  ? 'owed_amount'
                  : watchedSplitMethod === 'share'
                    ? 'share'
                    : 'percent';
              const current = (m[fieldKey] ?? '') as string;
              return (
                <View key={m.user_id} className="flex-row items-center gap-2">
                  <Text className="w-24 text-sm text-neutral-700">{label}</Text>
                  <TextInput
                    testID={`add-txn-member-${fieldKey}-${m.user_id}`}
                    value={current}
                    onChangeText={(v) => setMemberField(m.user_id, fieldKey, v)}
                    keyboardType="decimal-pad"
                    inputMode="decimal"
                    placeholder={watchedSplitMethod === 'percent' ? '0' : '0.00'}
                    className="h-9 flex-1 rounded-md border border-neutral-300 px-3 text-base text-neutral-900"
                  />
                </View>
              );
            })}
          </View>
        ) : null}

        {/* Paid by control — hidden for settlement (always single payer). */}
        {watchedType === 'expense' ? (
          <View>
            <Text className="mb-1 text-sm text-neutral-700">Paid by</Text>
            <View
              className="flex-row rounded-md border border-neutral-300"
              testID="add-txn-payer-mode"
            >
              {(['single', 'multiple'] as PayerMode[]).map((mode, idx) => {
                const selected = payerMode === mode;
                return (
                  <Pressable
                    key={mode}
                    testID={`add-txn-payer-mode-${mode}`}
                    onPress={() => onPayerModeChange(mode)}
                    className={`flex-1 items-center py-2 ${idx === 0 ? '' : 'border-l border-neutral-300'} ${
                      selected ? 'bg-primary-600' : 'bg-white active:bg-neutral-100'
                    }`}
                  >
                    <Text
                      className={
                        selected ? 'text-sm font-medium text-white' : 'text-sm text-neutral-700'
                      }
                    >
                      {mode === 'single' ? 'You only' : 'Multiple'}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          </View>
        ) : null}

        {/* Per-payer amount inputs when Multiple. */}
        {payerMode === 'multiple' && watchedType === 'expense' ? (
          <View testID="add-txn-payer-inputs" className="gap-2">
            <Text className="text-sm text-neutral-700">Paid amount per payer</Text>
            {watchedMembers.map((m) => {
              const label = m.user_id === myUserId ? 'You' : (friendNameById[m.user_id] ?? '—');
              const current = payerAmounts[m.user_id] ?? '';
              return (
                <View key={m.user_id} className="flex-row items-center gap-2">
                  <Text className="w-24 text-sm text-neutral-700">{label}</Text>
                  <TextInput
                    testID={`add-txn-payer-amount-${m.user_id}`}
                    value={current}
                    onChangeText={(v) => setPayerAmounts((prev) => ({ ...prev, [m.user_id]: v }))}
                    keyboardType="decimal-pad"
                    inputMode="decimal"
                    placeholder="0.00"
                    className="h-9 flex-1 rounded-md border border-neutral-300 px-3 text-base text-neutral-900"
                  />
                </View>
              );
            })}
          </View>
        ) : null}

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

        {/* Settlement summary */}
        {watchedType === 'settlement' ? (
          <View>
            <Text className="text-xs text-neutral-500">
              Settlement: amount split, you paid {watchedAmount || '0'} {myCurrency}
            </Text>
          </View>
        ) : null}

        {payerMode === 'single' && watchedType === 'expense' ? (
          <View>
            <Text className="text-xs text-neutral-500">
              You paid {watchedAmount || '0'} {myCurrency}
            </Text>
          </View>
        ) : null}

        {/* Single source of truth for payers field error so the testID
            isn't duplicated across rendering branches. */}
        {errors.payers ? (
          <Text testID="add-txn-payers-error" className="mt-1 text-sm text-danger-600">
            {(errors.payers as { message?: string }).message ?? 'Invalid payers'}
          </Text>
        ) : null}

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

function editValuesFrom(t: Transaction): AddTransactionValues {
  // Server timestamps + Decimals come through as strings on the wire;
  // the form schema is string-typed too. `txn_date` is a string in
  // the SDK shape (date-string).
  const dateStr = String(t.txn_date);
  return {
    name: t.name,
    type: t.type,
    amount: String(t.amount),
    currency: t.currency,
    txn_date: dateStr,
    note: t.note ?? '',
    split_method: t.split_method,
    members: t.members.map((m) => ({
      user_id: m.user_id,
      share: m.share != null ? String(m.share) : null,
      percent: m.percent != null ? String(m.percent) : null,
      owed_amount: m.owed_amount != null ? String(m.owed_amount) : null,
    })),
    payers: t.payers.map((p) => ({
      user_id: p.user_id,
      paid_amount: String(p.paid_amount),
    })),
  };
}
