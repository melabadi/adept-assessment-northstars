import { expect, type Page } from '@playwright/test';

/** Opens the app and switches the Development-mode persona switcher to `personaId`. */
export async function actAs(page: Page, personaId: string) {
  await page.goto('/');
  const select = page.getByLabel('Demo persona');
  await expect(select).toBeEnabled();
  if ((await select.inputValue()) !== personaId) {
    await Promise.all([
      page.waitForResponse((response) => response.url().endsWith('/api/me') && response.ok()),
      select.selectOption(personaId),
    ]);
  }
  await expect(select).toHaveValue(personaId);
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
}
