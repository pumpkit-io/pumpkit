import { AuthorsSection } from '@/components/blocks/authors-section';
import { ctaLabels } from '@/components/blocks/cta-labels';
import { usePlanCatalog } from '@/components/blocks/use-plan-catalog';
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
  const catalog = usePlanCatalog(sells_plans);
  const labels = ctaLabels(catalog, sells_plans);

  return (
    <>
      <HeroHeader ctaLabel={labels.nav} />
      <main>
        <HeroSection ctaLabel={labels.hero} />
        <AuthorsSection />
        {sells_plans && <PricingSection state={catalog} />}
        <OpenSourceSection />
      </main>
      <div className="flex justify-center pt-8">
        <Mascot animation="doze_off" playInViewAfterMs={FOOTER_NAP_DELAY_MS} restOnLastFrame />
      </div>
      <CompanyFooter />
    </>
  );
}
