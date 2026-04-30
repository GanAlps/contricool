/**
 * Phase 2e: re-export typed shapes from the generated SDK.  The
 * Pydantic models in apps/api are the single source of truth; the
 * SDK is a typed mirror of them.
 *
 * A few inputs (signup, verify-email, reset-password) need a small
 * client-side rename because openapi-typescript emits the request-body
 * type without a friendly name; we alias here to keep screens
 * readable.
 */

import type {
  AddFriendRequest,
  AddFriendResponse,
  AuthUser,
  CreateTransactionRequest,
  Currency,
  ForgotPasswordResponse,
  FriendBalanceResponse,
  FriendItem,
  ListFriendsResponse,
  ListTransactionsResponse,
  RefreshResponse,
  ResendEmailCodeResponse,
  ResetPasswordRequest,
  ResetPasswordResponse,
  SignInRequest,
  SignInResponse,
  SignupRequest,
  SignupResponse,
  SplitMethod,
  Transaction,
  TransactionListItem,
  TransactionMember,
  TransactionPayer,
  TxnType,
  VerifyEmailRequest,
  VerifyEmailResponse,
} from '@contricool/client-sdk';

export type {
  AddFriendRequest,
  AddFriendResponse,
  AuthUser,
  CreateTransactionRequest,
  Currency,
  FriendBalanceResponse,
  FriendItem,
  ForgotPasswordResponse,
  ListFriendsResponse,
  ListTransactionsResponse,
  RefreshResponse,
  ResendEmailCodeResponse,
  ResetPasswordRequest,
  ResetPasswordResponse,
  SignInRequest,
  SignupRequest,
  SignupResponse,
  SplitMethod,
  Transaction,
  TransactionListItem,
  TransactionMember,
  TransactionPayer,
  TxnType,
  VerifyEmailRequest,
  VerifyEmailResponse,
};

// Renamed aliases for screen/driver readability.
export type LoginInput = SignInRequest;
export type LoginResponse = SignInResponse;
export type SignupInput = SignupRequest;
export type VerifyEmailInput = VerifyEmailRequest;
export type ResetPasswordInput = ResetPasswordRequest;
export type AddFriendInput = AddFriendRequest;
export type FriendBalance = FriendBalanceResponse;

// Phase 2c envelope wrapper still re-exported from lib/api for callers
// that need the type without importing the SDK.
export type { ApiError, ApiErrorDetail } from '@contricool/client-sdk';
