import privacyEn from './documents/privacy.en.md?raw';
import privacyIt from './documents/privacy.it.md?raw';
import termsEn from './documents/terms.en.md?raw';
import termsIt from './documents/terms.it.md?raw';

export type LegalLanguage = 'en' | 'it';

export interface LegalDocument {
  path: string;
  language: LegalLanguage;
  /** The page heading, also used for the browser title. */
  title: string;
  /** ISO date shown as "Last updated". */
  lastUpdated: string;
  markdown: string;
  /** Path of the same document in the other language. */
  alternatePath: string;
}

export const PRIVACY_PATH = '/privacy';
export const TERMS_PATH = '/terms';
const PRIVACY_IT_PATH = '/it/privacy';
const TERMS_IT_PATH = '/it/terms';

/** The English legal documents the footers link to, in display order. */
export const LEGAL_LINKS = [
  { path: PRIVACY_PATH, label: 'Privacy Policy' },
  { path: TERMS_PATH, label: 'Terms' },
];

// Bump with every change to a document's text; both languages share the date.
// TERMS_LAST_UPDATED must equal the backend's TERMS_VERSION.
const PRIVACY_LAST_UPDATED = '2026-10-11';
const TERMS_LAST_UPDATED = '2026-10-11';

/** Every legal document, served at its own public route: a new document is a Markdown file plus an entry here. */
export const LEGAL_DOCUMENTS: LegalDocument[] = [
  {
    path: PRIVACY_PATH,
    language: 'en',
    title: 'Privacy Policy',
    lastUpdated: PRIVACY_LAST_UPDATED,
    markdown: privacyEn,
    alternatePath: PRIVACY_IT_PATH,
  },
  {
    path: TERMS_PATH,
    language: 'en',
    title: 'Terms',
    lastUpdated: TERMS_LAST_UPDATED,
    markdown: termsEn,
    alternatePath: TERMS_IT_PATH,
  },
  {
    path: PRIVACY_IT_PATH,
    language: 'it',
    title: 'Informativa sulla privacy',
    lastUpdated: PRIVACY_LAST_UPDATED,
    markdown: privacyIt,
    alternatePath: PRIVACY_PATH,
  },
  {
    path: TERMS_IT_PATH,
    language: 'it',
    title: 'Termini',
    lastUpdated: TERMS_LAST_UPDATED,
    markdown: termsIt,
    alternatePath: TERMS_PATH,
  },
];

/** The words the legal page shell needs in each language. */
export const LEGAL_LABELS: Record<
  LegalLanguage,
  { locale: string; lastUpdated: string; readInThisLanguage: string }
> = {
  en: { locale: 'en-GB', lastUpdated: 'Last updated', readInThisLanguage: 'Read in English' },
  it: {
    locale: 'it-IT',
    lastUpdated: 'Ultimo aggiornamento',
    readInThisLanguage: 'Leggi in italiano',
  },
};
