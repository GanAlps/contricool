import { create } from 'zustand';

import { setApiAuthAccessors } from './api';
import driver from './auth-driver.web';
import { decodeIdToken } from './id-token';
import type { AuthUser, ResetPasswordInput, SignupInput, VerifyEmailInput } from './types';

export type AuthState = {
  user: AuthUser | null;
  accessToken: string | null;
  idToken: string | null;
  loading: boolean;

  signIn: (input: { email: string; password: string }) => Promise<void>;
  signOut: () => Promise<void>;
  signUp: (input: SignupInput) => Promise<void>;
  verifyEmail: (input: VerifyEmailInput) => Promise<void>;
  resendEmailCode: (input: { email: string }) => Promise<void>;
  forgotPassword: (input: { email: string }) => Promise<void>;
  resetPassword: (input: ResetPasswordInput) => Promise<void>;
  refreshSession: () => Promise<void>;
  _clear: () => void;
};

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  accessToken: null,
  idToken: null,
  loading: true,

  signIn: async (input) => {
    const r = await driver.signIn(input);
    set({
      user: r.user,
      accessToken: r.access_token,
      idToken: r.id_token,
      loading: false,
    });
  },

  signOut: async () => {
    try {
      await driver.signOut();
    } catch {
      // Always clear local state regardless of server response.
    }
    get()._clear();
  },

  signUp: async (input) => {
    await driver.signUp(input);
  },

  verifyEmail: async (input) => {
    await driver.verifyEmail(input);
  },

  resendEmailCode: async (input) => {
    await driver.resendEmailCode(input);
  },

  forgotPassword: async (input) => {
    await driver.forgotPassword(input);
  },

  resetPassword: async (input) => {
    await driver.resetPassword(input);
  },

  refreshSession: async () => {
    set({ loading: true });
    try {
      const r = await driver.refreshSession();
      const u = decodeIdToken(r.id_token);
      set({
        user: u,
        accessToken: r.access_token,
        idToken: r.id_token,
        loading: false,
      });
    } catch {
      set({
        user: null,
        accessToken: null,
        idToken: null,
        loading: false,
      });
    }
  },

  _clear: () =>
    set({
      user: null,
      accessToken: null,
      idToken: null,
      loading: false,
    }),
}));

// Wire api → store. Module-load-time call so the cycle resolves once.
setApiAuthAccessors({
  getAccessToken: () => useAuthStore.getState().accessToken,
  setTokensFromRefresh: ({ access_token, id_token }) => {
    const u = decodeIdToken(id_token);
    useAuthStore.setState({ accessToken: access_token, idToken: id_token, user: u });
  },
  forceSignOut: async () => {
    useAuthStore.getState()._clear();
  },
});
