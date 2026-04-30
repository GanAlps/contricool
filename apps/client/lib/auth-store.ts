import { create } from 'zustand';

// Extensionless import: Metro's platform resolver picks
// `auth-driver.web.ts` on web and `auth-driver.native.ts` on native
// (the native impl ships in a later phase). Vitest is configured
// (vitest.config.ts) to prefer `.web.ts` so tests resolve to the web
// implementation just like Metro does on the web target.
import driver from './auth-driver';
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
  /** Phase 2e: SDK middleware calls this after a successful refresh. */
  _setTokensFromRefresh: (accessToken: string, idToken: string) => void;
  /** Patch the cached user (e.g. after a settings rename). */
  patchUser: (patch: Partial<AuthUser>) => void;
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
    let driverErr: unknown = null;
    try {
      await driver.signOut();
    } catch (e) {
      driverErr = e;
    }
    // Always clear local state regardless of server response, then
    // re-throw so the caller can surface a toast (R8.4).
    get()._clear();
    if (driverErr) {
      throw driverErr;
    }
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

  _setTokensFromRefresh: (accessToken, idToken) => {
    const u = decodeIdToken(idToken);
    set({ accessToken, idToken, user: u });
  },

  patchUser: (patch) => {
    const current = get().user;
    if (!current) {
      return;
    }
    set({ user: { ...current, ...patch } });
  },

  _clear: () =>
    set({
      user: null,
      accessToken: null,
      idToken: null,
      loading: false,
    }),
}));
