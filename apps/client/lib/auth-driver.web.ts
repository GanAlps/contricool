import { apiFetch } from './api';
import type { AuthDriver } from './auth-driver-types';

export const webAuthDriver: AuthDriver = {
  signUp: (input) => apiFetch('/auth/signup', { method: 'POST', json: input, auth: 'public' }),
  verifyEmail: (input) =>
    apiFetch('/auth/verify-email', { method: 'POST', json: input, auth: 'public' }),
  resendEmailCode: (input) =>
    apiFetch('/auth/resend-email-code', { method: 'POST', json: input, auth: 'public' }),
  signIn: (input) => apiFetch('/auth/login', { method: 'POST', json: input, auth: 'public' }),
  refreshSession: () =>
    apiFetch('/auth/refresh', { method: 'POST', auth: 'public', __noRetry: true }),
  signOut: () => apiFetch<void>('/auth/logout', { method: 'POST' }),
  forgotPassword: (input) =>
    apiFetch('/auth/forgot-password', { method: 'POST', json: input, auth: 'public' }),
  resetPassword: (input) =>
    apiFetch('/auth/reset-password', { method: 'POST', json: input, auth: 'public' }),
};

export default webAuthDriver;
