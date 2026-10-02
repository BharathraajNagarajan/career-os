const GENERIC_ERROR = "Sign-in failed. Please try again.";

const ERROR_MESSAGES: Record<string, string> = {
  invalid_state: "Sign-in could not be verified. Please try again.",
  idp_error: "Google sign-in was cancelled or failed. Please try again.",
  sign_in_failed: GENERIC_ERROR,
  account_conflict:
    "An account with this email already exists and cannot be linked automatically.",
  account_unavailable: "This account is not available for sign-in.",
  provider_unavailable: "Google is unreachable right now. Try again shortly.",
};

export const NOTICES: Record<string, string> = {
  account_deletion_requested:
    "Your account deletion has been requested. Your data will be removed shortly.",
};

export function signInErrorMessage(code: string | null): string | null {
  if (code === null) {
    return null;
  }
  return ERROR_MESSAGES[code] ?? GENERIC_ERROR;
}
