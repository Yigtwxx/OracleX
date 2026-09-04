import { expect, test } from '@playwright/test';

import { TEST_USER, stubBackend, stubSupabaseAuth } from './stubs';

/**
 * The signed-out profile page is the sign-in form; a successful sign-in swaps
 * it for the profile header without a navigation. That swap runs through
 * supabase-js → `onAuthStateChange` → `AuthContext` → `ProfilePage`, none of
 * which a unit test touches.
 */
test.describe('sign in', () => {
  test.beforeEach(async ({ page }) => {
    await stubBackend(page);
    await stubSupabaseAuth(page);
    await page.goto('/profile');
  });

  test('signed out, the profile page offers the account card', async ({ page }) => {
    const modes = page.getByRole('group', { name: 'Account access' });
    await expect(modes).toBeVisible();
    await expect(modes.getByRole('button', { name: 'Sign in' })).toHaveAttribute(
      'aria-pressed',
      'true'
    );
    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByLabel('Password')).toBeVisible();
  });

  test('a bad address is refused before anything is sent', async ({ page }) => {
    let requests = 0;
    page.on('request', (request) => {
      if (request.url().includes('/auth/v1/token')) requests += 1;
    });

    await page.getByLabel('Email').fill('not-an-address');
    await page.getByLabel('Password').fill(TEST_USER.password);
    await page.locator('form').getByRole('button', { name: 'Sign in' }).click();

    await expect(page.getByLabel('Email')).toHaveAttribute('aria-invalid', 'true');
    expect(requests).toBe(0);
  });

  test('wrong credentials show a plain-language error and stay signed out', async ({ page }) => {
    await page.getByLabel('Email').fill(TEST_USER.email);
    await page.getByLabel('Password').fill('not-the-password');
    await page.locator('form').getByRole('button', { name: 'Sign in' }).click();

    await expect(page.getByText('That email and password do not match.')).toBeVisible();
    await expect(page.getByRole('group', { name: 'Account access' })).toBeVisible();
  });

  test('valid credentials swap the card for the profile', async ({ page }) => {
    await page.getByLabel('Email').fill(TEST_USER.email);
    await page.getByLabel('Password').fill(TEST_USER.password);
    await page.locator('form').getByRole('button', { name: 'Sign in' }).click();

    await expect(page.getByRole('group', { name: 'Profile sections' })).toBeVisible();
    await expect(page.getByText(TEST_USER.email)).toBeVisible();
    await expect(page.getByRole('group', { name: 'Account access' })).toHaveCount(0);
    // Still on the same URL: the page re-rendered, it did not redirect.
    await expect(page).toHaveURL(/\/profile$/);
  });
});
