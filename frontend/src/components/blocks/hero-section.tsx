import { useRef } from 'react';
import { Link } from 'react-router-dom';
import type { Variants } from 'framer-motion';
import { CtaFrame } from '@/components/blocks/cta-frame';
import { HeroFrame } from '@/components/blocks/hero-frame';
import { Button } from '@/components/ui/button';
import { AnimatedGroup } from '@/components/ui/animated-group';
import { track } from '@/lib/analytics';
import { useOnceVisible } from '@/lib/useOnceVisible';

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

// The button and screenshot wait for the text above them to settle first.
const staggeredVariants: { container: Variants; item: Variants } = {
  container: {
    visible: { transition: { staggerChildren: 0.05, delayChildren: 0.75 } },
  },
  ...transitionVariants,
};

export function HeroSection() {
  const screenshotRef = useRef<HTMLDivElement | null>(null);
  useOnceVisible(screenshotRef, () => track('landing_hero_screenshot_viewed'));

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
          <div className="mx-auto grid max-w-7xl gap-12 px-6 lg:grid-cols-12 lg:items-start lg:gap-10">
            <div className="lg:col-span-5">
              <AnimatedGroup variants={transitionVariants}>
                <h1 className="max-w-2xl text-balance font-display text-5xl font-semibold tracking-tighter text-foreground sm:text-6xl lg:text-[3.5rem] lg:leading-[1.05] xl:text-[4rem]">
                  Your ideas, in the style of the authors you admire.
                </h1>
                <p className="mt-6 max-w-xl text-pretty text-lg text-muted-foreground">
                  Write a brief, pick up to three X authors to learn style from, and get a post
                  ready to paste. Not quite right? Say what to change and get a new version.
                </p>
              </AnimatedGroup>

              <AnimatedGroup variants={staggeredVariants} className="mt-10 flex">
                <CtaFrame>
                  <Button asChild size="lg" className="rounded-xl px-5 text-base">
                    <Link to="/login" onClick={() => track('landing_hero_cta_clicked')}>
                      Start writing
                    </Link>
                  </Button>
                </CtaFrame>
              </AnimatedGroup>
            </div>

            <AnimatedGroup variants={staggeredVariants} className="min-w-0 lg:col-span-7">
              <HeroFrame>
                <div
                  ref={screenshotRef}
                  className="flex size-full items-center justify-center font-mono text-sm text-muted-foreground"
                >
                  [Product screenshot]
                </div>
              </HeroFrame>
            </AnimatedGroup>
          </div>
        </div>
      </section>
    </div>
  );
}
