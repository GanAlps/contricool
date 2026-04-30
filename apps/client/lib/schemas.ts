import { z } from 'zod';

const email = z.string().trim().toLowerCase().email('Enter a valid email');
const password = z.string().min(10, 'At least 10 characters');
const code = z.string().regex(/^\d{6}$/, 'Enter the 6-digit code');
const name = z.string().trim().min(1, 'Required').max(128, 'Too long (max 128)');
const currency = z.enum(['USD', 'INR']);
const phone = z
  .string()
  .regex(/^\+[1-9]\d{1,14}$/, 'Use E.164 format, e.g. +14155552671')
  .optional()
  .or(z.literal(''));

export const LoginSchema = z.object({
  email,
  password: z.string().min(1, 'Password is required'),
});
export type LoginValues = z.infer<typeof LoginSchema>;

export const SignupSchema = z
  .object({
    email,
    password,
    confirm_password: z.string(),
    name,
    currency,
    phone,
  })
  .refine((d) => d.password === d.confirm_password, {
    path: ['confirm_password'],
    message: 'Passwords do not match',
  });
export type SignupValues = z.infer<typeof SignupSchema>;

export const VerifyEmailSchema = z.object({ email, code });
export type VerifyEmailValues = z.infer<typeof VerifyEmailSchema>;

export const ForgotPasswordSchema = z.object({ email });
export type ForgotPasswordValues = z.infer<typeof ForgotPasswordSchema>;

// Lenient by design: the backend distinguishes phone-shape (400
// INVALID_IDENTIFIER) from malformed-email (422 VALIDATION_ERROR).
// Doing client-side `.email()` validation would coalesce both into a
// single client error, losing the per-shape copy.
export const AddFriendSchema = z.object({
  email: z.string().trim().min(1, 'Required'),
});
export type AddFriendValues = z.infer<typeof AddFriendSchema>;

// ---------------------------------------------------------------------------
// Transactions (Phase 4c).
//
// Structural validation only — the server is the authoritative
// validator (Phase 4b's `service.validate_create_payload` enforces
// the per-method invariants and returns stable error codes). We do
// the obvious checks here to give the form a fast-fail UX without
// duplicating the backend's validation logic.
// ---------------------------------------------------------------------------

// User-id is whatever the friends-list API hands us; the server is
// the authoritative validator. Client-side check is "non-empty" —
// any stricter shape would risk rejecting legitimate ids returned
// by an in-flight backend evolution (e.g. UUID-shaped service ids
// during a future migration).
const ULID_PATTERN = /^.{1,128}$/;

const decimalAmount = z
  .string()
  .trim()
  .regex(/^\d+(\.\d{1,2})?$/, 'Enter a number with up to 2 decimal places')
  .refine((v) => Number(v) > 0, 'Must be positive');

const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'Use the YYYY-MM-DD format');

const ulid = z.string().regex(ULID_PATTERN, 'Invalid user id');

const TxnMemberZ = z.object({
  user_id: ulid,
  share: z.string().trim().optional().nullable(),
  percent: z.string().trim().optional().nullable(),
  owed_amount: z.string().trim().optional().nullable(),
});

// Payer paid_amount is filled from the form's `amount` field at
// submit time (single-payer at MVP), so the schema accepts a
// permissive shape here — server validation is authoritative.
const TxnPayerZ = z.object({
  user_id: ulid,
  paid_amount: z.string().trim(),
});

export const AddTransactionSchema = z
  .object({
    name: z.string().trim().min(1, 'Required').max(120, 'Too long'),
    type: z.enum(['expense', 'settlement']),
    amount: decimalAmount,
    currency: currency,
    txn_date: isoDate,
    note: z.string().max(500, 'Too long (max 500)').default(''),
    split_method: z.enum(['equal', 'amount', 'share', 'percent']),
    members: z.array(TxnMemberZ).min(2, 'Pick at least one friend').max(10, 'Max 10 members'),
    payers: z.array(TxnPayerZ).min(1).max(10),
  })
  .superRefine((data, ctx) => {
    // Settlement-type structural sanity (server has the authoritative
    // check; we surface it earlier as a UX win).
    if (data.type === 'settlement' && data.members.length !== 2) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['members'],
        message: 'Settlement must have exactly two members',
      });
    }
  });
export type AddTransactionValues = z.infer<typeof AddTransactionSchema>;

export const ResetPasswordSchema = z
  .object({
    email,
    code,
    new_password: password,
    confirm_password: z.string(),
  })
  .refine((d) => d.new_password === d.confirm_password, {
    path: ['confirm_password'],
    message: 'Passwords do not match',
  });
export type ResetPasswordValues = z.infer<typeof ResetPasswordSchema>;
