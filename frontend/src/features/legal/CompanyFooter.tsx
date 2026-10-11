import { Link } from 'react-router-dom';
import { cn } from '@/lib/utils';
import { PRIVACY_PATH, TERMS_PATH } from './documents';
import { OPERATOR } from './operator';

const LINK_CLASS = 'text-foreground underline-offset-4 transition-colors hover:underline';

/** The Operator's company details and the legal links, at the foot of every public page. */
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
            <li>
              <Link to={PRIVACY_PATH} className={LINK_CLASS}>
                Privacy Policy
              </Link>
            </li>
            <li>
              <Link to={TERMS_PATH} className={LINK_CLASS}>
                Terms
              </Link>
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
