/**
 * N23 + N24: never log password, code, access/id tokens, or email
 * during auth flows.
 */

import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import { useAuthStore } from '~/lib/auth-store';

const SECRETS = [
  'P@ssword123!', // password
  '123456', // code
  'access-jwt', // access token
  'access-jwt-2',
  'id-jwt',
  'id-jwt-2',
  'a@b.com', // email
];

let calls: string[] = [];
const spies: Array<ReturnType<typeof vi.spyOn>> = [];

beforeAll(() => {
  for (const m of ['log', 'info', 'warn', 'error', 'debug'] as const) {
    spies.push(
      vi.spyOn(console, m).mockImplementation((...args: unknown[]) => {
        calls.push(args.map((a) => String(a)).join(' '));
      }),
    );
  }
});

afterAll(() => {
  for (const s of spies) s.mockRestore();
});

beforeEach(() => {
  calls = [];
  useAuthStore.getState()._clear();
});

afterEach(() => {
  useAuthStore.getState()._clear();
});

function assertNoSecrets(): void {
  for (const c of calls) {
    for (const secret of SECRETS) {
      expect(c, `console call leaked secret ${secret}: ${c}`).not.toContain(secret);
    }
  }
}

describe('logging redaction', () => {
  it('N23: happy-path login does not log password, tokens, or email', async () => {
    await useAuthStore.getState().signIn({ email: 'a@b.com', password: 'P@ssword123!' });
    assertNoSecrets();
  });

  it('N24: verify-email does not log the OTP code', async () => {
    await useAuthStore.getState().verifyEmail({ email: 'a@b.com', code: '123456' });
    assertNoSecrets();
  });

  it('refresh + signOut do not log tokens', async () => {
    await useAuthStore.getState().refreshSession();
    useAuthStore.setState({ accessToken: 'access-jwt' });
    await useAuthStore.getState().signOut();
    assertNoSecrets();
  });
});
