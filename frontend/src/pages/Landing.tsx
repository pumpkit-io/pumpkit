import { AuthorsSection } from '@/components/blocks/authors-section';
import { HeroHeader } from '@/components/blocks/hero-header';
import { HeroSection } from '@/components/blocks/hero-section';
import { PricingSection } from '@/components/blocks/pricing-section';

export function Landing() {
  return (
    <>
      <HeroHeader />
      <main>
        <HeroSection />
        <AuthorsSection />
        <PricingSection />
      </main>
    </>
  );
}
