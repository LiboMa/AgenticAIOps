// @ts-check
import { defineConfig, devices } from '@playwright/test';

/**
 * AgenticAIOps Dashboard - Playwright E2E Test Configuration
 * 
 * Usage:
 *   npx playwright test              # Run all tests
 *   npx playwright test --ui         # Open UI mode
 *   npx playwright test --grep "Bug" # Run tests matching pattern
 */
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ['html', { open: 'never', outputFolder: 'playwright-report' }],
    ['list'],
  ],
  
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    headless: true,
    // Default timeout for actions like click, fill, etc.
    actionTimeout: 10_000,
  },

  /* Global timeout per test */
  timeout: 60_000,

  /* Run local dev server before tests if not already running */
  webServer: process.env.E2E_BASE_URL ? undefined : {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
    timeout: 30_000,
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
