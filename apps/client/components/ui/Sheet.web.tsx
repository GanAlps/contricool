import type { ReactNode } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';

import { cn } from '~/lib/utils';

export type SheetProps = {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  testID?: string;
};

/**
 * Web Sheet — backdrop + centered foreground card. No animation;
 * RN-Web compatible (Pressable + View + ScrollView).
 *
 * The outer container uses ``fixed inset-0`` (NativeWind →
 * CSS ``position: fixed``) so the overlay is **viewport**-relative,
 * not container-relative. With ``absolute inset-0`` the sheet was
 * clipped by whichever ancestor screen rendered it (issue reported
 * 2026-04-30).
 *
 * Native uses a separate ``Sheet.native.tsx`` backed by RN's
 * ``Modal`` with ``presentationStyle="pageSheet"`` — RN coerces
 * ``position: fixed`` to ``absolute`` (no viewport concept), which
 * clipped the modal inside its parent screen on phones.
 *
 * The inner foreground card is constrained to ``max-h-[90vh]``
 * with an internal ``ScrollView`` so an oversized form (e.g.
 * amount-split with 10 members + the multi-payer editor) scrolls
 * instead of overflowing the viewport.
 */
export function Sheet({ open, onClose, title, children, testID }: SheetProps) {
  if (!open) {
    return null;
  }
  return (
    <View className="fixed inset-0 z-50 items-center justify-center" testID={testID ?? 'sheet'}>
      <Pressable
        accessibilityLabel="Close"
        onPress={onClose}
        testID={testID ? `${testID}-backdrop` : 'sheet-backdrop'}
        className="absolute inset-0 bg-neutral-900/50"
      />
      <View
        className={cn(
          'z-10 max-h-[90vh] w-full max-w-md overflow-hidden rounded-lg border border-neutral-200 bg-white shadow-lg',
        )}
      >
        <View className="flex-row items-center justify-between border-b border-neutral-100 p-4">
          <Text className="text-lg font-semibold text-neutral-900">{title ?? ''}</Text>
          <Pressable
            accessibilityLabel="Close dialog"
            accessibilityRole="button"
            onPress={onClose}
            testID={testID ? `${testID}-close` : 'sheet-close'}
            className="rounded-md p-1 active:bg-neutral-100"
          >
            <Text className="text-base text-neutral-700">×</Text>
          </Pressable>
        </View>
        <ScrollView contentContainerClassName="p-4">{children}</ScrollView>
      </View>
    </View>
  );
}
