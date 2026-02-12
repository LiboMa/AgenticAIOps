/**
 * Bug-008 Edge Cases: Table Rendering Stress Tests
 * 
 * Covers scenarios Reviewer flagged as missing:
 * - Single-row (minimal) table
 * - Large table (20 rows, 10 columns) — overflow/scroll
 * - Special characters & empty cells
 * - Multiple tables in one response
 * - Table alongside other markdown elements (nested context)
 */
import { test, expect } from './fixtures/test-fixtures.js';

/** Helper: send a message and wait for response */
async function sendAndWait(page, message, waitForText, timeout = 15_000) {
  const textarea = page.locator('textarea').first();
  await textarea.fill(message);
  await page.locator('button').filter({ hasText: /send/i }).first().click();
  await page.waitForFunction(
    (text) => document.body.innerText.includes(text),
    waitForText,
    { timeout }
  );
}

test.describe('Bug-008 Edge Cases', () => {

  test('single-row table renders correctly', async ({ page, mockApi }) => {
    mockApi.setResponse('singleRowTable');
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    await sendAndWait(page, 'check metric', 'CPU Usage');

    const table = page.locator('table').first();
    await expect(table).toBeVisible();

    // Should have 1 header row + 1 data row
    const headerCells = table.locator('th');
    expect(await headerCells.count()).toBe(2); // Metric, Value

    const dataCells = table.locator('td');
    expect(await dataCells.count()).toBe(2); // CPU Usage, 98.7%

    await expect(table.locator('td').nth(1)).toContainText('98.7%');
  });

  test('large table (20 rows) renders all rows and is scrollable', async ({ page, mockApi }) => {
    mockApi.setResponse('largeTable');
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    await sendAndWait(page, 'list all resources', 'etcd-m9n0');

    const table = page.locator('table').first();
    await expect(table).toBeVisible();

    // Should have 10 header columns
    const headers = table.locator('th');
    expect(await headers.count()).toBe(10);

    // Should have 20 data rows
    const dataRows = table.locator('tbody tr');
    const rowCount = await dataRows.count();
    expect(rowCount).toBeGreaterThanOrEqual(20);

    // Verify first and last row data
    const tableText = await table.innerText();
    expect(tableText).toContain('web-frontend-a1b2');
    expect(tableText).toContain('etcd-m9n0');
    expect(tableText).toContain('CrashLoop');

    // Table container should handle overflow (scrollable wrapper)
    const tableContainer = table.locator('..');
    const overflow = await tableContainer.evaluate(el => {
      const cs = window.getComputedStyle(el);
      return cs.overflowX;
    });
    expect(overflow).toBe('auto');
  });

  test('table with special characters and empty cells', async ({ page, mockApi }) => {
    mockApi.setResponse('specialCharsTable');
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    await sendAndWait(page, 'show alerts', 'Alert Summary');

    const table = page.locator('table').first();
    await expect(table).toBeVisible();

    const tableText = await table.innerText();

    // Inline code in table cells should render (not raw backticks)
    expect(tableText).toContain('ip-10-0-1-42');
    expect(tableText).not.toContain('`ip-10-0-1-42`');

    // Bold in table cells
    expect(tableText).toContain('worker-xyz');

    // Emojis should render
    expect(tableText).toContain('✅');
    expect(tableText).toContain('❌');
    expect(tableText).toContain('⚠️');

    // Empty cells should not break table structure
    const allCells = table.locator('td');
    const cellCount = await allCells.count();
    expect(cellCount).toBe(16); // 4 rows × 4 columns

    // No raw pipe chars in rendered output
    const bodyText = await page.locator('body').innerText();
    expect(bodyText).not.toContain('|---|');
  });

  test('multiple tables in a single response', async ({ page, mockApi }) => {
    mockApi.setResponse('multiTable');
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    await sendAndWait(page, 'compare before after', 'Improvements');

    // Should render 2 separate tables
    const tables = page.locator('table');
    const tableCount = await tables.count();
    expect(tableCount).toBe(2);

    // First table: Before
    const table1Text = await tables.nth(0).innerText();
    expect(table1Text).toContain('120ms');
    expect(table1Text).toContain('0.5%');

    // Second table: After
    const table2Text = await tables.nth(1).innerText();
    expect(table2Text).toContain('85ms');
    expect(table2Text).toContain('0.2%');

    // Headings between tables should also render
    const h3s = page.locator('h3');
    const h3Texts = await h3s.allInnerTexts();
    expect(h3Texts.some(t => t.includes('Before'))).toBe(true);
    expect(h3Texts.some(t => t.includes('After'))).toBe(true);
  });

  test('screenshot: large table overflow behavior', async ({ page, mockApi }) => {
    mockApi.setResponse('largeTable');
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    await sendAndWait(page, 'list resources', 'etcd-m9n0');

    const table = page.locator('table').first();
    await expect(table).toBeVisible();
    await table.screenshot({ path: 'tests/e2e/screenshots/edge-large-table.png' });
  });

  test('screenshot: special chars table', async ({ page, mockApi }) => {
    mockApi.setResponse('specialCharsTable');
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    await sendAndWait(page, 'show alerts', 'Alert Summary');

    const table = page.locator('table').first();
    await expect(table).toBeVisible();
    await table.screenshot({ path: 'tests/e2e/screenshots/edge-special-chars-table.png' });
  });
});
