import { useEffect, useState, type SVGProps } from 'react';

// Where the code lives, which is the same for every Instance.
export const GITHUB_REPO_URL = 'https://github.com/pumpkit-io/pumpkit';
export const SELF_HOSTING_GUIDE_URL = `${GITHUB_REPO_URL}/blob/main/docs/self-hosting.md`;

const GITHUB_REPO_API = 'https://api.github.com/repos/pumpkit-io/pumpkit';

// A count that arrives later than this would shift the nav after the visitor has read it.
const STARS_TIMEOUT_MS = 4000;

const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 });

/** Formats a star count the way GitHub does: 87, 1.2k, 12k. */
export function formatStars(count: number): string {
  return compact.format(count).toLowerCase();
}

/** The repository's stargazer count, or null while it loads or when GitHub can't answer. */
export function useGitHubStars(): number | null {
  const [stars, setStars] = useState<number | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), STARS_TIMEOUT_MS);
    fetch(GITHUB_REPO_API, {
      signal: controller.signal,
      headers: { Accept: 'application/vnd.github+json' },
    })
      .then((response) => (response.ok ? response.json() : null))
      .then((repo: { stargazers_count?: unknown } | null) => {
        if (typeof repo?.stargazers_count === 'number') setStars(repo.stargazers_count);
      })
      .catch(() => {})
      .finally(() => window.clearTimeout(timeout));
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, []);

  return stars;
}

export function GitHubMark(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden focusable="false" {...props}>
      <path d="M12 .3a12 12 0 0 0-3.8 23.4c.6.1.8-.3.8-.6v-2.2c-3.3.7-4-1.4-4-1.4-.6-1.4-1.4-1.8-1.4-1.8-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.8 1.3 3.5 1 0-.8.4-1.3.7-1.6-2.7-.3-5.5-1.3-5.5-6 0-1.2.5-2.3 1.3-3.1-.2-.4-.6-1.6 0-3.2 0 0 1-.3 3.4 1.2a11.5 11.5 0 0 1 6 0c2.3-1.5 3.3-1.2 3.3-1.2.6 1.6.2 2.8.1 3.2.8.8 1.3 1.9 1.3 3.2 0 4.6-2.8 5.6-5.5 5.9.5.4.9 1.1.9 2.2v3.3c0 .3.1.7.8.6A12 12 0 0 0 12 .3" />
    </svg>
  );
}
