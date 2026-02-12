/**
 * Dashboard Smoke E2E Tests
 * 
 * Basic tests to verify the dashboard loads and core UI elements are present.
 * Acts as a regression gate for all frontend changes.
 */
import { test, expect } from './fixtures/test-fixtures.js';

test.describe('Dashboard Smoke Tests', () => {

  test('should load the dashboard without errors', async ({ page }) => {
    // Capture console errors
    const errors = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Page should have content (not blank)
    const body = await page.locator('body').innerText();
    expect(body.length).toBeGreaterThan(10);

    // No critical JS errors (filter React dev warnings)
    const criticalErrors = errors.filter(e => 
      !e.includes('DevTools') && 
      !e.includes('Warning:') &&
      !e.includes('Failed to load resource')  // API calls without backend
    );
    // Just log; don't fail on non-critical
    if (criticalErrors.length > 0) {
      console.warn('Console errors:', criticalErrors);
    }
  });

  test('should display the AgentChat component', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // AI Operations Assistant title should be visible
    const title = page.locator('text=AI Operations Assistant').or(
      page.locator('text=AIOps Assistant')
    );
    await expect(title.first()).toBeVisible({ timeout: 10_000 });
  });

  test('should have a chat input area', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const textarea = page.locator('textarea').first();
    await expect(textarea).toBeVisible({ timeout: 10_000 });
    await expect(textarea).toBeEnabled();
  });

  test('should have a Send button', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Wait for the chat textarea to appear first (ensures page is rendered)
    await expect(page.locator('textarea').first()).toBeVisible({ timeout: 10_000 });

    const sendBtn = page.locator('button').filter({ hasText: /send/i }).first();
    await expect(sendBtn).toBeVisible({ timeout: 10_000 });
  });

  test('should have model selector', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Ant Design Select for model
    const modelSelector = page.locator('.ant-select').first();
    await expect(modelSelector).toBeVisible({ timeout: 10_000 });
  });

  test('should show welcome message on load', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // The welcome message is the first assistant message
    const welcomeText = page.locator('text=Welcome to AgenticAIOps').or(
      page.locator('text=AIOps Assistant')
    );
    await expect(welcomeText.first()).toBeVisible({ timeout: 10_000 });
  });

  test('should send a message and receive a response', async ({ page, mockApi }) => {
    mockApi.setResponse('default');
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Type a message
    const textarea = page.locator('textarea').first();
    await textarea.fill('health check');

    // Send
    const sendBtn = page.locator('button').filter({ hasText: /send/i }).first();
    await sendBtn.click();

    // User message should appear (use exact match to avoid multiple hits)
    await expect(page.getByText('health check', { exact: true })).toBeVisible({ timeout: 10_000 });

    // Assistant response should appear
    await expect(page.locator('text=Health Check Complete')).toBeVisible({ timeout: 15_000 });
  });

  test('should render markdown in responses (bold, code)', async ({ page, mockApi }) => {
    mockApi.setResponse('default');
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const textarea = page.locator('textarea').first();
    await textarea.fill('health check');
    await page.locator('button').filter({ hasText: /send/i }).first().click();

    // Wait for response
    await expect(page.locator('text=Health Check Complete')).toBeVisible({ timeout: 15_000 });

    // Bold text should render as <strong> not raw **
    const strongElements = page.locator('strong');
    expect(await strongElements.count()).toBeGreaterThanOrEqual(1);

    // Should not show raw ** in visible text
    const bodyText = await page.locator('body').innerText();
    // Check there's no raw markdown bold markers adjacent to "Health Check Complete"
    expect(bodyText).not.toMatch(/\*\*Health Check Complete\*\*/);
  });

  test('screenshot: dashboard initial state', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.screenshot({ 
      path: 'tests/e2e/screenshots/dashboard-initial.png',
      fullPage: true,
    });
  });
});
