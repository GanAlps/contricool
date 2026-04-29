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
 */
export function Sheet({ open, onClose, title, children, testID }: SheetProps) {
  if (!open) {
    return null;
  }
  return (
    <View className="absolute inset-0 z-50 items-center justify-center" testID={testID ?? 'sheet'}>
      <Pressable
        accessibilityLabel="Close"
        onPress={onClose}
        testID={testID ? `${testID}-backdrop` : 'sheet-backdrop'}
        className="absolute inset-0 bg-neutral-900/50"
      />
      <View
        className={cn(
          'z-10 w-full max-w-md rounded-lg border border-neutral-200 bg-white p-6 shadow-lg',
        )}
      >
        <View className="mb-4 flex-row items-center justify-between">
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
        {children}
      </View>
    </View>
  );
}
