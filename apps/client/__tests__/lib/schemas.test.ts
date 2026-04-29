import { describe, expect, it } from 'vitest';

import {
  ForgotPasswordSchema,
  LoginSchema,
  ResetPasswordSchema,
  SignupSchema,
  VerifyEmailSchema,
} from '~/lib/schemas';

describe('LoginSchema', () => {
  it('accepts a valid input and lowercases the email', () => {
    const r = LoginSchema.safeParse({ email: 'A@B.com  ', password: 'x' });
    expect(r.success).toBe(true);
    if (r.success) expect(r.data.email).toBe('a@b.com');
  });
  it('rejects invalid email', () => {
    expect(LoginSchema.safeParse({ email: 'oops', password: 'x' }).success).toBe(false);
  });
  it('rejects empty password', () => {
    expect(LoginSchema.safeParse({ email: 'a@b.com', password: '' }).success).toBe(false);
  });
});

describe('SignupSchema', () => {
  const base = {
    email: 'alice@example.com',
    password: 'P@ssword123!',
    confirm_password: 'P@ssword123!',
    name: 'Alice',
    currency: 'USD' as const,
  };
  it('accepts a valid input without phone', () => {
    expect(SignupSchema.safeParse(base).success).toBe(true);
  });
  it('accepts a valid input with E.164 phone', () => {
    expect(SignupSchema.safeParse({ ...base, phone: '+14155552671' }).success).toBe(true);
  });
  it('accepts an empty-string phone', () => {
    expect(SignupSchema.safeParse({ ...base, phone: '' }).success).toBe(true);
  });
  it('rejects malformed phone', () => {
    expect(SignupSchema.safeParse({ ...base, phone: '4155552671' }).success).toBe(false);
  });
  it('rejects mismatched confirm_password (N4)', () => {
    expect(SignupSchema.safeParse({ ...base, confirm_password: 'different' }).success).toBe(false);
  });
  it('rejects too-short password', () => {
    expect(
      SignupSchema.safeParse({ ...base, password: 'short', confirm_password: 'short' }).success,
    ).toBe(false);
  });
  it('rejects unknown currency', () => {
    expect(SignupSchema.safeParse({ ...base, currency: 'EUR' as 'USD' }).success).toBe(false);
  });
  it('rejects empty name', () => {
    expect(SignupSchema.safeParse({ ...base, name: '   ' }).success).toBe(false);
  });
});

describe('VerifyEmailSchema', () => {
  it('accepts a 6-digit code', () => {
    expect(VerifyEmailSchema.safeParse({ email: 'a@b.com', code: '123456' }).success).toBe(true);
  });
  it('rejects non-6-digit code', () => {
    expect(VerifyEmailSchema.safeParse({ email: 'a@b.com', code: '12abcd' }).success).toBe(false);
  });
});

describe('ForgotPasswordSchema', () => {
  it('accepts a valid email', () => {
    expect(ForgotPasswordSchema.safeParse({ email: 'a@b.com' }).success).toBe(true);
  });
});

describe('ResetPasswordSchema', () => {
  const base = {
    email: 'a@b.com',
    code: '123456',
    new_password: 'NewP@ssword123!',
    confirm_password: 'NewP@ssword123!',
  };
  it('accepts a valid input', () => {
    expect(ResetPasswordSchema.safeParse(base).success).toBe(true);
  });
  it('rejects mismatched confirm_password (N12)', () => {
    expect(ResetPasswordSchema.safeParse({ ...base, confirm_password: 'other' }).success).toBe(
      false,
    );
  });
  it('rejects too-short new_password', () => {
    expect(
      ResetPasswordSchema.safeParse({ ...base, new_password: 'short', confirm_password: 'short' })
        .success,
    ).toBe(false);
  });
  it('rejects bad code', () => {
    expect(ResetPasswordSchema.safeParse({ ...base, code: 'abc' }).success).toBe(false);
  });
});
