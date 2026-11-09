import { useId, type ReactNode } from 'react';
import type { LegalLanguage } from '@/features/legal/documents';
import { TEXT_LINK_CLASS } from '@/features/legal/textLink';

const CLAUSES = [
  {
    number: 9,
    anchor: 'suspension',
    en: 'Suspension and termination by the Operator',
    it: 'Sospensione e risoluzione da parte del Gestore',
  },
  {
    number: 16,
    anchor: 'liability',
    en: 'Limitation of liability',
    it: 'Limitazione di responsabilità',
  },
  {
    number: 19,
    anchor: 'changes',
    en: 'Changes to these Terms',
    it: 'Modifiche ai presenti Termini',
  },
  { number: 21, anchor: 'courts', en: 'Competent court', it: 'Foro competente' },
];

export interface CouponAcceptance {
  acceptedTerms: boolean;
  approvedSpecificClauses: boolean;
}

export function CouponAcceptanceFields({
  language,
  value,
  onChange,
  disabled,
}: {
  language: LegalLanguage;
  value: CouponAcceptance;
  onChange: (value: CouponAcceptance) => void;
  disabled: boolean;
}) {
  const id = useId();
  const italian = language === 'it';
  const terms = italian ? '/it/terms' : '/terms';
  const link = (path: string, text: ReactNode) => (
    <a href={path} target="_blank" rel="noopener noreferrer" className={TEXT_LINK_CLASS}>
      {text}
    </a>
  );
  return (
    <fieldset
      disabled={disabled}
      lang={language}
      aria-label="Accept the Terms for free access"
      className="space-y-3 rounded-xl border border-border p-4 text-xs leading-5 text-muted-foreground"
    >
      <label className="flex min-h-11 cursor-pointer items-start gap-3">
        <input
          type="checkbox"
          className="mt-1 h-4 w-4 shrink-0 accent-primary"
          checked={value.acceptedTerms}
          onChange={(event) => onChange({ ...value, acceptedTerms: event.target.checked })}
        />
        <span>
          {italian ? (
            <>
              Accetto i {link(terms, 'Termini')} e ho letto l’
              {link('/it/privacy', 'Informativa sulla privacy')}.
            </>
          ) : (
            <>
              I accept the {link(terms, 'Terms')} and have read the{' '}
              {link('/privacy', 'Privacy Policy')}.
            </>
          )}
        </span>
      </label>
      <label className="flex min-h-11 cursor-pointer items-start gap-3">
        <input
          type="checkbox"
          className="mt-1 h-4 w-4 shrink-0 accent-primary"
          checked={value.approvedSpecificClauses}
          aria-describedby={id}
          onChange={(event) =>
            onChange({ ...value, approvedSpecificClauses: event.target.checked })
          }
        />
        <span id={id}>
          {italian
            ? 'Ai sensi degli artt. 1341 e 1342 del Codice civile, approvo specificamente le clausole '
            : 'Under arts. 1341 and 1342 of the Italian Civil Code, I specifically approve clauses '}
          {CLAUSES.map((clause, index) => (
            <span key={clause.number}>
              {index === 0 ? '' : index === CLAUSES.length - 1 ? (italian ? ' e ' : ' and ') : ', '}
              {link(`${terms}#${clause.anchor}`, `${clause.number} (${clause[language]})`)}
            </span>
          ))}
          .
        </span>
      </label>
    </fieldset>
  );
}
