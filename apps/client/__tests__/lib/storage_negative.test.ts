/**
 * N21: ContriCool client never persists access/id/refresh tokens to
 * any browser storage.  Refresh lives in the HttpOnly cookie set by
 * Phase 2c; access + id live in Zustand memory only.
 *
 * N22: hard reload after sign-out → refresh 401 → store empty.
 */

import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { useAuthStore } from '~/lib/auth-store';

import { server } from '../msw-handlers';

describe('storage negatives', () => {
  beforeEach(() => {
    useAuthStore.getState()._clear();
    localStorage.clear();
    sessionStorage.clear();
  });
  afterEach(() => {
    useAuthStore.getState()._clear();
    localStorage.clear();
    sessionStorage.clear();
  });

  it('N21: our app never writes anything to localStorage / sessionStorage', async () => {
    await useAuthStore.getState().signIn({ email: 'a@b.com', password: 'P@ssword123!' });
    await useAuthStore.getState().refreshSession();
    const ourKeys = (s: Storage): string[] => {
      const out: string[] = [];
      for (let i = 0; i < s.length; i++) {
        const k = s.key(i) ?? '';
        // MSW v2's cookie-store simulator persists HttpOnly-cookie state
        // in localStorage to mimic browser behaviour.  That key is a test
        // artefact, not application state.
        if (!k.startsWith('__msw-')) {
          out.push(k);
        }
      }
      return out;
    };
    expect(ourKeys(localStorage)).toEqual([]);
    expect(ourKeys(sessionStorage)).toEqual([]);
  });

  it('N22: hard reload after sign-out → store empty', async () => {
    server.use(
      http.post('http://localhost/v1/auth/refresh', () =>
        HttpResponse.json(
          { error: { code: 'REFRESH_FAILED', message: 'gone', request_id: 'r' } },
          { status: 401 },
        ),
      ),
    );
    await useAuthStore.getState().refreshSession();
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().accessToken).toBeNull();
    expect(localStorage.length).toBe(0);
  });
});
