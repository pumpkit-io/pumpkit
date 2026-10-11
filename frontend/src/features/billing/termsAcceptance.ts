/** The three boxes a User ticks before every Checkout (ADR 0010). */
export interface TermsAcceptance {
  acceptedTerms: boolean;
  requestedImmediateStart: boolean;
  approvedSpecificClauses: boolean;
}

export const NOTHING_ACCEPTED: TermsAcceptance = {
  acceptedTerms: false,
  requestedImmediateStart: false,
  approvedSpecificClauses: false,
};

export function acceptsAll(acceptance: TermsAcceptance): boolean {
  return (
    acceptance.acceptedTerms &&
    acceptance.requestedImmediateStart &&
    acceptance.approvedSpecificClauses
  );
}
