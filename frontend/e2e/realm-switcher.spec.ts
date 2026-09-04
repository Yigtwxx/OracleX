import { expect, test } from '@playwright/test';

import { stubBackend } from './stubs';

/**
 * The realm is read off the path, not held in a store. That is the claim
 * these tests hold the shell to: a switch is a navigation and nothing else,
 * a direct link lands in the right tab set, and the tab set is entirely
 * decided by the URL the browser is on.
 */
test.describe('realm switcher', () => {
  test.beforeEach(async ({ page }) => {
    await stubBackend(page);
  });

  test('the global terminal carries its own tabs and a switcher named in English', async ({
    page,
  }) => {
    await page.goto('/overview?type=crypto');

    const nav = page.getByRole('navigation');
    await expect(nav.getByRole('link', { name: 'Overview' })).toBeVisible();
    await expect(nav.getByRole('link', { name: 'Hisseler' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Select market' })).toBeVisible();
  });

  test('switching to BIST navigates to /bist and swaps the whole tab set', async ({ page }) => {
    await page.goto('/overview?type=crypto');

    await page.getByRole('button', { name: 'Select market' }).click();
    const menu = page.getByRole('menu');
    await expect(menu).toBeVisible();
    await expect(menu.getByRole('menuitem', { name: /Kripto \/ Nasdaq/ })).toHaveAttribute(
      'aria-current',
      'true'
    );

    await menu.getByRole('menuitem', { name: /BIST 100/ }).click();

    await expect(page).toHaveURL(/\/bist$/);
    const nav = page.getByRole('navigation');
    await expect(nav.getByRole('link', { name: 'Hisseler' })).toBeVisible();
    await expect(nav.getByRole('link', { name: 'Overview' })).toHaveCount(0);
    // The trigger's own name follows the realm's language.
    await expect(page.getByRole('button', { name: 'Piyasa seç' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Select market' })).toHaveCount(0);
  });

  test('switching back lands on /home, the one tab that orients you', async ({ page }) => {
    await page.goto('/bist/kap');

    await page.getByRole('button', { name: 'Piyasa seç' }).click();
    await page
      .getByRole('menu')
      .getByRole('menuitem', { name: /Kripto \/ Nasdaq/ })
      .click();

    await expect(page).toHaveURL(/\/home$/);
    await expect(
      page.getByRole('navigation').getByRole('link', { name: 'Overview' })
    ).toBeVisible();
  });

  test('a deep BIST link opens straight into the BIST tab set', async ({ page }) => {
    await page.goto('/bist/viop');

    const nav = page.getByRole('navigation');
    await expect(nav.getByRole('link', { name: 'Hisseler' })).toBeVisible();
    await expect(nav.getByRole('link', { name: 'Overview' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Piyasa seç' })).toBeVisible();
  });

  test('Escape closes the menu without leaving the realm', async ({ page }) => {
    await page.goto('/overview?type=crypto');

    await page.getByRole('button', { name: 'Select market' }).click();
    await expect(page.getByRole('menu')).toBeVisible();

    await page.keyboard.press('Escape');

    await expect(page.getByRole('menu')).toHaveCount(0);
    await expect(page).toHaveURL(/\/overview/);
  });
});
