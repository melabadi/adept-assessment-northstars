import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { callsTo, detail, json, mockApi, noPermissions, renderApp } from '../../test/utils';

const hugo = { id: 'u-hugo', displayName: 'Hugo Bernard' };

describe('DecisionPanel', () => {
  it('shows the self-approval reason and no Approve or Reject button', async () => {
    mockApi({
      'GET /api/requests/REQ-1024': () =>
        detail({
          id: 'REQ-1024',
          title: 'Replacement keyboard (spilled coffee)',
          requester: hugo,
          permissions: { ...noPermissions, canTriage: true, decideBlockedReason: 'self_approval' },
        }),
      'GET /api/requests/REQ-1024/history': () => [],
    });

    renderApp('/requests/REQ-1024', { persona: 'u-hugo' });

    const panel = await screen.findByRole('region', { name: 'Decision' });
    expect(within(panel).getByText("You can't approve or reject your own request.")).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /reject/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'Decision comment' })).not.toBeInTheDocument();
  });

  it('requires a comment to reject and sends one idempotency key per approval attempt', async () => {
    let decided = false;
    const fetchMock = mockApi({
      'GET /api/requests/REQ-1002': () =>
        detail({
          id: 'REQ-1002',
          title: 'Second monitor for finance analyst',
          status: decided ? 'Approved' : 'Submitted',
          decision: decided
            ? { outcome: 'Approved', decidedBy: { id: 'u-chloe', displayName: 'Chloé Dubois' }, comment: 'OK', decidedAt: '2026-10-26T10:00:00Z' }
            : null,
          permissions: { ...noPermissions, canDecide: !decided, decideBlockedReason: decided ? 'terminal' : null },
        }),
      'GET /api/requests/REQ-1002/history': () => [],
      'POST /api/requests/REQ-1002/decisions': () => {
        decided = true;
        return json({ outcome: 'Approved', decidedBy: { id: 'u-chloe', displayName: 'Chloé Dubois' }, comment: 'OK', decidedAt: '2026-10-26T10:00:00Z' }, 201);
      },
    });
    const user = userEvent.setup();

    renderApp('/requests/REQ-1002', { persona: 'u-chloe' });

    await user.click(await screen.findByRole('button', { name: 'Reject' }));
    expect(screen.getByText('Add a comment explaining why the request is rejected.')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Decision comment' })).toHaveFocus();
    expect(callsTo(fetchMock, 'POST', '/api/requests/REQ-1002/decisions')).toHaveLength(0);

    await user.type(screen.getByRole('textbox', { name: 'Decision comment' }), 'OK');
    await user.click(screen.getByRole('button', { name: 'Approve' }));

    const panel = await screen.findByRole('region', { name: 'Decision' });
    await waitFor(() => expect(within(panel).getByText('By Chloé Dubois')).toBeInTheDocument());
    const posts = callsTo(fetchMock, 'POST', '/api/requests/REQ-1002/decisions');
    expect(posts).toHaveLength(1);
    expect(posts[0].body).toEqual({ outcome: 'Approved', comment: 'OK' });
    expect(posts[0].headers.get('Idempotency-Key')).toMatch(/^[0-9a-f-]{36}$/);
    expect(posts[0].headers.get('X-RequestHub-User')).toBe('u-chloe');
  });
});
