import { useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Brand } from '@/components/brand/Brand';
import { useInstance } from '@/features/instance/useInstance';
import { CompanyFooter } from './CompanyFooter';
import { LEGAL_DOCUMENTS, LEGAL_LABELS, type LegalDocument } from './documents';
import { LegalMarkdown } from './LegalMarkdown';

function formatDate(isoDate: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(`${isoDate}T00:00:00Z`));
}

/** Gives the page the document's title and language while it is open. */
function useDocumentHead(title: string, language: string) {
  const { app_name } = useInstance();
  useEffect(() => {
    const root = document.documentElement;
    const previousTitle = document.title;
    const previousLang = root.getAttribute('lang');
    document.title = `${title} · ${app_name}`;
    root.setAttribute('lang', language);
    return () => {
      document.title = previousTitle;
      if (previousLang === null) root.removeAttribute('lang');
      else root.setAttribute('lang', previousLang);
    };
  }, [title, language, app_name]);
}

/** The browser cannot jump to a heading React renders after load, so this does it once the text is there. */
function useScrollToHash() {
  const { hash } = useLocation();
  useEffect(() => {
    if (!hash) return;
    // Instant, overriding the page's smooth scrolling: a long smooth scroll aims at where the
    // heading was when it started, and the page still shifts under it, so it stops short.
    document
      .getElementById(decodeURIComponent(hash.slice(1)))
      ?.scrollIntoView({ behavior: 'instant' });
  }, [hash]);
}

/** A public legal document: brand bar, the rendered Markdown and the company footer. */
export function LegalPage({ document: legalDocument }: { document: LegalDocument }) {
  const { title, language, lastUpdated, markdown, alternatePath } = legalDocument;
  const labels = LEGAL_LABELS[language];
  const { app_name } = useInstance();
  const alternate = LEGAL_DOCUMENTS.find((doc) => doc.path === alternatePath);
  useDocumentHead(title, language);
  useScrollToHash();

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <header className="mx-auto flex w-full max-w-3xl items-center justify-between px-6 py-5">
        <Link to="/" aria-label={app_name}>
          <Brand size="sm" />
        </Link>
        {alternate && (
          <Link
            to={alternate.path}
            lang={alternate.language}
            hrefLang={alternate.language}
            className="text-sm text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline"
          >
            {LEGAL_LABELS[alternate.language].readInThisLanguage}
          </Link>
        )}
      </header>
      <main className="mx-auto w-full max-w-3xl flex-1 px-6 pb-20 pt-10">
        <article className="text-[0.9375rem] text-muted-foreground">
          <h1 className="text-4xl font-normal leading-tight tracking-tight text-foreground">
            {title}
          </h1>
          <p className="mt-3 text-sm">
            {labels.lastUpdated}: {formatDate(lastUpdated, labels.locale)}
          </p>
          <LegalMarkdown markdown={markdown} />
        </article>
      </main>
      <CompanyFooter />
    </div>
  );
}
