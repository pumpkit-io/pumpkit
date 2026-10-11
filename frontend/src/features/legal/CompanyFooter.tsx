import { Link } from 'react-router-dom';
import { CookieSettingsButton } from '@/features/analyticsConsent/CookieSettingsButton';
import { cn } from '@/lib/utils';
import { LEGAL_LINKS } from './documents';
import { OPERATOR } from './operator';

const LINK_CLASS = 'text-foreground underline-offset-4 transition-colors hover:underline';

/** The Operator's company details, the legal links and Cookie settings, at the foot of every public page. */
export function CompanyFooter({ className }: { className?: string }) {
  return (
    <footer
      className={cn('border-t border-border px-6 py-8 text-xs text-muted-foreground', className)}
    >
      <div className="mx-auto flex max-w-6xl flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <address className="space-y-1 not-italic leading-5">
          <p className="font-medium text-foreground">{OPERATOR.name}</p>
          <p>{OPERATOR.address}</p>
          <p>
            VAT ID {OPERATOR.vatId} · REA {OPERATOR.rea} · Share capital {OPERATOR.shareCapital}
          </p>
          <p>PEC {OPERATOR.pec}</p>
        </address>
        <nav aria-label="Legal">
          <ul className="flex flex-wrap gap-x-5 gap-y-2">
            {LEGAL_LINKS.map(({ path, label }) => (
              <li key={path}>
                <Link to={path} className={LINK_CLASS}>
                  {label}
                </Link>
              </li>
            ))}
            <li>
              <CookieSettingsButton className={LINK_CLASS} />
            </li>
            <li>
              <a href={`mailto:${OPERATOR.supportEmail}`} className={LINK_CLASS}>
                {OPERATOR.supportEmail}
              </a>
            </li>
          </ul>
        </nav>
      </div>
    </footer>
  );
}
