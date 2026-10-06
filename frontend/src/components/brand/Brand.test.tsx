import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ThemeProvider } from '@/features/theme/ThemeProvider';
import { Brand } from './Brand';

describe('Brand', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it('shows the app name by default', () => {
    render(
      <ThemeProvider>
        <Brand />
      </ThemeProvider>,
    );
    expect(screen.getByText('Pumpkit')).toBeInTheDocument();
  });

  it('shows the configured app name with its casing', async () => {
    vi.stubEnv('VITE_APP_NAME', 'acmeWriter');
    vi.resetModules();
    const { Brand: ConfiguredBrand } = await import('./Brand');
    const { ThemeProvider: ConfiguredThemeProvider } =
      await import('@/features/theme/ThemeProvider');
    render(
      <ConfiguredThemeProvider>
        <ConfiguredBrand />
      </ConfiguredThemeProvider>,
    );
    expect(screen.getByText('acmeWriter')).toBeInTheDocument();
  });

  it('can hide the name', () => {
    render(
      <ThemeProvider>
        <Brand showName={false} />
      </ThemeProvider>,
    );
    expect(screen.queryByText('Pumpkit')).not.toBeInTheDocument();
  });
});
