import { Link } from 'react-router-dom';
import type { Variants } from 'framer-motion';
import { Brand } from '@/components/brand/Brand';
import { Button } from '@/components/ui/button';
import { AnimatedGroup } from '@/components/ui/animated-group';
import { track } from '@/lib/analytics';
import { APP_NAME } from '@/lib/app';

const transitionVariants: { item: Variants } = {
  item: {
    hidden: { opacity: 0, filter: 'blur(12px)', y: 12 },
    visible: { opacity: 1, filter: 'blur(0px)', y: 0, transition: { type: 'spring', bounce: 0.3, duration: 1.5 } },
  },
};

function HeroHeader() {
  return (
    <header className="fixed inset-x-0 top-0 z-20 border-b border-border/60 bg-background/80 backdrop-blur">
      <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <Link to="/" aria-label={`${APP_NAME} home`}>
          <Brand size="sm" />
        </Link>
        <div className="flex items-center gap-2">
          <a href="#pricing" className="hidden px-3 py-2 font-sans text-sm text-muted-foreground hover:text-foreground sm:inline">
            Pricing
          </a>
          <Button asChild size="sm" onClick={() => track('landing_nav_get_started_clicked')}>
            <Link to="/login">Get started</Link>
          </Button>
        </div>
      </nav>
    </header>
  );
}

export function HeroSection() {
  return (
    <>
      <HeroHeader />
      <main className="overflow-hidden">
        <section className="relative bg-canvas-radial pb-24 pt-36 md:pt-44">
          <div className="mx-auto max-w-4xl px-6 text-center">
            <AnimatedGroup variants={transitionVariants}>
              <h1 className="text-balance text-4xl font-normal tracking-tight text-foreground md:text-6xl">
                Your product headline goes here
              </h1>
              <p className="mx-auto mt-6 max-w-2xl text-balance font-sans text-lg text-muted-foreground">
                One or two sentences that explain what {APP_NAME} does and who it is for. Edit
                src/components/blocks/hero-section.tsx.
              </p>
              <div className="mt-10 flex items-center justify-center gap-3">
                <Button asChild size="lg" onClick={() => track('landing_hero_cta_clicked')}>
                  <Link to="/login">Get started</Link>
                </Button>
                <Button asChild size="lg" variant="outline">
                  <a href="#pricing">See pricing</a>
                </Button>
              </div>
            </AnimatedGroup>
          </div>
        </section>
      </main>
    </>
  );
}
