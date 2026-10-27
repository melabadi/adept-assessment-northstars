// The reviewer's browser regression test for "Reviewer confirms the recommended routing department" (Develop phase).
// It checks acceptance criteria 1, 2, 3, 4, and 7 of solutions/03-develop-github/feature-issue.md as a user sees them,
// independently of the tests Copilot writes. During the demo, copy it into app/web/e2e/ on Copilot's branch and run it.
import { expect, test, type Page } from '@playwright/test';
import { actAs } from './helpers';

/** Ava files an equipment request under Facilities. The sample triage rules route equipment to IT. */
async function fileMisroutedRequest(page: Page, title: string) {
  await actAs(page, 'u-ava');
  await page.getByRole('main').getByRole('link', { name: 'New request' }).click();
  await page.getByLabel('Title', { exact: true }).fill(title);
  await page.getByLabel('Description', { exact: true }).fill('Laptop docking station for desk 3F-20.');
  await page.getByLabel('Category', { exact: true }).selectOption('equipment');
  await page.getByLabel('Department', { exact: true }).selectOption('FAC');
  await page.getByRole('button', { name: 'Submit request' }).click();
  await expect(page).toHaveURL(/\/requests\/REQ-\d+$/);
  return new URL(page.url()).pathname.split('/').pop()!;
}

/** Ben, a reviewer for IT and Facilities, asks the triage assistant for a recommendation. */
async function recommend(page: Page, id: string) {
  await actAs(page, 'u-ben');
  await page.goto(`/requests/${id}`);
  const triage = page.getByRole('region', { name: 'Triage assistant' });
  await triage.getByRole('button', { name: 'Get recommendation' }).click();
  await expect(triage.getByRole('list', { name: 'Policy citations' })).toContainText('POL-ROUTE-001');
  return triage;
}

test.describe('Confirm recommended routing', () => {
  test('Ben confirms a recommendation that moves a misrouted request to IT', async ({ page }) => {
    const id = await fileMisroutedRequest(page, `Laptop dock misrouted ${Date.now()}`);
    const triage = await recommend(page, id);

    await triage.getByRole('button', { name: 'Confirm routing' }).click();
    await expect(triage).toContainText('Confirmed by Ben Okafor');
    await expect(triage.getByRole('button', { name: 'Confirm routing' })).toHaveCount(0);
    await expect(page.getByRole('region', { name: 'Routing' })).toContainText('Current department: IT Services');
    await expect(page.getByText('Status: In review')).toBeVisible();

    const history = page.getByRole('region', { name: 'History' });
    await expect(history.getByRole('listitem').filter({ hasText: 'Routing confirmed: IT Services' })).toHaveCount(1);
    await expect(history).not.toContainText('triage.confirmed');
  });

  test('a recommendation made before a manual reroute is stale and cannot be confirmed', async ({ page }) => {
    const id = await fileMisroutedRequest(page, `Laptop dock rerouted by hand ${Date.now()}`);
    const triage = await recommend(page, id);

    const routing = page.getByRole('region', { name: 'Routing' });
    await routing.getByLabel('New department').selectOption({ label: 'IT Services' });
    await routing.getByRole('button', { name: 'Change routing' }).click();
    await expect(routing).toContainText('Current department: IT Services');

    await expect(triage).toContainText('Stale: request was rerouted since this suggestion');
    await expect(triage.getByRole('button', { name: 'Confirm routing' })).toHaveCount(0);
  });

  test('a requester never sees Confirm routing', async ({ page }) => {
    await actAs(page, 'u-ava');
    await page.goto('/requests/REQ-1001');
    await expect(page.getByRole('region', { name: 'Triage assistant' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Confirm routing' })).toHaveCount(0);
  });
});
