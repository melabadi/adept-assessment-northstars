import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { detail, mockApi, renderApp } from '../../test/utils';

const confirmation = {
  id: 501,
  action: 'triage.confirmed',
  actor: { id: 'u-ben', displayName: 'Ben Okafor' },
  occurredAt: '2026-10-26T06:20:00Z',
  details: { recommendationId: '7d2c1f00-0000-4000-8000-000000000001', from: 'IT', to: 'FAC' },
  correlationId: null,
};

function setup(locale: 'en' | 'fr') {
  mockApi({
    'GET /api/requests/REQ-1001': () => detail(),
    'GET /api/requests/REQ-1001/history': () => [confirmation],
  });
  renderApp('/requests/REQ-1001', { persona: 'u-ben', locale });
}

describe('triage confirmation history label', () => {
  it('uses the English plain-language label', async () => {
    setup('en');
    expect(await screen.findByText('Confirmed recommended routing from IT Services to Facilities')).toBeInTheDocument();
  });

  it('uses the French plain-language label', async () => {
    setup('fr');
    expect(await screen.findByText('Acheminement recommandé confirmé de Services TI à Installations')).toBeInTheDocument();
  });
});
