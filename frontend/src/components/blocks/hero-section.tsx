import { Link } from 'react-router-dom';
import type { Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import { CTA_CLASSES } from '@/components/blocks/cta-classes';
import { CtaLabel } from '@/components/blocks/cta-label';
import { HeroHeadline } from '@/components/blocks/hero-headline';
import { HeroFrame } from '@/components/blocks/hero-frame';
import { LaunchVideo } from '@/components/blocks/launch-video';
import { Button } from '@/components/ui/button';
import { AnimatedGroup } from '@/components/ui/animated-group';
import { track } from '@/lib/analytics';

const transitionVariants: { item: Variants } = {
  item: {
    hidden: { opacity: 0, filter: 'blur(12px)', y: 12 },
    visible: {
      opacity: 1,
      filter: 'blur(0px)',
      y: 0,
      transition: { type: 'spring', bounce: 0.3, duration: 1.5 },
    },
  },
};

// The button and video wait for the text above them to settle first.
const staggeredVariants: { container: Variants; item: Variants } = {
  container: {
    visible: { transition: { staggerChildren: 0.05, delayChildren: 0.75 } },
  },
  ...transitionVariants,
};

export function HeroSection({
  ctaLabel,
  ctaNote,
}: {
  ctaLabel: string | null;
  ctaNote: string | null;
}) {
  return (
    <div className="overflow-hidden">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 isolate z-[2] hidden opacity-50 contain-strict lg:block"
      >
        <div className="absolute left-0 top-0 h-[80rem] w-[35rem] -translate-y-[350px] -rotate-45 rounded-full bg-[radial-gradient(68.54%_68.72%_at_55.02%_31.46%,hsl(var(--foreground)/.08)_0,hsl(var(--foreground)/.02)_50%,hsl(var(--foreground)/0)_80%)]" />
        <div className="absolute left-0 top-0 h-[80rem] w-56 -rotate-45 rounded-full bg-[radial-gradient(50%_50%_at_50%_50%,hsl(var(--foreground)/.06)_0,hsl(var(--foreground)/.02)_80%,transparent_100%)] [translate:5%_-50%]" />
        <div className="absolute left-0 top-0 h-[80rem] w-56 -translate-y-[350px] -rotate-45 bg-[radial-gradient(50%_50%_at_50%_50%,hsl(var(--foreground)/.04)_0,hsl(var(--foreground)/.02)_80%,transparent_100%)]" />
      </div>
      <section>
        <div className="relative pb-8 pt-28 md:pt-36">
          <div
            aria-hidden
            className="absolute inset-0 -z-10 size-full [background:radial-gradient(125%_125%_at_50%_100%,transparent_0%,hsl(var(--background))_75%)]"
          />
          <div className="mx-auto grid max-w-[88rem] gap-12 px-6 lg:grid-cols-12 lg:items-start lg:gap-10">
            <div className="text-center lg:col-span-5">
              <AnimatedGroup variants={transitionVariants}>
                <h1 className="landing-headline mx-auto max-w-3xl text-balance font-display font-semibold tracking-tight text-foreground">
                  <HeroHeadline />
                </h1>
                <p className="mx-auto mt-6 max-w-[48ch] text-pretty text-lg leading-relaxed text-muted-foreground">
                  Pumpkit writes and schedules posts on X for you. Posts sound like you, or like
                  your favorite X accounts. Use it in the web app, or use the MCP to let your agents
                  run it.
                </p>
              </AnimatedGroup>

              <AnimatedGroup
                variants={staggeredVariants}
                className="mt-8 flex flex-col items-center"
              >
                <Button
                  asChild
                  size="lg"
                  variant="solid"
                  className={cn(CTA_CLASSES, 'h-12 min-w-44 px-6')}
                >
                  <Link
                    to="/login"
                    aria-busy={ctaLabel === null}
                    aria-label={ctaLabel === null ? 'Loading signup options' : undefined}
                    aria-describedby={ctaNote ? 'hero-cta-note' : undefined}
                    onClick={() => track('landing_hero_cta_clicked')}
                  >
                    <CtaLabel pending={ctaLabel === null}>{ctaLabel}</CtaLabel>
                  </Link>
                </Button>
                <p
                  id="hero-cta-note"
                  aria-hidden={!ctaNote}
                  className={cn(
                    'mt-3 text-sm leading-relaxed text-muted-foreground',
                    !ctaNote && 'invisible',
                  )}
                >
                  {ctaNote ?? '\u00a0'}
                </p>
              </AnimatedGroup>
            </div>

            <AnimatedGroup
              variants={staggeredVariants}
              className="min-w-0 lg:col-span-7 xl:mt-[5px]"
            >
              <HeroFrame>
                <LaunchVideo />
              </HeroFrame>
            </AnimatedGroup>
          </div>
        </div>
      </section>
    </div>
  );
}
