import type { ReactNode } from 'react';
import { AllowanceInfo } from './AllowanceInfo';
import type { OfferLine } from './planOffer';

/** An offer line's text with its info button, if it has one. */
export function OfferLineContent({ line }: { line: OfferLine }): ReactNode {
  return (
    <>
      {line.text}
      {line.info && <AllowanceInfo topic={line.info} className="ml-1" />}
    </>
  );
}
