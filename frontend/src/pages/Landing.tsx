import { AuthorsSection } from '@/components/blocks/authors-section';
import { HeroHeader } from '@/components/blocks/hero-header';
import { HeroSection } from '@/components/blocks/hero-section';
import { PricingSection } from '@/components/blocks/pricing-section';
import { useInstance } from '@/features/instance/useInstance';
import { CompanyFooter } from '@/features/legal/CompanyFooter';

export function Landing() {
  const { sells_plans } = useInstance();

  return (
    <>
      <HeroHeader />
      <main>
        <HeroSection />
        <AuthorsSection />
        {sells_plans && <PricingSection />}
      </main>
      <CompanyFooter />
    </>
  );
}
