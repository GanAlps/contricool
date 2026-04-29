/**
 * Backend contract types for Phase 2c's /v1/auth/* endpoints.
 * These mirror the Pydantic shapes in apps/api/app/features/auth/models.py
 * and will be replaced by the generated `@contricool/client-sdk` types
 * in Phase 2e.
 */

export type Currency = 'USD' | 'INR';

export type AuthUser = {
  user_id: string;
  name: string;
  currency: Currency;
};

export type SignupInput = {
  email: string;
  password: string;
  name: string;
  currency: Currency;
  phone?: string;
};

export type SignupResponse = {
  user_id: string;
  status: 'PENDING_VERIFICATION';
};

export type VerifyEmailInput = {
  email: string;
  code: string;
};

export type VerifyEmailResponse = {
  email_verified: true;
  account_active: true;
};

export type ResendEmailCodeResponse = {
  status: 'RESENT';
};

export type LoginInput = {
  email: string;
  password: string;
};

export type LoginResponse = {
  access_token: string;
  id_token: string;
  expires_in: number;
  user: AuthUser;
};

export type RefreshResponse = {
  access_token: string;
  id_token: string;
  expires_in: number;
};

export type ForgotPasswordResponse = {
  status: 'RESET_CODE_SENT';
};

export type ResetPasswordInput = {
  email: string;
  code: string;
  new_password: string;
};

export type ResetPasswordResponse = {
  password_reset: true;
};

export type ApiErrorDetail = {
  field: string;
  issue: string;
};

export type ApiErrorEnvelope = {
  error: {
    code: string;
    message: string;
    request_id: string | null;
    details?: ApiErrorDetail[];
    retry_after?: number;
  };
};
