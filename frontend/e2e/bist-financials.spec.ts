import { expect, test } from '@playwright/test';

import { stubBackend } from './stubs';

/**
 * The one Bilanço behaviour worth a real browser.
 *
 * `lib/bist-financials.test.ts` already pins `effectiveBasis`, but the failure
 * this guards against is a wiring failure rather than a logic one: a page that
 * computes the right frame and then labels the panels from the *requested* one
 * would pass every unit test and still show nominal lira under "Reel". The only
 * way to see that is to render it.
 */
test.describe('Bilanço price frame', () => {
  test('offers the deflated frame when an inflation series is available', async ({ page }) => {
    await stubBackend(page);
    await page.goto('/bist/bilanco');

    await expect(page.getByRole('heading', { name: 'Bilanço' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Reel', exact: true })).toBeVisible();
  });

  test('nothing is labelled real when the board could not be deflated', async ({ page }) => {
    await stubBackend(page, { deflated: false });
    await page.goto('/bist/bilanco');

    await expect(page.getByRole('heading', { name: 'Bilanço' })).toBeVisible();

    // The toggle is gone rather than present-and-answering-nominal.
    await expect(page.getByRole('button', { name: 'Reel', exact: true })).toHaveCount(0);

    // The reason is stated where the reader is looking.
    await expect(page.getByText(/Enflasyon serisi bu kurulumda tanımlı değil/)).toBeVisible();

    // The headline growth tile renames itself rather than showing a dash under
    // a "Reel" heading, and carries the nominal figure under its own name.
    await expect(page.getByText('Nominal hasılat büyümesi')).toBeVisible();
    await expect(page.getByText('Reel hasılat büyümesi')).toHaveCount(0);

    // Every panel that names its frame names the nominal one.
    await expect(page.getByText(/kesikli çizgi ROE/)).toContainText('nominal');
  });
});
