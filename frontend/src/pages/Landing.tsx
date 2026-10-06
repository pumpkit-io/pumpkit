import { AuthorsSection } from '@/components/blocks/authors-section';
import { HeroSection } from '@/components/blocks/hero-section';
import { PricingSection } from '@/components/blocks/pricing-section';

export function Landing() {
  return (
    <>
      <HeroSection />
      <AuthorsSection />
      <PricingSection />
    </>
  );
}
