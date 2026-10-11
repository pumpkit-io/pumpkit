import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { CookieSettingsButton } from '@/features/analyticsConsent/CookieSettingsButton';
import { useInstance } from '@/features/instance/useInstance';
import { LEGAL_LINKS } from './documents';

/**
 * The legal links where the Instance has Operator details, and Cookie settings where it has
 * analytics (ADR 0011); with neither, nothing. `children` are further list items after them.
 */
export function LegalLinks({
  className,
  listClassName,
  linkClassName,
  newTab = false,
  children,
}: {
  className?: string;
  listClassName?: string;
  linkClassName?: string;
  newTab?: boolean;
  children?: ReactNode;
}) {
  const { operator, analytics } = useInstance();
  if (!operator && !analytics) return null;
  return (
    <nav aria-label={operator ? 'Legal' : 'Cookies'} className={className}>
      <ul className={listClassName}>
        {operator &&
          LEGAL_LINKS.map(({ path, label }) => (
            <li key={path}>
              {newTab ? (
                <a href={path} target="_blank" rel="noopener noreferrer" className={linkClassName}>
                  {label}
                </a>
              ) : (
                <Link to={path} className={linkClassName}>
                  {label}
                </Link>
              )}
            </li>
          ))}
        {analytics && (
          <li>
            <CookieSettingsButton className={linkClassName} />
          </li>
        )}
        {children}
      </ul>
    </nav>
  );
}
