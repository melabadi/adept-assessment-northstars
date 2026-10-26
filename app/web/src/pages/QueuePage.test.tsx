import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { callsTo, mockApi, paged, problem, renderApp, summary } from '../test/utils';

describe('QueuePage', () => {
  it('shows an error with Retry, then the requests', async () => {
    let calls = 0;
    mockApi({
      'GET /api/requests': () =>
        ++calls === 1 ? problem(500, 'server.error', 'Database unavailable.') : paged([summary({ hasRecommendation: true })]),
    });
    const user = userEvent.setup();

    renderApp('/');

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent("We couldn't load the requests.");
    expect(alert).toHaveTextContent('Database unavailable.');
    await user.click(within(alert).getByRole('button', { name: 'Retry' }));

    const row = await screen.findByRole('row', { name: /REQ-1001/ });
    expect(within(row).getByRole('link', { name: 'REQ-1001' })).toHaveAttribute('href', '/requests/REQ-1001');
    expect(within(row).getByText('Assistant suggestion')).toBeInTheDocument();
    expect(within(row).getByText('IT Services')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: /My requests/ })).toBeInTheDocument();
  });

  it('offers scope tabs by role and sends filters and a debounced search to the API', async () => {
    const fetchMock = mockApi();
    const user = userEvent.setup();

    renderApp('/', { persona: 'u-dan' });

    const tabs = await screen.findAllByRole('tab');
    expect(tabs.map((tab) => tab.textContent)).toEqual(['My requests', 'Team queue', 'All requests']);
    expect(screen.getByRole('tab', { name: 'Team queue' })).toHaveAttribute('aria-selected', 'true');

    await user.selectOptions(screen.getByRole('combobox', { name: 'Status' }), 'InReview');
    await user.type(screen.getByRole('searchbox', { name: 'Search' }), 'laptop');

    await waitFor(() => {
      const last = callsTo(fetchMock, 'GET', '/api/requests').at(-1)!;
      expect(last.url.searchParams.get('q')).toBe('laptop');
      expect(last.url.searchParams.get('status')).toBe('InReview');
      expect(last.url.searchParams.get('scope')).toBe('queue');
    });
    const searches = callsTo(fetchMock, 'GET', '/api/requests').filter((call) => call.url.searchParams.has('q'));
    expect(searches).toHaveLength(1);

    await user.click(screen.getByRole('tab', { name: 'Team queue' }));
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'All requests' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'All requests' })).toHaveFocus();
    await waitFor(() => expect(callsTo(fetchMock, 'GET', '/api/requests').at(-1)!.url.searchParams.get('scope')).toBe('all'));
  });

  it('shows only My requests to a requester, with an empty state that links to a new request', async () => {
    mockApi();

    renderApp('/', { persona: 'u-ava' });

    expect(await screen.findByText("You haven't submitted any requests yet.")).toBeInTheDocument();
    expect(screen.getAllByRole('tab')).toHaveLength(1);
    expect(screen.getByRole('tab', { name: 'My requests' })).toHaveAttribute('aria-selected', 'true');
  });
});
