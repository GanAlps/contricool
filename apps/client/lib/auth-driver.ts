/**
 * AuthDriver interface — Metro's platform resolver picks
 * `auth-driver.web.ts` on web; native ships `auth-driver.native.ts`
 * in a later phase (likely Amplify-backed).
 */

import type {
  ForgotPasswordResponse,
  LoginInput,
  LoginResponse,
  RefreshResponse,
  ResendEmailCodeResponse,
  ResetPasswordInput,
  ResetPasswordResponse,
  SignupInput,
  SignupResponse,
  VerifyEmailInput,
  VerifyEmailResponse,
} from './types';

export interface AuthDriver {
  signUp(input: SignupInput): Promise<SignupResponse>;
  verifyEmail(input: VerifyEmailInput): Promise<VerifyEmailResponse>;
  resendEmailCode(input: { email: string }): Promise<ResendEmailCodeResponse>;
  signIn(input: LoginInput): Promise<LoginResponse>;
  refreshSession(): Promise<RefreshResponse>;
  signOut(): Promise<void>;
  forgotPassword(input: { email: string }): Promise<ForgotPasswordResponse>;
  resetPassword(input: ResetPasswordInput): Promise<ResetPasswordResponse>;
}
