/**
 * Bug-008: Markdown Table Rendering E2E Test
 * 
 * Verifies that Markdown tables in AI responses are rendered as proper
 * HTML <table> elements (via react-markdown + remark-gfm), NOT as raw
 * pipe-delimited text.
 * 
 * Regression target: MarkdownRenderer.jsx + AgentChat.jsx
 */
import { test, expect, MOCK_RESPONSES } from './fixtures/test-fixtures.js';

test.describe('Bug-008: Table Rendering', () => {
  
  test.beforeEach(async ({ page, mockApi }) => {
    mockApi.setResponse('table');
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('should render markdown tables as HTML <table> not raw pipes', async ({ page }) => {
    // Find the chat input and send a message that triggers a table response
    const textarea = page.locator('textarea').first();
    await textarea.fill('show pod status');
    
    // Click send button
    const sendBtn = page.locator('button').filter({ hasText: /send/i }).first();
    await sendBtn.click();

    // Wait for the assistant response to appear (contains "Pod Name")
    const responseArea = page.locator('.message-wrapper').last();
    await expect(responseArea).toBeVisible({ timeout: 15_000 });

    // Wait for table content to render
    await page.waitForFunction(
      () => document.body.innerText.includes('api-server'),
      { timeout: 15_000 }
    );

    // ✅ CORE ASSERTION: HTML <table> must exist inside the chat area
    const tables = page.locator('table');
    const tableCount = await tables.count();
    expect(tableCount).toBeGreaterThanOrEqual(1);

    // ✅ Table should have proper structure: thead, th, td
    const firstTable = tables.first();
    await expect(firstTable).toBeVisible();
    
    const headerCells = firstTable.locator('th');
    expect(await headerCells.count()).toBeGreaterThanOrEqual(4); // Pod Name, Namespace, Status, Restarts...

    const dataCells = firstTable.locator('td');
    expect(await dataCells.count()).toBeGreaterThanOrEqual(4); // At least one data row

    // ✅ Verify specific header text
    await expect(firstTable.locator('th').first()).toContainText('Pod Name');

    // ✅ Verify data cell content
    await expect(firstTable.locator('td').first()).toContainText('api-server');

    // ❌ NEGATIVE: Raw pipe characters should NOT appear as table delimiters
    // (If tables render correctly, there won't be raw "|---|" separators visible)
    const bodyText = await page.locator('body').innerText();
    expect(bodyText).not.toContain('|---|');
    expect(bodyText).not.toContain('| Pod Name |');  // Should be in <th>, not raw text
  });

  test('should render table with proper styling (border, padding)', async ({ page }) => {
    const textarea = page.locator('textarea').first();
    await textarea.fill('show pod status');
    await page.locator('button').filter({ hasText: /send/i }).first().click();

    await page.waitForFunction(
      () => document.body.innerText.includes('api-server'),
      { timeout: 15_000 }
    );

    const table = page.locator('table').first();
    await expect(table).toBeVisible();

    // Styled table should have border-collapse
    const style = await table.evaluate(el => {
      const cs = window.getComputedStyle(el);
      return {
        borderCollapse: cs.borderCollapse,
        width: cs.width,
      };
    });
    expect(style.borderCollapse).toBe('collapse');

    // th cells should have padding
    const thPadding = await page.locator('th').first().evaluate(el => {
      return window.getComputedStyle(el).padding;
    });
    expect(thPadding).not.toBe('0px');
  });

  test('should render multiple rows correctly', async ({ page }) => {
    const textarea = page.locator('textarea').first();
    await textarea.fill('show pod status');
    await page.locator('button').filter({ hasText: /send/i }).first().click();

    await page.waitForFunction(
      () => document.body.innerText.includes('redis-cache'),
      { timeout: 15_000 }
    );

    const table = page.locator('table').first();
    
    // Verify all 4 data rows exist
    const rows = table.locator('tbody tr, tr:not(:first-child)');
    const rowCount = await rows.count();
    expect(rowCount).toBeGreaterThanOrEqual(4); // 4 pods in mock

    // Verify specific pod names appear in table cells
    const tableText = await table.innerText();
    expect(tableText).toContain('api-server');
    expect(tableText).toContain('worker-node');
    expect(tableText).toContain('redis-cache');
    expect(tableText).toContain('nginx-ingress');
  });

  test('should handle table inside complex markdown response', async ({ page, mockApi }) => {
    // Switch to complex mock (lists + code + table)
    mockApi.setResponse('complex');

    const textarea = page.locator('textarea').first();
    await textarea.fill('run RCA analysis');
    await page.locator('button').filter({ hasText: /send/i }).first().click();

    await page.waitForFunction(
      () => document.body.innerText.includes('worker-deployment'),
      { timeout: 15_000 }
    );

    // Table should render even alongside code blocks and lists
    const tables = page.locator('table');
    expect(await tables.count()).toBeGreaterThanOrEqual(1);

    // Code block should also render (not raw backticks)
    const codeBlocks = page.locator('pre code, .prism-code, [class*="syntax"]');
    expect(await codeBlocks.count()).toBeGreaterThanOrEqual(1);

    // The Affected Resources table should have correct data
    const table = tables.first();
    const tableText = await table.innerText();
    expect(tableText).toContain('worker-deployment');
    expect(tableText).toContain('High');
  });

  test('screenshot: table renders visually correct', async ({ page }) => {
    const textarea = page.locator('textarea').first();
    await textarea.fill('show pod status');
    await page.locator('button').filter({ hasText: /send/i }).first().click();

    await page.waitForFunction(
      () => document.body.innerText.includes('api-server'),
      { timeout: 15_000 }
    );

    // Take screenshot for visual inspection
    const table = page.locator('table').first();
    await expect(table).toBeVisible();
    await table.screenshot({ path: 'tests/e2e/screenshots/bug-008-table-render.png' });
    
    // Also full-page screenshot for context
    await page.screenshot({ 
      path: 'tests/e2e/screenshots/bug-008-full-page.png',
      fullPage: true,
    });
  });
});
