import { useEffect } from 'react';
import { Pressable, Text, View } from 'react-native';
import { create } from 'zustand';

import { cn } from '~/lib/utils';

export type ToastKind = 'success' | 'error' | 'info';

export type Toast = {
  id: number;
  kind: ToastKind;
  message: string;
  durationMs: number;
};

type ToasterState = {
  toasts: Toast[];
  push: (kind: ToastKind, message: string, durationMs?: number) => number;
  dismiss: (id: number) => void;
  clear: () => void;
};

let nextId = 1;

export const useToasterStore = create<ToasterState>((set) => ({
  toasts: [],
  push: (kind, message, durationMs = 4000) => {
    const id = nextId++;
    set((s) => ({ toasts: [...s.toasts, { id, kind, message, durationMs }] }));
    return id;
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  clear: () => set({ toasts: [] }),
}));

export const toast = {
  success: (message: string, durationMs?: number) =>
    useToasterStore.getState().push('success', message, durationMs),
  error: (message: string, durationMs?: number) =>
    useToasterStore.getState().push('error', message, durationMs),
  info: (message: string, durationMs?: number) =>
    useToasterStore.getState().push('info', message, durationMs),
};

const kindStyles: Record<ToastKind, string> = {
  success: 'bg-success-600',
  error: 'bg-danger-600',
  info: 'bg-neutral-700',
};

export function Toaster({ testID }: { testID?: string }) {
  const toasts = useToasterStore((s) => s.toasts);
  const dismiss = useToasterStore((s) => s.dismiss);
  return (
    <View
      style={{ pointerEvents: 'box-none' }}
      className="absolute inset-x-0 bottom-4 items-center"
      testID={testID ?? 'toaster'}
    >
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onDismiss={dismiss} />
      ))}
    </View>
  );
}

function ToastItem({ toast: t, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  useEffect(() => {
    const handle = setTimeout(() => onDismiss(t.id), t.durationMs);
    return () => clearTimeout(handle);
  }, [t.id, t.durationMs, onDismiss]);
  return (
    <Pressable
      onPress={() => onDismiss(t.id)}
      accessibilityRole="alert"
      testID={`toast-${t.kind}`}
      className={cn('mt-2 max-w-md rounded-md px-4 py-3', kindStyles[t.kind])}
    >
      <Text className="text-sm text-white">{t.message}</Text>
    </Pressable>
  );
}
