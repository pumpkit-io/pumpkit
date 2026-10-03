import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ThemeProvider } from '@/features/theme/ThemeProvider';
import { Brand } from './Brand';

describe('Brand', () => {
  it('shows the app name by default', () => {
    render(<ThemeProvider><Brand /></ThemeProvider>);
    expect(screen.getByText('Pumpkit')).toBeInTheDocument();
  });

  it('can hide the name', () => {
    render(<ThemeProvider><Brand showName={false} /></ThemeProvider>);
    expect(screen.queryByText('Pumpkit')).not.toBeInTheDocument();
  });
});
