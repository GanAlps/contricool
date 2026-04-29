import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '~/lib/api';
import type {
  AddFriendInput,
  AddFriendResponse,
  FriendBalance,
  ListFriendsResponse,
} from '~/lib/types';

/**
 * Centralised query keys for the friends feature.  Keep the keys here
 * so cache-invalidation lives next to the queries that produce them.
 */
export const friendsKeys = {
  all: ['friends'] as const,
  list: (limit: number) => ['friends', { limit }] as const,
  balance: (userId: string) => ['friend-balance', userId] as const,
};

const DEFAULT_LIST_LIMIT = 50;

export function useFriends() {
  return useQuery<ListFriendsResponse>({
    queryKey: friendsKeys.list(DEFAULT_LIST_LIMIT),
    queryFn: async () => {
      const r = await apiClient.GET('/friends', {
        params: { query: { limit: DEFAULT_LIST_LIMIT } },
      });
      // The SDK middleware throws ApiErrorException on non-2xx, so a
      // resolved promise with `data == null` cannot happen at runtime.
      return r.data as ListFriendsResponse;
    },
    staleTime: 30_000,
  });
}

export function useFriendBalance(userId: string) {
  return useQuery<FriendBalance>({
    queryKey: friendsKeys.balance(userId),
    queryFn: async () => {
      const r = await apiClient.GET('/friends/{user_id}/balance', {
        params: { path: { user_id: userId } },
      });
      return r.data as FriendBalance;
    },
    staleTime: 0,
    enabled: Boolean(userId),
  });
}

export function useAddFriend() {
  const qc = useQueryClient();
  return useMutation<AddFriendResponse, Error, AddFriendInput>({
    mutationFn: async (input) => {
      const r = await apiClient.POST('/friends/add', { body: input });
      return r.data as AddFriendResponse;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: friendsKeys.all });
    },
  });
}

export function useRemoveFriend() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: async (userId) => {
      await apiClient.DELETE('/friends/{user_id}', {
        params: { path: { user_id: userId } },
      });
    },
    onSuccess: (_data, userId) => {
      qc.invalidateQueries({ queryKey: friendsKeys.all });
      qc.removeQueries({ queryKey: friendsKeys.balance(userId) });
    },
  });
}
