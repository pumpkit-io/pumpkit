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
  /** ISO date shown as "Last updated"; bump it with every change to the text. */
  lastUpdated: string;
  markdown: string;
  /** Path of the same document in the other language. */
  alternatePath: string;
}

export const PRIVACY_PATH = '/privacy';
export const TERMS_PATH = '/terms';
const PRIVACY_IT_PATH = '/it/privacy';
const TERMS_IT_PATH = '/it/terms';

/** Every legal document, served at its own public route: a new document is a Markdown file plus an entry here. */
export const LEGAL_DOCUMENTS: LegalDocument[] = [
  {
    path: PRIVACY_PATH,
    language: 'en',
    title: 'Privacy Policy',
    lastUpdated: '2026-10-11',
    markdown: privacyEn,
    alternatePath: PRIVACY_IT_PATH,
  },
  {
    path: TERMS_PATH,
    language: 'en',
    title: 'Terms',
    lastUpdated: '2026-10-11',
    markdown: termsEn,
    alternatePath: TERMS_IT_PATH,
  },
  {
    path: PRIVACY_IT_PATH,
    language: 'it',
    title: 'Informativa sulla privacy',
    lastUpdated: '2026-10-11',
    markdown: privacyIt,
    alternatePath: PRIVACY_PATH,
  },
  {
    path: TERMS_IT_PATH,
    language: 'it',
    title: 'Termini',
    lastUpdated: '2026-10-11',
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
