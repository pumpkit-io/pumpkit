import { AuthorsSection } from '@/components/blocks/authors-section';
import { HeroHeader } from '@/components/blocks/hero-header';
import { HeroSection } from '@/components/blocks/hero-section';
import { Mascot } from '@/components/blocks/mascot';
import { OpenSourceSection } from '@/components/blocks/open-source-section';
import { PricingSection } from '@/components/blocks/pricing-section';
import { Switch } from '@/components/ui/switch';
import { useInstance } from '@/features/instance/useInstance';
import { CompanyFooter } from '@/features/legal/CompanyFooter';
import { cn } from '@/lib/utils';
import { useState } from 'react';

// The mascot nods off only once the visitor has lingered at the foot of the page, or has stopped hovering it.
const FOOTER_NAP_DELAY_MS = 5000;

export function Landing() {
  const { sells_plans } = useInstance();
  const [wordmarkFont, setWordmarkFont] = useState(false);

  return (
    <div className={cn(wordmarkFont && 'font-wordmark-preview')}>
      <HeroHeader />
      <main>
        <HeroSection />
        <AuthorsSection />
        {sells_plans && <PricingSection />}
        <OpenSourceSection />
      </main>
      <div className="flex justify-center pt-8">
        <Mascot animation="doze_off" playInViewAfterMs={FOOTER_NAP_DELAY_MS} restOnLastFrame />
      </div>
      <CompanyFooter />
      {/* Experiment: compare the page's fonts with the wordmark's, then keep one. */}
      <label className="fixed bottom-4 right-4 z-30 flex items-center gap-2 rounded-full border border-border bg-card px-3 py-2 text-sm shadow-sm">
        <Switch checked={wordmarkFont} onCheckedChange={setWordmarkFont} />
        Wordmark font
      </label>
    </div>
  );
}
