import { useInstance } from '@/features/instance/useInstance';
import type { OperatorDetails } from '@/lib/instance';
import { cn } from '@/lib/utils';
import { LegalLinks } from './LegalLinks';

const LINK_CLASS = 'text-foreground underline-offset-4 transition-colors hover:underline';

function companyIdentifiers({ vat_id, rea, share_capital }: OperatorDetails): string {
  return [
    vat_id && `VAT ID ${vat_id}`,
    rea && `REA ${rea}`,
    share_capital && `Share capital ${share_capital}`,
  ]
    .filter(Boolean)
    .join(' · ');
}

/**
 * The Operator's company details and legal links, Cookie settings and the support address, at
 * the foot of every public page. Each part shows only where the Instance has it (ADR 0011).
 */
export function CompanyFooter({ className }: { className?: string }) {
  const { operator, analytics, support_email } = useInstance();
  if (!operator && !analytics && !support_email) return null;
  const identifiers = operator && companyIdentifiers(operator);
  return (
    <footer
      className={cn('border-t border-border px-6 py-8 text-xs text-muted-foreground', className)}
    >
      <div
        className={cn(
          'mx-auto flex max-w-6xl flex-col gap-4 sm:flex-row sm:items-start',
          operator ? 'sm:justify-between' : 'sm:justify-end',
        )}
      >
        {operator && (
          <address className="space-y-1 not-italic leading-5">
            <p className="font-medium text-foreground">{operator.name}</p>
            <p>{operator.address}</p>
            {identifiers && <p>{identifiers}</p>}
            {operator.pec && <p>PEC {operator.pec}</p>}
          </address>
        )}
        <LegalLinks listClassName="flex flex-wrap gap-x-5 gap-y-2" linkClassName={LINK_CLASS}>
          {support_email ? (
            <li>
              <a href={`mailto:${support_email}`} className={LINK_CLASS}>
                {support_email}
              </a>
            </li>
          ) : null}
        </LegalLinks>
      </div>
    </footer>
  );
}
