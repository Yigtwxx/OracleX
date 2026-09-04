import { expect, test, type Locator, type Page } from '@playwright/test';

import { COINS, COINS_IN_FILTER_BUCKET, FILTER_BUCKET_LABEL, stubBackend } from './stubs';

/**
 * The 24h change histogram doubles as the table's filter. The two live in
 * different components with the selection lifted into the page between them,
 * so the interesting failure — a click that redraws the bar and not the
 * table, or the reverse — is invisible to a unit test of either.
 */

/** The asset table's card. Rows are `div[role=button]`, not `<tr>`. */
function assetTable(page: Page): Locator {
  return page
    .locator('.surface')
    .filter({ has: page.getByRole('heading', { name: 'Crypto Assets' }) });
}

const rows = (page: Page) => assetTable(page).locator('[role="button"][tabindex="0"]');

/** The histogram column for a bucket, by its accessible name. */
function bucketColumn(page: Page, label: string): Locator {
  const escaped = label.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&');
  return page.getByRole('button', { name: new RegExp(`assets changed ${escaped}$`) });
}

test.describe('overview change filter', () => {
  test.beforeEach(async ({ page }) => {
    await stubBackend(page);
    await page.goto('/overview?type=crypto');
    await expect(rows(page)).toHaveCount(COINS.length);
  });

  test('clicking a histogram column narrows the table to that bucket', async ({ page }) => {
    const column = bucketColumn(page, FILTER_BUCKET_LABEL);
    await expect(column).toHaveAttribute('aria-pressed', 'false');

    await column.click();

    await expect(column).toHaveAttribute('aria-pressed', 'true');
    await expect(rows(page)).toHaveCount(COINS_IN_FILTER_BUCKET);
    // "1–3 of 3 (10)": the payload total stays in view while narrowed.
    await expect(assetTable(page)).toContainText(`of ${COINS_IN_FILTER_BUCKET} (${COINS.length})`);
    await expect(
      assetTable(page).getByRole('button', { name: /Clear change filter/ })
    ).toContainText(`24h ${FILTER_BUCKET_LABEL}`);
  });

  test('the chip on the table clears the filter set from below it', async ({ page }) => {
    await bucketColumn(page, FILTER_BUCKET_LABEL).click();
    await expect(rows(page)).toHaveCount(COINS_IN_FILTER_BUCKET);

    await assetTable(page)
      .getByRole('button', { name: /Clear change filter/ })
      .click();

    await expect(rows(page)).toHaveCount(COINS.length);
    await expect(page.getByText('Select a column to filter the table above.')).toBeVisible();
  });

  test('clicking the selected column again toggles the filter off', async ({ page }) => {
    const column = bucketColumn(page, FILTER_BUCKET_LABEL);
    await column.click();
    await expect(rows(page)).toHaveCount(COINS_IN_FILTER_BUCKET);

    await column.click();

    await expect(column).toHaveAttribute('aria-pressed', 'false');
    await expect(rows(page)).toHaveCount(COINS.length);
  });

  test('an empty bucket still filters, to an explained empty table', async ({ page }) => {
    // No fixture coin moves between +6 and +10.
    await bucketColumn(page, '+6 / +10').click();

    await expect(rows(page)).toHaveCount(0);
    await expect(page.getByText('No assets changed +6 / +10 in the last 24h.')).toBeVisible();
  });
});
