import { useRef } from 'react';
import { GITHUB_REPO_URL, GitHubMark, SELF_HOSTING_GUIDE_URL } from '@/components/blocks/github';
import { Mascot } from '@/components/blocks/mascot';
import { Button } from '@/components/ui/button';
import { track } from '@/lib/analytics';
import { useOnceVisible } from '@/lib/useOnceVisible';

export function OpenSourceSection() {
  const sectionRef = useRef<HTMLElement | null>(null);
  useOnceVisible(sectionRef, () => track('landing_open_source_section_viewed'));

  return (
    <section
      ref={sectionRef}
      aria-labelledby="open-source-heading"
      className="relative bg-background pb-24 pt-16 md:pb-32 md:pt-24"
    >
      <div
        aria-hidden
        className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-border to-transparent"
      />
      <div className="mx-auto flex max-w-5xl flex-col gap-10 px-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="max-w-2xl">
          <h2
            id="open-source-heading"
            className="text-balance font-display text-3xl font-semibold tracking-tight md:text-4xl"
          >
            Read every line. Run it yourself.
          </h2>
          <p className="mt-4 max-w-xl text-pretty text-base text-muted-foreground md:text-lg">
            Pumpkit is open source under AGPL-3.0. Self-host it on your own server, or use
            pumpkit.io and skip the setup.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Button asChild className="gap-2">
              <a href={GITHUB_REPO_URL} onClick={() => track('landing_open_source_github_clicked')}>
                <GitHubMark className="size-4" />
                View on GitHub
              </a>
            </Button>
            <Button asChild variant="outline">
              <a
                href={SELF_HOSTING_GUIDE_URL}
                onClick={() => track('landing_open_source_self_hosting_clicked')}
              >
                Self-hosting guide
              </a>
            </Button>
          </div>
        </div>
        <Mascot animation="detective" className="self-end sm:self-auto" />
      </div>
    </section>
  );
}
