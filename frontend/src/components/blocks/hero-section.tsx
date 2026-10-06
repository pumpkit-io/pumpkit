import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import type { Variants } from 'framer-motion';
import { Menu, X } from 'lucide-react';
import { Brand } from '@/components/brand/Brand';
import { Button } from '@/components/ui/button';
import { AnimatedGroup } from '@/components/ui/animated-group';
import { track } from '@/lib/analytics';
import { APP_NAME } from '@/lib/app';
import { useOnceVisible } from '@/lib/useOnceVisible';
import { cn } from '@/lib/utils';

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

type Surface = 'desktop' | 'mobile';

const NAV_LINKS = [
  { label: 'Authors', href: '#authors', event: 'landing_nav_authors_clicked' },
  { label: 'Pricing', href: '#pricing', event: 'landing_nav_pricing_clicked' },
] as const;

const MOBILE_MENU_ID = 'landing-mobile-menu';

function HeroHeader() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [isScrolled, setIsScrolled] = useState(false);

  useEffect(() => {
    const handleScroll = () => setIsScrolled(window.scrollY > 50);
    handleScroll();
    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  const toggleMenu = () => {
    const next = !menuOpen;
    setMenuOpen(next);
    track(next ? 'landing_mobile_menu_opened' : 'landing_mobile_menu_closed');
  };

  const closeMenu = () => {
    setMenuOpen(false);
    track('landing_mobile_menu_closed');
  };

  const navLinks = (surface: Surface) =>
    NAV_LINKS.map(({ label, href, event }) => (
      <li key={href}>
        <a
          href={href}
          onClick={() => {
            track(event, { surface });
            if (surface === 'mobile') closeMenu();
          }}
          className="block text-muted-foreground duration-150 hover:text-foreground"
        >
          {label}
        </a>
      </li>
    ));

  const getStarted = (surface: Surface) => (
    <Button asChild size="sm" className={surface === 'mobile' ? 'w-full' : undefined}>
      <Link
        to="/login"
        onClick={() => {
          track('landing_nav_get_started_clicked', { surface });
          if (surface === 'mobile') closeMenu();
        }}
      >
        Get started
      </Link>
    </Button>
  );

  return (
    <header
      data-state={menuOpen ? 'active' : undefined}
      className="group fixed inset-x-0 top-0 z-20 px-2"
    >
      <div
        className={cn(
          'mx-auto mt-2 max-w-6xl border border-transparent px-6 transition-all duration-300 lg:px-12',
          isScrolled &&
            'max-w-4xl rounded-2xl border-border bg-background/50 backdrop-blur-lg lg:px-5',
        )}
      >
        <div className="relative flex items-center justify-between py-3 lg:py-4">
          <Link
            to="/"
            aria-label={`${APP_NAME} home`}
            onClick={() => track('landing_nav_logo_clicked')}
          >
            <Brand size="sm" />
          </Link>

          <nav aria-label="Main" className="absolute inset-0 m-auto hidden size-fit lg:block">
            <ul className="flex gap-8 text-sm">{navLinks('desktop')}</ul>
          </nav>

          <div className="hidden lg:block">{getStarted('desktop')}</div>

          <button
            type="button"
            onClick={toggleMenu}
            aria-label={menuOpen ? 'Close menu' : 'Open menu'}
            aria-expanded={menuOpen}
            aria-controls={MOBILE_MENU_ID}
            className="relative -m-2.5 -mr-4 block p-2.5 lg:hidden"
          >
            <Menu className="m-auto size-6 duration-200 group-data-[state=active]:rotate-180 group-data-[state=active]:scale-0 group-data-[state=active]:opacity-0" />
            <X className="absolute inset-0 m-auto size-6 -rotate-180 scale-0 opacity-0 duration-200 group-data-[state=active]:rotate-0 group-data-[state=active]:scale-100 group-data-[state=active]:opacity-100" />
          </button>
        </div>

        {menuOpen && (
          <nav
            id={MOBILE_MENU_ID}
            aria-label="Menu"
            className="mb-4 space-y-8 rounded-3xl border bg-background p-6 shadow-2xl shadow-zinc-300/20 dark:shadow-none lg:hidden"
          >
            <ul className="space-y-6 text-base">{navLinks('mobile')}</ul>
            {getStarted('mobile')}
          </nav>
        )}
      </div>
    </header>
  );
}

export function HeroSection() {
  const screenshotRef = useRef<HTMLDivElement | null>(null);
  useOnceVisible(screenshotRef, () => track('landing_hero_screenshot_viewed'));

  return (
    <>
      <HeroHeader />
      <main className="overflow-hidden">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 isolate z-[2] hidden opacity-50 contain-strict lg:block"
        >
          <div className="absolute left-0 top-0 h-[80rem] w-[35rem] -translate-y-[350px] -rotate-45 rounded-full bg-[radial-gradient(68.54%_68.72%_at_55.02%_31.46%,hsl(var(--foreground)/.08)_0,hsl(var(--foreground)/.02)_50%,hsl(var(--foreground)/0)_80%)]" />
          <div className="absolute left-0 top-0 h-[80rem] w-56 -rotate-45 rounded-full bg-[radial-gradient(50%_50%_at_50%_50%,hsl(var(--foreground)/.06)_0,hsl(var(--foreground)/.02)_80%,transparent_100%)] [translate:5%_-50%]" />
          <div className="absolute left-0 top-0 h-[80rem] w-56 -translate-y-[350px] -rotate-45 bg-[radial-gradient(50%_50%_at_50%_50%,hsl(var(--foreground)/.04)_0,hsl(var(--foreground)/.02)_80%,transparent_100%)]" />
        </div>
        <section>
          <div className="relative pt-28 md:pt-36">
            <div
              aria-hidden
              className="absolute inset-0 -z-10 size-full [background:radial-gradient(125%_125%_at_50%_100%,transparent_0%,hsl(var(--background))_75%)]"
            />
            <div className="mx-auto max-w-7xl px-6 text-center">
              <AnimatedGroup variants={transitionVariants}>
                <div className="mx-auto flex w-fit items-center rounded-full border bg-muted px-4 py-1.5 shadow-md shadow-black/5 dark:border-t-white/5 dark:shadow-zinc-950">
                  <span className="text-sm text-foreground">Open source · built for X</span>
                </div>
                <h1 className="mx-auto mt-8 max-w-4xl text-balance text-5xl font-semibold tracking-tight text-foreground sm:text-6xl md:text-7xl lg:mt-16 xl:text-[5.25rem]">
                  <span className="text-primary">Your ideas</span>, in the style of the authors you{' '}
                  <span className="text-primary">admire</span>.
                </h1>
                <p className="mx-auto mt-8 max-w-3xl text-balance text-lg text-muted-foreground">
                  Write a brief, pick up to three X authors to learn style from, and get a post
                  ready to paste. Not quite right? Say what to change and get a new version.
                </p>
              </AnimatedGroup>

              <AnimatedGroup
                variants={staggeredVariants}
                className="mt-12 flex flex-col items-center justify-center gap-2 md:flex-row"
              >
                <div className="rounded-[14px] border bg-foreground/10 p-0.5">
                  <Button asChild size="lg" className="rounded-xl px-5 text-base">
                    <Link to="/login" onClick={() => track('landing_hero_cta_clicked')}>
                      Start writing
                    </Link>
                  </Button>
                </div>
              </AnimatedGroup>
            </div>

            <AnimatedGroup variants={staggeredVariants}>
              <div className="relative -mr-56 mt-8 overflow-hidden px-2 sm:mr-0 sm:mt-12 md:mt-20">
                <div className="relative mx-auto max-w-6xl overflow-hidden rounded-2xl border bg-background p-4 shadow-lg shadow-zinc-950/15 ring-1 ring-background">
                  <div
                    ref={screenshotRef}
                    className="flex aspect-[16/10] w-full items-center justify-center rounded-2xl border border-border/25 bg-muted font-mono text-sm text-muted-foreground"
                  >
                    [Product screenshot]
                  </div>
                </div>
              </div>
            </AnimatedGroup>
          </div>
        </section>
      </main>
    </>
  );
}
