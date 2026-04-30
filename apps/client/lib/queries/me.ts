/**
 * TanStack Query hooks for the ``/v1/me`` feature.
 *
 * - ``useDeleteMyAccount`` — soft-deactivates the user; the server
 *   then disables the Cognito user and global-signs-out, so the
 *   next API call from this client will already 401.
 * - ``useExportMyData`` — returns the full data export blob. Subject
 *   to the server-side 1-per-24h cooldown.
 * - ``useUpdateMyProfile`` — change the requester's display name.
 */
import { useMutation } from '@tanstack/react-query';

import type { ExportResponse, MeProfileSlim } from '@contricool/client-sdk';

import { apiClient } from '~/lib/api';

export type { ExportResponse, MeProfileSlim } from '@contricool/client-sdk';

export function useDeleteMyAccount() {
  return useMutation<void, Error, void>({
    mutationFn: async () => {
      await apiClient.DELETE('/me', {});
    },
  });
}

export function useExportMyData() {
  return useMutation<ExportResponse, Error, void>({
    mutationFn: async () => {
      const r = await apiClient.GET('/me/export', {});
      return r.data as ExportResponse;
    },
  });
}

export function useUpdateMyProfile() {
  return useMutation<MeProfileSlim, Error, { name: string }>({
    mutationFn: async (input) => {
      const r = await apiClient.PATCH('/me/profile', { body: input });
      return r.data as MeProfileSlim;
    },
  });
}
