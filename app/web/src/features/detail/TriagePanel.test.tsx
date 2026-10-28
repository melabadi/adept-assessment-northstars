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
    expect(within(panel).queryByRole('button')).not.toBeInTheDocument();
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

  it('lets a reviewer confirm the current proposed recommendation and shows the confirmer and routing history', async () => {
    const requestId = 'REQ-1001';
    const rec = recommendation({ departmentAtRecommendation: 'IT', suggestedDepartmentId: 'FAC' });
    const proposed = detail({
      departmentId: 'IT',
      latestRecommendation: rec,
      permissions: { ...noPermissions, canTriage: true, canRoute: true },
    });
    const confirmed = detail({
      ...proposed,
      departmentId: 'FAC',
      status: 'InReview',
      latestRecommendation: { ...rec, status: 'Confirmed' },
    });
    let current = proposed;
    let history: { id: number; action: string; actor: { id: string; displayName: string }; occurredAt: string; details: Record<string, unknown>; correlationId: null }[] = [];
    const fetchMock = mockApi({
      [`GET /api/requests/${requestId}`]: () => current,
      [`GET /api/requests/${requestId}/history`]: () => history,
      [`POST /api/requests/${requestId}/triage-recommendations/${rec.id}/confirm`]: () => {
        current = confirmed;
        history = [
          {
            id: 1,
            action: 'triage.confirmed',
            actor: { id: 'u-ben', displayName: 'Ben Okafor' },
            occurredAt: '2026-10-28T12:00:00Z',
            details: { recommendationId: rec.id, from: 'IT', to: 'FAC' },
            correlationId: null,
          },
        ];
        return current;
      },
    });
    const user = userEvent.setup();

    renderApp(`/requests/${requestId}`, { persona: 'u-ben' });

    const panel = await screen.findByRole('region', { name: 'Triage assistant' });
    await user.click(within(panel).getByRole('button', { name: 'Confirm routing' }));

    expect(await within(panel).findByText('Confirmed by Ben Okafor')).toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: 'Confirm routing' })).not.toBeInTheDocument();
    expect(screen.getByText('Routing confirmed: Facilities')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/requests/${requestId}/triage-recommendations/${rec.id}/confirm`,
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('never shows the confirmation button to a requester or for a stale recommendation', async () => {
    mockApi({
      'GET /api/requests/REQ-1001': () =>
        detail({
          departmentId: 'FAC',
          latestRecommendation: recommendation({ departmentAtRecommendation: 'IT' }),
          permissions: { ...noPermissions, canTriage: true, canRoute: true },
        }),
      'GET /api/requests/REQ-1001/history': () => [],
    });

    renderApp('/requests/REQ-1001', { persona: 'u-ava' });

    const panel = await screen.findByRole('region', { name: 'Triage assistant' });
    expect(within(panel).getByText('Stale: request was rerouted since this suggestion')).toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: 'Confirm routing' })).not.toBeInTheDocument();
  });

  it('marks a superseded recommendation stale even when its original department matches the current department', async () => {
    mockApi({
      'GET /api/requests/REQ-1001': () =>
        detail({
          departmentId: 'IT',
          latestRecommendation: recommendation({ status: 'Superseded', departmentAtRecommendation: 'IT' }),
          permissions: { ...noPermissions, canRoute: true },
        }),
      'GET /api/requests/REQ-1001/history': () => [],
    });

    renderApp('/requests/REQ-1001', { persona: 'u-ben' });

    const panel = await screen.findByRole('region', { name: 'Triage assistant' });
    expect(within(panel).getByText('Stale: request was rerouted since this suggestion')).toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: 'Confirm routing' })).not.toBeInTheDocument();
  });

  it('localizes the confirmation action and confirmation history label in French', async () => {
    const rec = recommendation({ departmentAtRecommendation: 'IT' });
    mockApi({
      'GET /api/requests/REQ-1001': () =>
        detail({
          latestRecommendation: rec,
          permissions: { ...noPermissions, canRoute: true },
        }),
      'GET /api/requests/REQ-1001/history': () => [
        {
          id: 1,
          action: 'triage.confirmed',
          actor: { id: 'u-ben', displayName: 'Ben Okafor' },
          occurredAt: '2026-10-28T12:00:00Z',
          details: { recommendationId: rec.id, to: 'FAC' },
          correlationId: null,
        },
      ],
    });

    renderApp('/requests/REQ-1001', { locale: 'fr', persona: 'u-ben' });

    const panel = await screen.findByRole('region', { name: 'Assistant de triage' });
    expect(within(panel).getByRole('button', { name: "Confirmer l'acheminement" })).toBeInTheDocument();
    expect(screen.getByText((text) => text.startsWith('Acheminement confirmé') && text.includes('Installations'))).toBeInTheDocument();
  });

  it('uses feminine agreement for the French confirmed-by label', async () => {
    const rec = recommendation({ status: 'Confirmed', departmentAtRecommendation: 'IT' });
    mockApi({
      'GET /api/requests/REQ-1001': () => detail({ latestRecommendation: rec }),
      'GET /api/requests/REQ-1001/history': () => [
        {
          id: 1,
          action: 'triage.confirmed',
          actor: { id: 'u-ben', displayName: 'Ben Okafor' },
          occurredAt: '2026-10-28T12:00:00Z',
          details: { recommendationId: rec.id, to: 'FAC' },
          correlationId: null,
        },
      ],
    });

    renderApp('/requests/REQ-1001', { locale: 'fr', persona: 'u-ben' });

    const panel = await screen.findByRole('region', { name: 'Assistant de triage' });
    expect(within(panel).getByText('Confirmée par Ben Okafor')).toBeInTheDocument();
  });
});
