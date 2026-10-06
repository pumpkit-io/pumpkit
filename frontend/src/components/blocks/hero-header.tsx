import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Menu, X } from 'lucide-react';
import { Brand } from '@/components/brand/Brand';
import { Button } from '@/components/ui/button';
import { track } from '@/lib/analytics';
import { APP_NAME } from '@/lib/app';
import { cn } from '@/lib/utils';

type Surface = 'desktop' | 'mobile';

const NAV_LINKS = [
  { label: 'Authors', href: '#authors', event: 'landing_nav_authors_clicked' },
  { label: 'Pricing', href: '#pricing', event: 'landing_nav_pricing_clicked' },
] as const;

const MOBILE_MENU_ID = 'landing-mobile-menu';

export function HeroHeader() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [isScrolled, setIsScrolled] = useState(false);

  useEffect(() => {
    const handleScroll = () => setIsScrolled(window.scrollY > 50);
    handleScroll();
    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  useEffect(() => {
    if (!menuOpen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setMenuOpen(false);
      track('landing_mobile_menu_closed');
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [menuOpen]);

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
