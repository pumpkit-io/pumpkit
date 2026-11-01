import { AuthorsSection } from '@/components/blocks/authors-section';
import { HeroHeader } from '@/components/blocks/hero-header';
import { HeroSection } from '@/components/blocks/hero-section';
import { Mascot } from '@/components/blocks/mascot';
import { OpenSourceSection } from '@/components/blocks/open-source-section';
import { PricingSection } from '@/components/blocks/pricing-section';
import { useInstance } from '@/features/instance/useInstance';
import { CompanyFooter } from '@/features/legal/CompanyFooter';

// The mascot nods off only once the visitor has lingered at the foot of the page, or has stopped hovering it.
const FOOTER_NAP_DELAY_MS = 5000;

export function Landing() {
  const { sells_plans } = useInstance();

  return (
    <>
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
    </>
  );
}
