import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';
import { actAs } from './helpers';

test.describe('RequestHub in Development auth mode', () => {
  test('Ava creates a request and sees it in My requests', async ({ page }) => {
    const title = `E2E docking station ${Date.now()}`;
    await actAs(page, 'u-ava');

    await page.getByRole('main').getByRole('link', { name: 'New request' }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'New request' })).toBeVisible();
    await page.getByLabel('Title', { exact: true }).fill(title);
    await page.getByLabel('Description', { exact: true }).fill('USB-C docking station for the shared desk in the north wing.');
    await page.getByLabel('Category', { exact: true }).selectOption('equipment');
    await page.getByLabel('Department', { exact: true }).selectOption('IT');
    await page.getByLabel('Priority', { exact: true }).selectOption('High');
    await page.getByRole('button', { name: 'Submit request' }).click();

    await expect(page).toHaveURL(/\/requests\/REQ-\d+$/);
    await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible();
    const id = new URL(page.url()).pathname.split('/').pop()!;
    await expect(page.getByRole('main')).toContainText(`Request ${id} was submitted.`);

    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Requests' }).click();
    await page.getByRole('tab', { name: 'My requests' }).click();
    const row = page.getByRole('row', { name: new RegExp(`\\b${id}\\b`) });
    await expect(row).toContainText(title);
    await expect(row).toContainText('Submitted');
    await expect(row).toContainText('High');
    await expect(row).toContainText('IT Services');
  });

  test('Chloé approves REQ-1002 and the history shows the decision', async ({ page }) => {
    await actAs(page, 'u-chloe');
    await page.goto('/requests/REQ-1002');
    await expect(page.getByRole('heading', { level: 1, name: 'Second monitor for finance analyst' })).toBeVisible();

    const decision = page.getByRole('region', { name: 'Decision' });
    await decision.getByLabel('Decision comment').fill('Approved for month-end reconciliation work.');
    await decision.getByRole('button', { name: 'Approve' }).click();

    await expect(decision).toContainText('By Chloé Dubois');
    await expect(decision).toContainText('Approved for month-end reconciliation work.');
    await expect(decision.getByRole('button', { name: 'Approve' })).toHaveCount(0);
    await expect(page.getByText('Status: Approved')).toBeVisible();

    const history = page.getByRole('region', { name: 'History' });
    const entry = history.getByRole('listitem').filter({ hasText: 'Decision recorded: Approved' });
    await expect(entry).toBeVisible();
    await expect(entry).toContainText('by Chloé Dubois');
  });

  test('Hugo opening his own REQ-1024 sees the self-approval message and no Approve button', async ({ page }) => {
    await actAs(page, 'u-hugo');
    await page.goto('/requests/REQ-1024');
    await expect(page.getByRole('heading', { level: 1, name: 'Replacement keyboard (spilled coffee)' })).toBeVisible();

    const decision = page.getByRole('region', { name: 'Decision' });
    await expect(decision).toContainText("You can't approve or reject your own request.");
    await expect(page.getByRole('button', { name: 'Approve' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Reject' })).toHaveCount(0);
  });

  test('switching to French translates the UI and is remembered', async ({ page }) => {
    await actAs(page, 'u-dan');
    await page.getByRole('button', { name: 'Français' }).click();

    await expect(page.getByRole('heading', { level: 1, name: 'Demandes' })).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('lang', 'fr');
    await expect(page.getByRole('tab', { name: "File de l'équipe" })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('main').getByRole('link', { name: 'Nouvelle demande' })).toBeVisible();
    await expect(page.getByRole('row', { name: /REQ-1001/ })).toContainText('Services TI');

    await page.reload();
    await expect(page.getByRole('heading', { level: 1, name: 'Demandes' })).toBeVisible();
    await page.goto('/requests/REQ-1024');
    await expect(page.getByRole('region', { name: 'Décision' })).toBeVisible();
    await expect(page.getByRole('region', { name: 'Assistant de triage' })).toContainText(
      'Les recommandations sont indicatives. Seul un approbateur peut approuver ou refuser.',
    );
  });

  test('Ben gets a sample-rules recommendation for REQ-1001', async ({ page }) => {
    await actAs(page, 'u-ben');
    await page.goto('/requests/REQ-1001');

    const triage = page.getByRole('region', { name: 'Triage assistant' });
    await triage.getByRole('button', { name: 'Get recommendation' }).click();
    await expect(triage).toContainText('Sample rules — not AI');
    await expect(triage.getByRole('list', { name: 'Policy citations' })).toContainText('POL-ROUTE-001 v1.2');
    await expect(triage).toContainText('Recommendations are advisory. Only an approver can approve or reject.');
    await expect(page.getByRole('region', { name: 'History' })).toContainText('Assistant suggested IT Services');
  });

  test('Ava uploads an attachment and downloads it again', async ({ page }) => {
    await actAs(page, 'u-ava');
    await page.goto('/requests/REQ-1001');

    const attachments = page.getByRole('region', { name: 'Attachments' });
    const content = `Vendor quote ${Date.now()}\nDock: 1 x 249.00\n`;
    await attachments.getByLabel('File to upload').setInputFiles({ name: 'e2e-quote.txt', mimeType: 'text/plain', buffer: Buffer.from(content) });
    await attachments.getByRole('button', { name: 'Upload', exact: true }).click();

    const link = attachments.getByRole('link', { name: 'e2e-quote.txt' }).last();
    await expect(link).toBeVisible();
    const [download] = await Promise.all([page.waitForEvent('download'), link.click()]);
    expect(download.suggestedFilename()).toBe('e2e-quote.txt');
    expect(await readFile(await download.path(), 'utf8')).toBe(content);
  });
});
