import { Link } from 'react-router-dom';
import { CookieSettingsButton } from '@/features/analyticsConsent/CookieSettingsButton';
import { useInstance } from '@/features/instance/useInstance';
import type { OperatorDetails } from '@/lib/instance';
import { cn } from '@/lib/utils';
import { LEGAL_LINKS } from './documents';

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
 * The Operator's company details and legal links, and Cookie settings, at the foot of every
 * public page. Each part shows only where the Instance has it (ADR 0011); with neither, no footer.
 */
export function CompanyFooter({ className }: { className?: string }) {
  const { operator, analytics } = useInstance();
  if (!operator && !analytics) return null;
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
        <nav aria-label={operator ? 'Legal' : 'Cookies'}>
          <ul className="flex flex-wrap gap-x-5 gap-y-2">
            {operator &&
              LEGAL_LINKS.map(({ path, label }) => (
                <li key={path}>
                  <Link to={path} className={LINK_CLASS}>
                    {label}
                  </Link>
                </li>
              ))}
            {analytics && (
              <li>
                <CookieSettingsButton className={LINK_CLASS} />
              </li>
            )}
            {operator && (
              <li>
                <a href={`mailto:${operator.support_email}`} className={LINK_CLASS}>
                  {operator.support_email}
                </a>
              </li>
            )}
          </ul>
        </nav>
      </div>
    </footer>
  );
}
