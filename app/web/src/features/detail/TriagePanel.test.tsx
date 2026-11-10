import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { detail, mockApi, noPermissions, problem, recommendation, renderApp } from '../../test/utils';

describe('TriagePanel', () => {
  it('labels sample-rule recommendations as not AI and shows policy citations with their text', async () => {
    mockApi({
      'GET /api/requests/REQ-1003': () =>
        detail({
          id: 'REQ-1003',
          title: 'Badge access to Building C lab',
          departmentId: 'FAC',
          latestRecommendation: recommendation(),
          permissions: { ...noPermissions, canTriage: true },
        }),
      'GET /api/requests/REQ-1003/history': () => [],
    });
    const user = userEvent.setup();

    renderApp('/requests/REQ-1003', { persona: 'u-ben' });

    const panel = await screen.findByRole('region', { name: 'Triage assistant' });
    expect(within(panel).getByText('Sample rules — not AI')).toBeInTheDocument();
    expect(within(panel).queryByText(/AI recommendation/)).not.toBeInTheDocument();

    const citations = within(panel).getByRole('list', { name: 'Policy citations' });
    const chip = within(citations).getByText('POL-ROUTE-003 v2.1');
    expect(chip).toHaveAttribute('title', expect.stringContaining('Workplace and building services'));

    await user.click(within(panel).getByText('Read the cited policies'));
    expect(within(panel).getByText(/building access badges route to Facilities/)).toBeVisible();

    expect(within(panel).getByText('60%')).toBeInTheDocument();
    expect(within(panel).getByText('Recommendations are advisory. Only an approver can approve or reject.')).toBeInTheDocument();
    expect(within(panel).getByRole('button', { name: 'Get recommendation' })).toBeInTheDocument();
    // Applying a recommendation is intentionally not part of the UI.
    expect(within(panel).getAllByRole('button')).toHaveLength(1);
  });

  it('labels AI recommendations with the provider and trace id, and flags stale or uncertain suggestions', async () => {
    mockApi({
      'GET /api/requests/REQ-1001': () =>
        detail({
          departmentId: 'FAC',
          latestRecommendation: recommendation({
            provider: 'foundry-agent',
            isSample: false,
            providerTraceId: 'resp_abc123',
            suggestedDepartmentId: 'IT',
            departmentAtRecommendation: 'IT',
            needsHumanReview: true,
            policyRefs: [{ policyId: 'POL-ROUTE-001', version: '1.2' }],
          }),
        }),
      'GET /api/requests/REQ-1001/history': () => [],
    });

    renderApp('/requests/REQ-1001', { persona: 'u-ava' });

    const panel = await screen.findByRole('region', { name: 'Triage assistant' });
    expect(within(panel).getByText('AI recommendation · foundry-agent')).toBeInTheDocument();
    expect(within(panel).getByText('Provider trace: resp_abc123')).toBeInTheDocument();
    expect(within(panel).queryByText('Sample rules — not AI')).not.toBeInTheDocument();
    expect(within(panel).getByText('Stale: request was rerouted since this suggestion')).toBeInTheDocument();
    expect(within(panel).getByText('Needs human review')).toBeInTheDocument();
    expect(
      within(panel).getByText('The assistant flagged this recommendation for a person. A reviewer should confirm the routing.'),
    ).toBeInTheDocument();
    expect(within(panel).queryByRole('button')).not.toBeInTheDocument();
  });

  it('lets an authorized reviewer confirm a current recommendation and shows the confirmer and history label', async () => {
    let confirmed = false;
    const currentRecommendation = recommendation({ departmentAtRecommendation: 'FAC' });
    const confirmedRecommendation = {
      ...currentRecommendation,
      status: 'Confirmed',
      confirmedBy: { id: 'u-ben', displayName: 'Ben Okafor' },
    };
    const fetchMock = mockApi({
      'GET /api/requests/REQ-1001': () => detail({
        departmentId: 'FAC',
        latestRecommendation: confirmed ? confirmedRecommendation : currentRecommendation,
        permissions: { ...noPermissions, canRoute: true, canTriage: true },
      }),
      'GET /api/requests/REQ-1001/history': () => confirmed
        ? [{ id: 20, action: 'triage.confirmed', actor: { id: 'u-ben', displayName: 'Ben Okafor' }, occurredAt: '2026-10-26T06:30:00Z', details: { to: 'FAC' }, correlationId: null }]
        : [],
      'POST /api/requests/REQ-1001/triage-recommendations/7d2c1f00-0000-4000-8000-000000000001/confirm': () => {
        confirmed = true;
        return detail({
          departmentId: 'FAC',
          latestRecommendation: confirmedRecommendation,
          permissions: { ...noPermissions, canRoute: true, canTriage: true },
        });
      },
    });
    const user = userEvent.setup();

    renderApp('/requests/REQ-1001', { persona: 'u-ben' });

    const panel = await screen.findByRole('region', { name: 'Triage assistant' });
    await user.click(within(panel).getByRole('button', { name: 'Confirm routing' }));

    expect(await within(panel).findByText('Confirmed by Ben Okafor')).toBeInTheDocument();
    expect(await screen.findByText('Routing confirmed: Facilities')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/requests/REQ-1001/triage-recommendations/7d2c1f00-0000-4000-8000-000000000001/confirm'),
      expect.objectContaining({ method: 'POST' }),
    );
    expect(within(panel).queryByRole('button', { name: 'Confirm routing' })).not.toBeInTheDocument();
  });

  it('does not offer confirmation for stale, already-confirmed, or inaccessible recommendations', async () => {
    const stale = recommendation({ departmentAtRecommendation: 'IT' });
    mockApi({
      'GET /api/requests/REQ-1001': () => detail({
        departmentId: 'FAC',
        latestRecommendation: stale,
        permissions: { ...noPermissions, canRoute: true },
      }),
      'GET /api/requests/REQ-1001/history': () => [],
    });
    const { unmount } = renderApp('/requests/REQ-1001', { persona: 'u-ben' });
    const stalePanel = await screen.findByRole('region', { name: 'Triage assistant' });
    expect(within(stalePanel).queryByRole('button', { name: 'Confirm routing' })).not.toBeInTheDocument();
    unmount();

    mockApi({
      'GET /api/requests/REQ-1001': () => detail({
        departmentId: 'FAC',
        latestRecommendation: recommendation({
          status: 'Confirmed',
          departmentAtRecommendation: 'FAC',
          confirmedBy: { id: 'u-dan', displayName: 'Dan Rivera' },
        }),
        permissions: { ...noPermissions, canRoute: true },
      }),
      'GET /api/requests/REQ-1001/history': () => [],
    });
    const { unmount: unmountConfirmed } = renderApp('/requests/REQ-1001', { persona: 'u-ben' });
    const confirmedPanel = await screen.findByRole('region', { name: 'Triage assistant' });
    expect(within(confirmedPanel).queryByRole('button', { name: 'Confirm routing' })).not.toBeInTheDocument();
    unmountConfirmed();

    mockApi({
      'GET /api/requests/REQ-1001': () => detail({
        departmentId: 'FAC',
        latestRecommendation: recommendation({ departmentAtRecommendation: 'FAC', suggestedDepartmentId: 'FIN' }),
        permissions: { ...noPermissions, canRoute: true },
      }),
      'GET /api/requests/REQ-1001/history': () => [],
    });
    renderApp('/requests/REQ-1001', { persona: 'u-ben' });
    const inaccessiblePanel = await screen.findByRole('region', { name: 'Triage assistant' });
    expect(within(inaccessiblePanel).queryByRole('button', { name: 'Confirm routing' })).not.toBeInTheDocument();
  });

  it('does not offer confirmation to the requester even when they also have reviewer access', async () => {
    mockApi({
      'GET /api/requests/REQ-1001': () => detail({
        requester: { id: 'u-ben', displayName: 'Ben Okafor' },
        departmentId: 'FAC',
        latestRecommendation: recommendation({ departmentAtRecommendation: 'FAC' }),
        permissions: { ...noPermissions, canRoute: true },
      }),
      'GET /api/requests/REQ-1001/history': () => [],
    });

    renderApp('/requests/REQ-1001', { persona: 'u-ben' });

    const panel = await screen.findByRole('region', { name: 'Triage assistant' });
    expect(within(panel).queryByRole('button', { name: 'Confirm routing' })).not.toBeInTheDocument();
  });

  it('renders the routing confirmation history label in French', async () => {
    mockApi({
      'GET /api/requests/REQ-1001': () => detail(),
      'GET /api/requests/REQ-1001/history': () => [
        {
          id: 21,
          action: 'triage.confirmed',
          actor: { id: 'u-ben', displayName: 'Ben Okafor' },
          occurredAt: '2026-10-26T06:30:00Z',
          details: { to: 'FAC' },
          correlationId: null,
        },
      ],
    });

    renderApp('/requests/REQ-1001', { locale: 'fr', persona: 'u-ava' });

    expect(await screen.findByText('Acheminement confirmé vers Installations')).toBeInTheDocument();
  });

  it('shows a translated, accessible error when the triage provider is unavailable', async () => {
    mockApi({
      'GET /api/requests/REQ-1001': () => detail({ permissions: { ...noPermissions, canTriage: true } }),
      'GET /api/requests/REQ-1001/history': () => [],
      'POST /api/requests/REQ-1001/triage-recommendations': () =>
        problem(503, 'triage.unavailable', 'The triage assistant is unavailable. Route the request manually.'),
    });
    const user = userEvent.setup();

    renderApp('/requests/REQ-1001', { persona: 'u-ben' });

    const panel = await screen.findByRole('region', { name: 'Triage assistant' });
    await user.click(within(panel).getByRole('button', { name: 'Get recommendation' }));

    const alert = await within(panel).findByRole('alert');
    expect(alert).toHaveTextContent("We couldn't get a recommendation.");
    expect(alert).toHaveTextContent('The triage assistant is unavailable right now. Route the request manually.');
    expect(alert).toHaveTextContent('Details: The triage assistant is unavailable. Route the request manually.');
    expect(within(panel).getByRole('button', { name: 'Get recommendation' })).toBeEnabled();
  });
});
