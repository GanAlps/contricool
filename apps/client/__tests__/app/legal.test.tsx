/**
 * Phase 7 — Privacy + Terms screens render the expected headings and
 * cite the correct legal frameworks.
 */
import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { useAuthStore } from '~/lib/auth-store';

import { mockExpoRouter, resetRouterMock } from './_router-mock';

mockExpoRouter();

const PrivacyScreen = (await import('~/app/(legal)/privacy')).default;
const TermsScreen = (await import('~/app/(legal)/terms')).default;
const LegalLayout = (await import('~/app/(legal)/_layout')).default;

beforeEach(() => {
  resetRouterMock();
  useAuthStore.getState()._clear();
});
afterEach(() => {
  useAuthStore.getState()._clear();
});

describe('Privacy', () => {
  it('renders title + CCPA + DPDP', () => {
    render(<PrivacyScreen />);
    expect(screen.getByTestId('privacy-title')).toBeInTheDocument();
    expect(screen.getByText(/CCPA/)).toBeInTheDocument();
    expect(screen.getByText(/DPDP/)).toBeInTheDocument();
  });
});

describe('Terms', () => {
  it('renders title + acceptance + governing law', () => {
    render(<TermsScreen />);
    expect(screen.getByTestId('terms-title')).toBeInTheDocument();
    expect(screen.getByText(/Acceptance/)).toBeInTheDocument();
    expect(screen.getByText(/Governing law/)).toBeInTheDocument();
  });
});

describe('Legal layout', () => {
  it('renders nothing visible itself; just provides a Stack wrapper', () => {
    const { container } = render(<LegalLayout />);
    expect(container).toBeInTheDocument();
  });
});
