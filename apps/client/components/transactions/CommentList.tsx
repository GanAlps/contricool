import { useState } from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';

import { Card } from '~/components/ui/Card';
import { Spinner } from '~/components/ui/Spinner';
import { toast } from '~/components/ui/Toaster';
import { ApiErrorException } from '~/lib/api';
import { useAuthStore } from '~/lib/auth-store';
import { usePostComment, useTransactionComments } from '~/lib/queries/transactions';

const SYSTEM_AUTHOR = 'system';

export type CommentListProps = {
  txnId: string;
  /** ``user_id``s of the txn members — used to gate the composer. */
  memberIds: string[];
  /** Friendly name lookup so we render names instead of bare ULIDs. */
  nameByUserId: Record<string, string>;
  testID?: string;
};

export function CommentList({ txnId, memberIds, nameByUserId, testID }: CommentListProps) {
  const me = useAuthStore((s) => s.user);
  const isMember = me ? memberIds.includes(me.user_id) : false;
  const comments = useTransactionComments(txnId);
  const post = usePostComment();
  const [draft, setDraft] = useState('');

  const onPost = async (): Promise<void> => {
    const trimmed = draft.trim();
    if (!trimmed) {
      return;
    }
    try {
      await post.mutateAsync({ txnId, body: trimmed });
      setDraft('');
    } catch (e) {
      if (e instanceof ApiErrorException) {
        toast.error(e.error.message ?? 'Could not post comment.');
      } else {
        toast.error('Could not post comment.');
      }
    }
  };

  const items = comments.data?.items ?? [];

  return (
    <Card testID={testID ?? 'txn-comments'}>
      <Text className="mb-2 text-base font-semibold text-neutral-900">Comments</Text>
      {comments.isLoading ? (
        <View className="items-center py-2">
          <Spinner testID="txn-comments-spinner" />
        </View>
      ) : items.length === 0 ? (
        <Text testID="txn-comments-empty" className="text-sm text-neutral-500">
          No comments yet.
        </Text>
      ) : (
        <View testID="txn-comments-list" className="gap-2">
          {items.map((c) => {
            const isSystem = c.kind === 'system' || c.author_id === SYSTEM_AUTHOR;
            const name = isSystem ? 'System' : (nameByUserId[c.author_id] ?? c.author_id);
            return (
              <View
                key={c.comment_id}
                testID={`comment-${c.comment_id}`}
                className={
                  isSystem
                    ? 'rounded-md border border-neutral-200 bg-neutral-100 p-3'
                    : 'rounded-md border border-neutral-200 bg-white p-3'
                }
              >
                <Text
                  className={
                    isSystem
                      ? 'mb-1 text-xs font-semibold uppercase tracking-wider text-neutral-500'
                      : 'mb-1 text-xs font-semibold text-neutral-700'
                  }
                >
                  {name}
                </Text>
                <Text className="text-sm text-neutral-900">{c.body}</Text>
              </View>
            );
          })}
        </View>
      )}

      {isMember ? (
        <View className="mt-3 flex-row gap-2">
          <TextInput
            testID="txn-comment-input"
            value={draft}
            onChangeText={setDraft}
            placeholder="Add a comment"
            multiline
            className="flex-1 rounded-md border border-neutral-300 bg-white p-2 text-sm text-neutral-900"
          />
          <Pressable
            testID="txn-comment-post"
            onPress={onPost}
            disabled={post.isPending || !draft.trim()}
            className={
              post.isPending || !draft.trim()
                ? 'items-center justify-center rounded-md bg-neutral-300 px-3'
                : 'items-center justify-center rounded-md bg-primary-600 px-3'
            }
          >
            <Text className="text-sm font-semibold text-white">Post</Text>
          </Pressable>
        </View>
      ) : null}
    </Card>
  );
}
