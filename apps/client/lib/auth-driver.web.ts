import { apiClient } from './api';
import type { AuthDriver } from './auth-driver-types';

/**
 * The SDK middleware throws `ApiErrorException` on non-2xx, so on
 * success `result.data` is always present.  The `data!` assertion is
 * sound — covered by the SDK's middleware tests.
 */
export const webAuthDriver: AuthDriver = {
  signUp: async (input) => {
    const r = await apiClient.POST('/auth/signup', { body: input });
    return r.data!;
  },
  verifyEmail: async (input) => {
    const r = await apiClient.POST('/auth/verify-email', { body: input });
    return r.data!;
  },
  resendEmailCode: async (input) => {
    const r = await apiClient.POST('/auth/resend-email-code', { body: input });
    return r.data!;
  },
  signIn: async (input) => {
    const r = await apiClient.POST('/auth/login', { body: input });
    return r.data!;
  },
  refreshSession: async () => {
    const r = await apiClient.POST('/auth/refresh');
    return r.data!;
  },
  signOut: async () => {
    await apiClient.POST('/auth/logout');
  },
  forgotPassword: async (input) => {
    const r = await apiClient.POST('/auth/forgot-password', { body: input });
    return r.data!;
  },
  resetPassword: async (input) => {
    const r = await apiClient.POST('/auth/reset-password', { body: input });
    return r.data!;
  },
};

export default webAuthDriver;
