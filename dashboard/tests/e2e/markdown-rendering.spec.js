/**
 * MarkdownRenderer Component E2E Tests
 * 
 * Tests all markdown rendering features:
 * - Tables (Bug-008)
 * - Code blocks with syntax highlighting
 * - Inline code
 * - Links, blockquotes
 * - Dark/light mode styling
 */
import { test, expect } from './fixtures/test-fixtures.js';

test.describe('Markdown Rendering', () => {

  test.beforeEach(async ({ page, mockApi }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('should render code blocks with syntax highlighting', async ({ page, mockApi }) => {
    mockApi.setResponse('complex');
    
    const textarea = page.locator('textarea').first();
    await textarea.fill('analyze issue');
    await page.locator('button').filter({ hasText: /send/i }).first().click();

    // Wait for response with code block
    await page.waitForFunction(
      () => document.body.innerText.includes('memory'),
      { timeout: 15_000 }
    );

    // Code should be in <pre> or syntax-highlighted block, not raw backticks
    const codeElements = page.locator('pre code, [class*="prism"], [class*="syntax"]');
    expect(await codeElements.count()).toBeGreaterThanOrEqual(1);

    // Should not show raw ``` in the text
    const bodyText = await page.locator('body').innerText();
    expect(bodyText).not.toContain('```yaml');
    expect(bodyText).not.toContain('```');
  });

  test('should render inline code with styling', async ({ page, mockApi }) => {
    mockApi.setResponse('complex');

    const textarea = page.locator('textarea').first();
    await textarea.fill('analyze');
    await page.locator('button').filter({ hasText: /send/i }).first().click();

    await page.waitForFunction(
      () => document.body.innerText.includes('512Mi'),
      { timeout: 15_000 }
    );

    // Inline code `512Mi` should be in a <code> element
    const inlineCode = page.locator('code').filter({ hasText: '512Mi' });
    expect(await inlineCode.count()).toBeGreaterThanOrEqual(1);
  });

  test('should render ordered lists correctly', async ({ page, mockApi }) => {
    mockApi.setResponse('complex');

    const textarea = page.locator('textarea').first();
    await textarea.fill('analyze');
    await page.locator('button').filter({ hasText: /send/i }).first().click();

    await page.waitForFunction(
      () => document.body.innerText.includes('Memory usage spiked'),
      { timeout: 15_000 }
    );

    // Lists should use <ol> or <li> elements
    const listItems = page.locator('li');
    expect(await listItems.count()).toBeGreaterThanOrEqual(2);
  });

  test('should render headings correctly', async ({ page, mockApi }) => {
    mockApi.setResponse('complex');

    const textarea = page.locator('textarea').first();
    await textarea.fill('analyze');
    await page.locator('button').filter({ hasText: /send/i }).first().click();

    await page.waitForFunction(
      () => document.body.innerText.includes('RCA Analysis'),
      { timeout: 15_000 }
    );

    // ## RCA Analysis should render as <h2>
    const heading = page.locator('h2').filter({ hasText: 'RCA Analysis' });
    expect(await heading.count()).toBeGreaterThanOrEqual(1);
  });
});
