import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { callsTo, detail, json, mockApi, problem, renderApp } from '../test/utils';

const title = 'Monitor arm for desk 7A';

function created() {
  return detail({ id: 'REQ-1025', title, description: 'Need an adjustable monitor arm for the shared desk.' });
}

async function fillForm(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByRole('textbox', { name: 'Title' }), title);
  await user.type(screen.getByRole('textbox', { name: 'Description' }), 'Need an adjustable monitor arm for the shared desk.');
  await user.selectOptions(screen.getByRole('combobox', { name: 'Category' }), 'equipment');
  await user.selectOptions(screen.getByRole('combobox', { name: 'Department' }), 'IT');
}

describe('NewRequestPage', () => {
  it('sends an Idempotency-Key and blocks a second submit while the first is pending', async () => {
    let respond: (response: Response) => void = () => {};
    const fetchMock = mockApi({
      'POST /api/requests': () => new Promise<Response>((resolve) => (respond = resolve)),
      'GET /api/requests/REQ-1025': () => created(),
      'GET /api/requests/REQ-1025/history': () => [],
    });
    const user = userEvent.setup();

    renderApp('/new');
    await fillForm(user);

    const submit = screen.getByRole('button', { name: 'Submit request' });
    await user.click(submit);

    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/requests')).toHaveLength(1));
    expect(submit).toBeDisabled();
    expect(submit).toHaveTextContent('Submitting…');

    // A second click on the disabled button and a forced form submission are both ignored.
    await user.click(submit);
    fireEvent.submit(submit.closest('form')!);
    expect(callsTo(fetchMock, 'POST', '/api/requests')).toHaveLength(1);

    const [post] = callsTo(fetchMock, 'POST', '/api/requests');
    expect(post.headers.get('Idempotency-Key')).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(post.headers.get('X-RequestHub-Client')).toBe('web');
    expect(post.body).toEqual({
      title,
      description: 'Need an adjustable monitor arm for the shared desk.',
      category: 'equipment',
      departmentId: 'IT',
      priority: 'Normal',
    });

    respond(json(created(), 201));
    expect(await screen.findByRole('heading', { level: 1, name: title })).toBeInTheDocument();
    expect(within(screen.getByRole('main')).getByText('Request REQ-1025 was submitted.')).toBeInTheDocument();
  });

  it('reuses the same Idempotency-Key when retrying after a failure', async () => {
    let attempts = 0;
    const fetchMock = mockApi({
      'POST /api/requests': () => (++attempts === 1 ? problem(503, 'service.unavailable', 'Try again.') : json(created(), 201)),
      'GET /api/requests/REQ-1025': () => created(),
      'GET /api/requests/REQ-1025/history': () => [],
    });
    const user = userEvent.setup();

    renderApp('/new');
    await fillForm(user);
    await user.click(screen.getByRole('button', { name: 'Submit request' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Try again.');
    await user.click(screen.getByRole('button', { name: 'Submit request' }));
    expect(await screen.findByRole('heading', { level: 1, name: title })).toBeInTheDocument();

    const keys = callsTo(fetchMock, 'POST', '/api/requests').map((call) => call.headers.get('Idempotency-Key'));
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it('validates inline before sending anything', async () => {
    const fetchMock = mockApi();
    const user = userEvent.setup();

    renderApp('/new');
    await user.type(await screen.findByRole('textbox', { name: 'Title' }), 'abc');
    await user.click(screen.getByRole('button', { name: 'Submit request' }));

    expect(screen.getByText('Enter a title of 5 to 120 characters.')).toBeInTheDocument();
    expect(screen.getByText('Choose a category.')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Title' })).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByRole('textbox', { name: 'Title' })).toHaveFocus();
    expect(screen.getByText('3 / 120 characters')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/requests')).toHaveLength(0);
  });
});
