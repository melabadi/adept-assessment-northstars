// Browser regression test for the "Reviewer confirms the recommended routing department" feature (Develop phase).
// It encodes acceptance criteria 1, 2, and 7 from phases/03-develop/github/confirm-routing-issue.md as a user sees them.
// During the demo, copy it into app/web/e2e/ on the feature branch and run it with the regression-validation skill.
import { expect, test } from '@playwright/test';
import { actAs } from './helpers';

test.describe('Confirm recommended routing', () => {
  test('Ben confirms a recommendation that moves a misfiled request to IT', async ({ page }) => {
    const title = `Laptop dock misfiled ${Date.now()}`;
    await actAs(page, 'u-ava');
    await page.getByRole('main').getByRole('link', { name: 'New request' }).click();
    await page.getByLabel('Title', { exact: true }).fill(title);
    await page.getByLabel('Description', { exact: true }).fill('Laptop docking station for desk 3F-20.');
    await page.getByLabel('Category', { exact: true }).selectOption('equipment');
    await page.getByLabel('Department', { exact: true }).selectOption('FAC');
    await page.getByRole('button', { name: 'Submit request' }).click();
    await expect(page).toHaveURL(/\/requests\/REQ-\d+$/);
    const id = new URL(page.url()).pathname.split('/').pop()!;

    await actAs(page, 'u-ben');
    await page.goto(`/requests/${id}`);
    const triage = page.getByRole('region', { name: 'Triage assistant' });
    await triage.getByRole('button', { name: 'Get recommendation' }).click();
    await expect(triage.getByRole('list', { name: 'Policy citations' })).toContainText('POL-ROUTE-001');

    await triage.getByRole('button', { name: 'Confirm routing' }).click();
    await expect(triage).toContainText('Confirmed by Ben Okafor');
    await expect(triage.getByRole('button', { name: 'Confirm routing' })).toHaveCount(0);
    await expect(page.getByRole('main')).toContainText('IT Services');
    await expect(page.getByText('Status: In review')).toBeVisible();
  });

  test('a requester never sees Confirm routing', async ({ page }) => {
    await actAs(page, 'u-ava');
    await page.goto('/requests/REQ-1001');
    await expect(page.getByRole('region', { name: 'Triage assistant' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Confirm routing' })).toHaveCount(0);
  });
});
