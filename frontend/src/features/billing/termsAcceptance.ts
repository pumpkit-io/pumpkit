import type { TermsAcceptance } from '@/services/billingService';

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
