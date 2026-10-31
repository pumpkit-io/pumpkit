import { useInstance } from '@/features/instance/useInstance';
import type { OperatorDetails } from '@/lib/instance';
import { cn } from '@/lib/utils';
import { LegalLinks } from './LegalLinks';

const LINK_CLASS = 'text-foreground underline-offset-4 transition-colors hover:underline';

function copyrightLine({ name, vat_id }: OperatorDetails): string {
  const owner = `© ${new Date().getFullYear()} ${name}`;
  return vat_id ? `${owner} · VAT ID ${vat_id}` : owner;
}

/**
 * The Operator's name and VAT ID, the legal links, Cookie settings and the support address, at the
 * foot of every public page. Each part shows only where the Instance has it (ADR 0011).
 */
export function CompanyFooter({ className }: { className?: string }) {
  const { operator, analytics, support_email } = useInstance();
  if (!operator && !analytics && !support_email) return null;
  return (
    <footer
      className={cn('border-t border-border px-6 py-8 text-xs text-muted-foreground', className)}
    >
      <div
        className={cn(
          'mx-auto flex max-w-6xl flex-col gap-4 sm:flex-row sm:items-center',
          operator ? 'sm:justify-between' : 'sm:justify-end',
        )}
      >
        {operator && <p className="leading-5">{copyrightLine(operator)}</p>}
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
