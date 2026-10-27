import { cleanup, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { callsTo, detail, mockApi, noPermissions, problem, recommendation, renderApp } from '../../test/utils';

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

  it('lets an authorized reviewer confirm a current proposed recommendation', async () => {
    let confirmed = false;
    const requestDetail = () => detail({
      departmentId: 'FAC',
      latestRecommendation: recommendation({
        departmentAtRecommendation: 'FAC',
        status: confirmed ? 'Confirmed' : 'Proposed',
        confirmedBy: confirmed ? { id: 'u-ben', displayName: 'Ben Okafor' } : null,
      }),
      permissions: { ...noPermissions, canConfirmRecommendation: !confirmed },
    });
    const fetchMock = mockApi({
      'GET /api/requests/REQ-1001': () => requestDetail(),
      'GET /api/requests/REQ-1001/history': () => [],
      'POST /api/requests/REQ-1001/triage-recommendations/7d2c1f00-0000-4000-8000-000000000001/confirm': () => {
        confirmed = true;
        return requestDetail();
      },
    });
    const user = userEvent.setup();

    renderApp('/requests/REQ-1001', { persona: 'u-ben' });

    const panel = await screen.findByRole('region', { name: 'Triage assistant' });
    const button = within(panel).getByRole('button', { name: 'Confirm routing' });
    await user.click(button);
    expect(callsTo(fetchMock, 'POST', '/api/requests/REQ-1001/triage-recommendations/7d2c1f00-0000-4000-8000-000000000001/confirm')).toHaveLength(1);
    expect(await within(panel).findByText('Confirmed by Ben Okafor')).toBeInTheDocument();
  });

  it('does not offer confirmation to requesters, stale recommendations, or already-confirmed recommendations', async () => {
    mockApi({
      'GET /api/requests/REQ-1001': () => detail({
        departmentId: 'FAC',
        latestRecommendation: recommendation({
          departmentAtRecommendation: 'IT',
          status: 'Proposed',
        }),
        permissions: { ...noPermissions, canConfirmRecommendation: true },
      }),
      'GET /api/requests/REQ-1001/history': () => [],
    });
    renderApp('/requests/REQ-1001', { persona: 'u-ben' });
    const stalePanel = await screen.findByRole('region', { name: 'Triage assistant' });
    expect(within(stalePanel).queryByRole('button', { name: 'Confirm routing' })).not.toBeInTheDocument();

    cleanup();
    mockApi({
      'GET /api/requests/REQ-1001': () => detail({
        departmentId: 'FAC',
        latestRecommendation: recommendation({ departmentAtRecommendation: 'FAC' }),
        permissions: { ...noPermissions, canConfirmRecommendation: false },
      }),
      'GET /api/requests/REQ-1001/history': () => [],
    });
    renderApp('/requests/REQ-1001', { persona: 'u-ava' });
    const requesterPanel = await screen.findByRole('region', { name: 'Triage assistant' });
    expect(within(requesterPanel).queryByRole('button', { name: 'Confirm routing' })).not.toBeInTheDocument();

    cleanup();
    mockApi({
      'GET /api/requests/REQ-1001': () => detail({
        departmentId: 'FAC',
        latestRecommendation: recommendation({
          departmentAtRecommendation: 'FAC',
          status: 'Confirmed',
          confirmedBy: { id: 'u-ben', displayName: 'Ben Okafor' },
        }),
        permissions: { ...noPermissions, canConfirmRecommendation: true },
      }),
      'GET /api/requests/REQ-1001/history': () => [],
    });
    renderApp('/requests/REQ-1001', { persona: 'u-ben' });
    const confirmedPanel = await screen.findByRole('region', { name: 'Triage assistant' });
    expect(within(confirmedPanel).queryByRole('button', { name: 'Confirm routing' })).not.toBeInTheDocument();
    expect(within(confirmedPanel).getByText('Confirmed by Ben Okafor')).toBeInTheDocument();
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
