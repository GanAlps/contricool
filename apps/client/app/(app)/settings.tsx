import { Link, useRouter } from 'expo-router';
import { useState } from 'react';
import { Platform, ScrollView, Text, View } from 'react-native';

import { Button } from '~/components/ui/Button';
import { Card } from '~/components/ui/Card';
import { Sheet } from '~/components/ui/Sheet';
import { toast } from '~/components/ui/Toaster';
import { ApiErrorException } from '~/lib/api';
import { useAuthStore } from '~/lib/auth-store';
import { useDeleteMyAccount, useExportMyData } from '~/lib/queries/me';

const EXPORT_FILENAME = 'contricool-export.json';

export default function SettingsScreen() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const signOut = useAuthStore((s) => s.signOut);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const exportMutation = useExportMyData();
  const deleteMutation = useDeleteMyAccount();

  const onExport = async (): Promise<void> => {
    try {
      const data = await exportMutation.mutateAsync();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      if (Platform.OS === 'web') {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = EXPORT_FILENAME;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        toast.success('Export downloaded.');
      } else {
        toast.info('Export ready (saving on native is not yet implemented).');
      }
    } catch (e) {
      if (e instanceof ApiErrorException && e.error.code === 'RATE_LIMITED') {
        toast.error('You can only export once every 24 hours. Try again later.');
        return;
      }
      toast.error('Export failed. Please try again.');
    }
  };

  const onConfirmDelete = async (): Promise<void> => {
    try {
      await deleteMutation.mutateAsync();
      toast.success('Account deactivated. You will be signed out.');
      setConfirmOpen(false);
      try {
        await signOut();
      } catch {
        // Server already global-signed-out the Cognito session.
      }
      router.replace('/login');
    } catch {
      toast.error('Failed to delete account. Please try again.');
    }
  };

  return (
    <ScrollView className="flex-1 bg-neutral-50" contentContainerClassName="p-6">
      <View className="mx-auto w-full max-w-2xl gap-4">
        <Text className="text-2xl font-bold text-neutral-900">Settings</Text>

        <Card>
          <Text className="mb-1 text-base font-semibold text-neutral-900">Profile</Text>
          <Text className="text-sm text-neutral-700">{user?.name ?? '—'}</Text>
          <Text className="text-xs text-neutral-500">
            Default currency: {user?.currency ?? '—'}
          </Text>
        </Card>

        <Card>
          <Text className="mb-1 text-base font-semibold text-neutral-900">Export my data</Text>
          <Text className="mb-3 text-sm text-neutral-700">
            Download a JSON file with your profile, friends, and all transactions you are part of.
            Limited to once per 24 hours.
          </Text>
          <Button
            testID="settings-export"
            variant="secondary"
            onPress={onExport}
            loading={exportMutation.isPending}
          >
            Export my data
          </Button>
        </Card>

        <Card>
          <Text className="mb-1 text-base font-semibold text-neutral-900">Delete my account</Text>
          <Text className="mb-3 text-sm text-neutral-700">
            Deactivates your account immediately. Your data is hard-deleted after 30 days. Friends
            will no longer see you in their friend list, but transactions you shared with them
            remain in their history.
          </Text>
          <Button
            testID="settings-delete"
            variant="destructive"
            onPress={() => setConfirmOpen(true)}
          >
            Delete my account
          </Button>
        </Card>

        <Card>
          <Text className="mb-1 text-base font-semibold text-neutral-900">Legal</Text>
          <View className="flex-row gap-4">
            <Link href="/privacy" testID="settings-privacy" className="text-blue-600 underline">
              Privacy Policy
            </Link>
            <Link href="/terms" testID="settings-terms" className="text-blue-600 underline">
              Terms of Service
            </Link>
          </View>
        </Card>
      </View>

      <Sheet
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title="Delete account?"
        testID="settings-delete-confirm"
      >
        <View className="gap-3 p-4">
          <Text className="text-sm text-neutral-700">
            This will deactivate your account and sign you out of every device. Your data will be
            hard-deleted after 30 days. Are you sure?
          </Text>
          <View className="flex-row justify-end gap-2">
            <Button
              testID="settings-delete-cancel"
              variant="ghost"
              onPress={() => setConfirmOpen(false)}
            >
              Cancel
            </Button>
            <Button
              testID="settings-delete-confirm-btn"
              variant="destructive"
              onPress={onConfirmDelete}
              loading={deleteMutation.isPending}
            >
              Yes, delete
            </Button>
          </View>
        </View>
      </Sheet>
    </ScrollView>
  );
}
