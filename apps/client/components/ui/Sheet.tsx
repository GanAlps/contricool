import type { ReactNode } from 'react';
import { Pressable, Text, View } from 'react-native';

import { cn } from '~/lib/utils';

export type SheetProps = {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  testID?: string;
};

/**
 * Minimal Phase 3b modal: backdrop + foreground card.  No animation
 * — the Phase 4 design wires reanimated; an MVP modal is fine
 * static.  RN-Web compatible (Pressable + View only).
 *
 * The outer container uses ``fixed inset-0`` (NativeWind →
 * CSS ``position: fixed``) so the overlay is **viewport**-relative
 * on web, not container-relative. With ``absolute inset-0`` the
 * sheet was clipped by whichever ancestor screen rendered it,
 * so a short transactions list left the modal hidden behind the
 * top-bar nav (issue reported 2026-04-30).
 *
 * On native, RN treats ``position: fixed`` as ``absolute`` (no
 * viewport concept). The web-only behavior is acceptable at MVP
 * since the native bundle hasn't shipped; when EAS native ships
 * we'll either keep ``absolute`` (modal scoped to the screen) or
 * port to ``react-native-modal`` for a true native overlay.
 *
 * The inner foreground card is constrained to ``max-h-[90vh]``
 * with internal scrolling so an oversized form (e.g. amount-split
 * with 10 members + the multi-payer editor) doesn't overflow the
 * viewport.
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
        <View className="p-4">{children}</View>
      </View>
    </View>
  );
}
