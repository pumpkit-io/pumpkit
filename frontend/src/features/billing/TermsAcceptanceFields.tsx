import type { ReactNode } from 'react';
import { PRIVACY_PATH, TERMS_PATH } from '@/features/legal/documents';
import type { TermsAcceptance } from './termsAcceptance';

// The onerous clauses arts. 1341 and 1342 c.c. require a business to approve one by one.
// Number, title and anchor must match the headings in the English Terms.
const ONEROUS_CLAUSES = [
  { number: 9, title: 'Suspension and termination by the Operator', anchor: 'suspension' },
  { number: 11, title: 'Automatic renewal and cancellation', anchor: 'renewal' },
  { number: 13, title: 'No refunds', anchor: 'refunds' },
  { number: 15, title: 'Limitation of liability', anchor: 'liability' },
  { number: 18, title: 'Changes to these Terms', anchor: 'changes' },
  { number: 20, title: 'Competent court (Court of Pesaro for businesses)', anchor: 'courts' },
];

const CLAUSES_ID = 'terms-acceptance-onerous-clauses';

// A new tab keeps the dialog and the boxes already ticked.
function DocumentLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-foreground underline underline-offset-4 hover:opacity-70"
    >
      {children}
    </a>
  );
}

function Box({
  checked,
  onChange,
  describedBy,
  children,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  describedBy?: string;
  children: ReactNode;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        aria-describedby={describedBy}
        className="mt-0.5 h-4 w-4 shrink-0 cursor-pointer accent-primary"
      />
      <span>{children}</span>
    </label>
  );
}

/** The three boxes a User ticks before every Checkout (ADR 0010). */
export function TermsAcceptanceFields({
  value,
  onChange,
}: {
  value: TermsAcceptance;
  onChange: (value: TermsAcceptance) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Accept the Terms"
      className="space-y-3 rounded-xl border border-border p-4 font-sans text-xs leading-5 text-muted-foreground"
    >
      <Box
        checked={value.acceptedTerms}
        onChange={(acceptedTerms) => onChange({ ...value, acceptedTerms })}
      >
        I accept the <DocumentLink href={TERMS_PATH}>Terms</DocumentLink> and have read the{' '}
        <DocumentLink href={PRIVACY_PATH}>Privacy Policy</DocumentLink>.
      </Box>
      <Box
        checked={value.requestedImmediateStart}
        onChange={(requestedImmediateStart) => onChange({ ...value, requestedImmediateStart })}
      >
        I ask for the service to start immediately, and acknowledge I lose the 14-day{' '}
        <DocumentLink href={`${TERMS_PATH}#withdrawal`}>right of withdrawal</DocumentLink> once the
        paid period starts.
      </Box>
      <div>
        <Box
          checked={value.approvedSpecificClauses}
          onChange={(approvedSpecificClauses) => onChange({ ...value, approvedSpecificClauses })}
          describedBy={CLAUSES_ID}
        >
          Under arts. 1341 and 1342 of the Italian Civil Code, I specifically approve these clauses
          of the Terms:
        </Box>
        <ul id={CLAUSES_ID} className="mt-1.5 space-y-0.5 pl-7">
          {ONEROUS_CLAUSES.map(({ number, title, anchor }) => (
            <li key={anchor}>
              <DocumentLink href={`${TERMS_PATH}#${anchor}`}>
                {number}. {title}
              </DocumentLink>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
