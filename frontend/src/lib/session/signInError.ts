/**
 * The `?error=` codes the sign-in page shows a message for. The backend, the
 * sign-in callbacks and the Session module (after an end) redirect there with
 * one of these.
 */
export const SIGN_IN_ERROR = {
  invalidMagicLink: 'invalid_magic_link',
  accountSuspended: 'account_suspended',
  signInFailed: 'sign_in_failed',
} as const;

export type SignInErrorCode = (typeof SIGN_IN_ERROR)[keyof typeof SIGN_IN_ERROR];

const CODES: ReadonlySet<string> = new Set(Object.values(SIGN_IN_ERROR));

export function isSignInErrorCode(code: string | null): code is SignInErrorCode {
  return code !== null && CODES.has(code);
}

/** The sign-in page, showing the message for `error` when given. */
export function signInPath(error?: SignInErrorCode): string {
  return error ? `/login?error=${error}` : '/login';
}
