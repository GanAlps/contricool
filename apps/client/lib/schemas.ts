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
