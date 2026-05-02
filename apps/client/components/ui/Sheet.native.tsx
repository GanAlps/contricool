import type { ReactNode } from 'react';
import {
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

export type SheetProps = {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  testID?: string;
};

/**
 * Native Sheet — full-page slide-up presentation backed by RN's
 * `Modal`. The web variant uses `position: fixed` which RN coerces
 * to `absolute`, so on phones the sheet was clipped by its
 * containing screen and the submit button fell off-screen.
 *
 * `presentationStyle="pageSheet"` gives iOS the system-native
 * drawer (slides from bottom, can be dismissed by swipe-down) and
 * Android a full-screen page that respects the back button via
 * `onRequestClose`.
 *
 * Body is wrapped in a ScrollView so long forms (multi-payer +
 * non-equal split editor) scroll instead of clipping. SafeAreaView
 * keeps the close button below the notch and content above the
 * gesture area.
 */
export function Sheet({ open, onClose, title, children, testID }: SheetProps) {
  return (
    <Modal
      visible={open}
      onRequestClose={onClose}
      animationType="slide"
      presentationStyle="pageSheet"
      transparent={false}
      statusBarTranslucent
      testID={testID ?? 'sheet'}
    >
      <SafeAreaView className="flex-1 bg-white" edges={['top', 'bottom']}>
        <KeyboardAvoidingView
          style={{ flex: 1 }}
          behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        >
          <View className="flex-row items-center justify-between border-b border-neutral-200 px-4 py-3">
            <Text className="text-lg font-semibold text-neutral-900">{title ?? ''}</Text>
            <Pressable
              accessibilityLabel="Close dialog"
              accessibilityRole="button"
              onPress={onClose}
              testID={testID ? `${testID}-close` : 'sheet-close'}
              className="rounded-md px-3 py-1 active:bg-neutral-100"
            >
              <Text className="text-2xl text-neutral-700">×</Text>
            </Pressable>
          </View>
          <ScrollView
            className="flex-1"
            contentContainerClassName="p-4"
            keyboardShouldPersistTaps="handled"
          >
            {children}
          </ScrollView>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </Modal>
  );
}
