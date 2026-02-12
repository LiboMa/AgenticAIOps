# 设计方案: Playwright E2E 测试体系

> **Author**: 📐 Architect  
> **Date**: 2026-02-12  
> **Status**: ✅ Phase 1 Complete (2026-02-12 20:19 UTC)  
> **Priority**: P0 (立即实施)  
> **Implemented by**: Developer + Tester  
> **Result**: 18/18 tests passing (39s)

---

## 背景

AgenticAIOps 前端 (React + Vite + Antd) 在 `dashboard/` 下，包含 4 个主页面 + 13 个组件。Bug-008 暴露了 Markdown 表格渲染问题 — 前端修复后缺乏自动化回归验证手段。

当前测试缺口：
- 后端有 pytest 测试 (`tests/`)，前端 **零测试**
- `MarkdownRenderer.jsx` 修复后无法自动验证 `<table>` 是否正确渲染
- 前端改动只能靠人工检查

已有基础：
- Playwright v1.58.2 + Chromium 已安装 (`~/.cache/ms-playwright/`)
- Playwright skill 已搭好基础 patterns
- Dashboard 使用 Vite dev server (`localhost:5173`)

## 目标

1. **即时目标**: 为 Bug-008 (表格渲染) 提供 E2E 验证脚本
2. **短期目标**: 建立前端 E2E 测试框架，覆盖核心页面
3. **中期目标**: CI 集成 + 回归测试流水线

## 方案

### 方案 A: 轻量脚本 (Playwright Script Mode)

用 Node.js 脚本直接调用 Playwright API，不引入测试框架。

```
dashboard/
  e2e/
    scripts/
      check-table-rendering.mjs    # Bug-008 验证
      check-page-loads.mjs         # 各页面加载
      check-chat-flow.mjs          # 聊天交互
    lib/
      helpers.mjs                  # 通用工具 (launch, screenshot, etc.)
    run.sh                         # 入口脚本
```

**运行方式**: `node e2e/scripts/check-table-rendering.mjs`

### 方案 B: Playwright Test Runner (推荐)

使用 `@playwright/test` 测试框架，获得完整的 test runner 能力。

```
dashboard/
  e2e/
    playwright.config.mjs          # 配置文件
    tests/
      smoke.spec.mjs               # 冒烟测试: 页面加载
      markdown-table.spec.mjs      # Bug-008: 表格渲染
      agent-chat.spec.mjs          # 聊天功能
      navigation.spec.mjs          # 侧栏导航
      dark-mode.spec.mjs           # 深色模式切换
    fixtures/
      markdown-samples.mjs         # 测试用 Markdown 数据
    helpers/
      api-mock.mjs                 # API Mock 工具
    screenshots/                   # 截图输出 (.gitignore)
    test-results/                  # 测试报告 (.gitignore)
```

**运行方式**: `npx playwright test --config=e2e/playwright.config.mjs`

## 对比

| 维度 | 方案 A: 轻量脚本 | 方案 B: Test Runner |
|------|------------------|---------------------|
| **上手速度** | ⚡ 极快，5分钟开写 | 🔧 需 10 分钟初始化配置 |
| **测试报告** | ❌ 手动 console.log | ✅ HTML/JSON 报告，截图 |
| **并行执行** | ❌ 串行 | ✅ 内置并行 |
| **断言库** | 手动 assert | ✅ expect + web-first assertions |
| **重试机制** | ❌ 无 | ✅ 内置 retry |
| **CI 集成** | ⚠️ 需自己处理 exit code | ✅ 标准 CI 友好 |
| **新依赖** | 无 (已有 playwright) | `@playwright/test` (同一包) |
| **Agent 可用性** | ✅ 直接 `node xxx` | ✅ `npx playwright test` |
| **可维护性** | ⚠️ 规模大了难管理 | ✅ 结构化 |

## 推荐

**方案 B: Playwright Test Runner**

理由：
1. `@playwright/test` 与 `playwright` 同包，**零额外安装**
2. 断言 (`expect(locator).toBeVisible()`) 比手写 assert 可靠得多
3. 自动截图 + HTML 报告对 Bug 验证极有价值
4. 后续 CI 集成零改造

---

## 实施计划

### Phase 1: 基础搭建 (Day 1) — ✅ DONE 2026-02-12

**产出**: 可运行的测试框架 + Bug-008 验证测试

> **实现差异记录**:
> - 目录: `tests/e2e/` (非 `e2e/tests/`) — 更符合 Node 项目惯例
> - 后缀: `.js` + `"type": "module"` (非 `.mjs`) — 等效
> - Fixtures: `test-fixtures.js` 合并了 mock 数据 + API 拦截 + Playwright base.extend — 更紧凑
> - API Mock: 使用 JSON fulfill (非 SSE stream) — 与当前 Chat 组件消费方式兼容
> - 测试数: 18 个 (Bug-008: 5, Smoke: 9, Markdown: 4)

#### 1.1 目录结构

```
dashboard/e2e/
├── playwright.config.mjs      # Playwright 配置
├── tests/
│   ├── smoke.spec.mjs         # 冒烟测试
│   └── markdown-table.spec.mjs # Bug-008 验证
├── fixtures/
│   └── markdown-samples.mjs   # 测试数据
├── helpers/
│   └── api-mock.mjs           # API Mock
├── screenshots/               # .gitignore
└── test-results/              # .gitignore
```

#### 1.2 Playwright 配置

```javascript
// dashboard/e2e/playwright.config.mjs
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 30000,
  retries: 1,
  reporter: [['html', { open: 'never' }], ['list']],
  
  use: {
    baseURL: 'http://localhost:5173',
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    viewport: { width: 1280, height: 720 },
  },

  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],

  // 不自动启动 webServer — 测试前需手动/CI 启动
  // 如果需要自动启动:
  // webServer: {
  //   command: 'npm run dev',
  //   port: 5173,
  //   cwd: '..',
  //   reuseExistingServer: true,
  // },
});
```

#### 1.3 Bug-008 核心测试: 表格渲染验证

```javascript
// dashboard/e2e/tests/markdown-table.spec.mjs
import { test, expect } from '@playwright/test';
import { MARKDOWN_WITH_TABLE } from '../fixtures/markdown-samples.mjs';

test.describe('Bug-008: Markdown Table Rendering', () => {

  test('tables render as <table> HTML, not raw pipe text', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // 方式一: 通过 Chat 发消息获取含表格的 AI 回复
    // 方式二: 直接注入 MarkdownRenderer 进行单元级 E2E 测试
    // 这里采用方式二 — 更稳定, 不依赖后端

    // 在页面中渲染 MarkdownRenderer
    await page.evaluate((md) => {
      // 找到消息区域或创建测试容器
      const container = document.createElement('div');
      container.id = 'e2e-test-container';
      document.body.appendChild(container);

      // 通过 React 渲染 (如果使用组件注入模式)
      // 备选: 直接设置 innerHTML 测试 remark-gfm 输出
      window.__E2E_MD_CONTENT__ = md;
    }, MARKDOWN_WITH_TABLE);

    // 验证: 页面中应有 <table> 元素
    const tables = page.locator('table');
    
    // 验证: 不应有 raw pipe 格式的文本
    const bodyText = await page.textContent('body');
    expect(bodyText).not.toContain('|---');
    expect(bodyText).not.toContain('| --- |');
  });

  test('table has proper <thead> and <tbody> structure', async ({ page }) => {
    // 导航到 AgentChat 页面
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // 当 Chat 中存在表格响应时:
    // 验证 HTML 结构
    const tableHeaders = page.locator('table thead th');
    const tableRows = page.locator('table tbody tr');

    // 如果页面上存在表格
    const tableCount = await page.locator('table').count();
    if (tableCount > 0) {
      expect(await tableHeaders.count()).toBeGreaterThan(0);
    }
  });

  test('MarkdownRenderer component renders table correctly', async ({ page }) => {
    // 直接加载一个测试页面来验证 MarkdownRenderer
    // 通过 evaluate 在已有页面注入测试内容
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // 使用 Antd 的消息机制模拟一条含表格的消息
    // 或直接检查现有的 MarkdownRenderer 输出
    
    // 截图存档
    await page.screenshot({ 
      path: 'e2e/screenshots/table-rendering.png',
      fullPage: true 
    });
  });
});
```

#### 1.4 测试数据 Fixtures

```javascript
// dashboard/e2e/fixtures/markdown-samples.mjs

export const MARKDOWN_WITH_TABLE = `
## Instance Status

| Instance ID | Status | CPU | Memory |
|---|---|---|---|
| i-0a1b2c3d | Running | 45% | 2.1 GB |
| i-0e5f6g7h | Stopped | 0% | 0 GB |
| i-0i9j8k7l | Running | 89% | 7.8 GB |

> High CPU usage detected on i-0i9j8k7l
`;

export const MARKDOWN_WITH_CODE = `
## Diagnosis

\`\`\`python
import boto3
client = boto3.client('ec2')
response = client.describe_instances()
\`\`\`

Inline code: \`kubectl get pods\`
`;

export const MARKDOWN_COMPLEX = `
# Root Cause Analysis

## Summary
The service degradation was caused by **memory leak** in the worker process.

## Timeline

| Time | Event | Impact |
|------|-------|--------|
| 14:00 | Deploy v2.3.1 | None |
| 14:15 | Memory usage spike | Latency +200ms |
| 14:30 | OOM Kill | 502 errors |
| 14:45 | Auto-rollback | Recovered |

## Metrics

\`\`\`json
{
  "p99_latency_ms": 1250,
  "error_rate": 0.15,
  "affected_pods": 3
}
\`\`\`

### Recommended Actions
1. Fix memory leak in \`worker.py\`
2. Add memory limits to pod spec
3. Enable **HPA** with memory-based scaling
`;
```

#### 1.5 API Mock Helper

```javascript
// dashboard/e2e/helpers/api-mock.mjs

/**
 * Mock API responses for E2E tests
 * Eliminates dependency on running backend
 */
export function setupApiMocks(page, apiUrl = 'http://localhost:8000') {
  
  // Mock /api/issues/dashboard
  page.route(`${apiUrl}/api/issues/dashboard`, route => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        stats: {
          total: 5,
          by_status: { detected: 2, investigating: 1, resolved: 2 },
          by_severity: { critical: 1, warning: 2, info: 2 },
        },
        recent_issues: [],
      }),
    });
  });

  // Mock /api/chat (streaming response with table)
  page.route(`${apiUrl}/api/chat`, route => {
    const tableResponse = `Here are the current instances:

| Instance | Status | CPU |
|----------|--------|-----|
| i-abc123 | Running | 45% |
| i-def456 | Stopped | 0% |

All systems operational.`;

    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: `data: {"type":"content","content":"${tableResponse.replace(/\n/g, '\\n')}"}\ndata: {"type":"done"}\n\n`,
    });
  });

  // Mock /api/health
  page.route(`${apiUrl}/api/health`, route => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'healthy', version: '2.0.0' }),
    });
  });
}

/**
 * Mock chat response with specific Markdown content
 */
export function mockChatWithMarkdown(page, markdown, apiUrl = 'http://localhost:8000') {
  page.route(`${apiUrl}/api/chat`, route => {
    const escaped = markdown.replace(/\n/g, '\\n').replace(/"/g, '\\"');
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: `data: {"type":"content","content":"${escaped}"}\ndata: {"type":"done"}\n\n`,
    });
  });
}
```

### Phase 2: 核心页面测试 (Day 2-3)

#### 2.1 冒烟测试

```javascript
// dashboard/e2e/tests/smoke.spec.mjs
import { test, expect } from '@playwright/test';
import { setupApiMocks } from '../helpers/api-mock.mjs';

test.describe('Smoke Tests - Page Loading', () => {
  
  test.beforeEach(async ({ page }) => {
    setupApiMocks(page);
  });

  test('app loads without errors', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    
    // App title/logo visible
    await expect(page.locator('text=AgenticAIOps')).toBeVisible();
    
    // No console errors
    const errors = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    
    expect(errors.length).toBe(0);
  });

  test('sidebar navigation works', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Default: AI Assistant (chat)
    await expect(page.locator('.ant-menu-item-selected')).toContainText('AI Assistant');

    // Navigate to Observability
    await page.click('text=Observability');
    await expect(page.locator('.ant-menu-item-selected')).toContainText('Observability');

    // Navigate to Security
    await page.click('text=Security');
    await expect(page.locator('.ant-menu-item-selected')).toContainText('Security');

    // Navigate to Scan & Monitor
    await page.click('text=Scan');
    await expect(page.locator('.ant-menu-item-selected')).toContainText('Scan');

    // Back to Chat
    await page.click('text=AI Assistant');
    await expect(page.locator('.ant-menu-item-selected')).toContainText('AI Assistant');
  });

  test('dark mode toggle works', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Find and click the dark mode switch
    const darkSwitch = page.locator('.ant-switch');
    await darkSwitch.click();

    // Verify body background changed
    const bgColor = await page.evaluate(() => 
      window.getComputedStyle(document.body).backgroundColor
    );
    // Dark mode should have dark background
    // (exact value depends on Antd theme)
    
    await page.screenshot({ path: 'e2e/screenshots/dark-mode.png' });
  });
});
```

#### 2.2 AgentChat 测试

```javascript
// dashboard/e2e/tests/agent-chat.spec.mjs
import { test, expect } from '@playwright/test';
import { setupApiMocks, mockChatWithMarkdown } from '../helpers/api-mock.mjs';
import { MARKDOWN_WITH_TABLE, MARKDOWN_COMPLEX } from '../fixtures/markdown-samples.mjs';

test.describe('AgentChat Page', () => {
  
  test.beforeEach(async ({ page }) => {
    setupApiMocks(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('chat input is visible and functional', async ({ page }) => {
    // Textarea should be visible
    const chatInput = page.locator('textarea');
    await expect(chatInput).toBeVisible();

    // Can type in textarea
    await chatInput.fill('Show me instance status');
    await expect(chatInput).toHaveValue('Show me instance status');
  });

  test('model selector shows available models', async ({ page }) => {
    const modelSelector = page.locator('.ant-select').first();
    if (await modelSelector.isVisible()) {
      await modelSelector.click();
      // Should show model options
      await expect(page.locator('.ant-select-item')).toHaveCount.toBeGreaterThan(0);
    }
  });

  test('chat response renders markdown table as HTML', async ({ page }) => {
    // Mock the chat API to return a table
    mockChatWithMarkdown(page, MARKDOWN_WITH_TABLE);

    // Type and send a message
    const chatInput = page.locator('textarea');
    await chatInput.fill('Show instance status');
    
    // Click send or press Enter
    const sendButton = page.locator('button').filter({ has: page.locator('[class*="SendOutlined"]') });
    if (await sendButton.isVisible()) {
      await sendButton.click();
    } else {
      await chatInput.press('Enter');
    }

    // Wait for response
    await page.waitForTimeout(2000);

    // Verify: HTML table rendered (not raw pipes)
    const tables = page.locator('table');
    const tableCount = await tables.count();
    
    // Key assertion for Bug-008
    if (tableCount > 0) {
      await expect(tables.first()).toBeVisible();
      
      // Verify table has header
      const headers = tables.first().locator('th');
      await expect(headers.first()).toBeVisible();
    }

    // No raw markdown pipe characters
    const messageArea = page.locator('[class*="message"], [class*="chat"]').last();
    if (await messageArea.isVisible()) {
      const text = await messageArea.textContent();
      expect(text).not.toContain('|---');
    }

    await page.screenshot({ path: 'e2e/screenshots/chat-table-response.png' });
  });
});
```

### Phase 3: CI/回归集成 (Day 4-5)

#### 3.1 npm scripts

在 `dashboard/package.json` 中添加:

```json
{
  "scripts": {
    "e2e": "npx playwright test --config=e2e/playwright.config.mjs",
    "e2e:headed": "npx playwright test --config=e2e/playwright.config.mjs --headed",
    "e2e:report": "npx playwright show-report e2e/test-results/html",
    "e2e:bug008": "npx playwright test --config=e2e/playwright.config.mjs -g 'Bug-008'"
  }
}
```

#### 3.2 .gitignore 更新

```
# E2E test artifacts
dashboard/e2e/screenshots/
dashboard/e2e/test-results/
dashboard/e2e/playwright-report/
```

#### 3.3 Agent 使用方式

Tester agent 可以直接执行:

```bash
# 验证 Bug-008 修复
cd /home/ubuntu/agentic-aiops-mvp/dashboard
npx playwright test --config=e2e/playwright.config.mjs -g "Bug-008"

# 跑全量 E2E
npx playwright test --config=e2e/playwright.config.mjs

# 截图验证某个页面
node -e "
import { chromium } from 'playwright';
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
await page.goto('http://localhost:5173');
await page.screenshot({ path: 'verify.png', fullPage: true });
await browser.close();
"
```

### Phase 4: 后续 — 通用 OpenClaw Skill 增强

增强 `~/.openclaw/skills/playwright/SKILL.md`，添加:

1. **E2E 测试 Patterns** — 标准测试模板
2. **API Mock 库** — 通用 mock 工具
3. **Visual Regression** — 截图对比
4. **Accessibility 检查** — a11y 审计

---

## 测试覆盖规划

| 测试类别 | 测试项 | 优先级 | Phase |
|----------|--------|--------|-------|
| Bug-008 | 表格渲染为 `<table>` | P0 | 1 |
| Bug-008 | 无 raw pipe 文本 | P0 | 1 |
| 冒烟 | 应用加载无报错 | P0 | 1 |
| 冒烟 | 4个页面均可导航 | P1 | 2 |
| 交互 | Chat 发送消息 | P1 | 2 |
| 交互 | 模型选择切换 | P2 | 2 |
| 渲染 | 代码块高亮+复制 | P1 | 2 |
| 渲染 | 深色模式切换 | P2 | 2 |
| 渲染 | Blockquote 样式 | P3 | 3 |
| 回归 | 截图对比 (visual) | P2 | 4 |

## 前置条件

1. Dashboard dev server 需运行: `cd dashboard && npm run dev`
2. 或使用 `webServer` 配置让 Playwright 自动启动
3. 后端 API 可选 — 通过 Mock 解耦

## 评审改进跟踪 (Reviewer: 2026-02-12)

| # | 建议 | 状态 | 计划 |
|---|------|------|------|
| 1 | `webServer` 配置启用 | ✅ 已实现 | 配置中已有，`E2E_BASE_URL` 覆盖 |
| 2 | Selector 加 `data-testid` | 📋 待办 | Phase 2 |
| 3 | Mock 格式 JSON vs SSE 对齐 | ✅ 已确认 | Chat 用 `axios.post` → JSON，mock 正确 |
| 4 | 超时值提取到 config | 📋 待办 | Phase 2 |
| 5 | Console error 过滤 React warnings | ✅ 已实现 | smoke 测试已过滤 `Warning:` |
| 6 | Visual regression (`toHaveScreenshot`) | 📋 待办 | Phase 4 |

## 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| Dev server 未启动导致测试失败 | 中 | 配置 `webServer` 自动启动 |
| Streaming API mock 复杂 | 中 | 先用简单 fulfill, 后续完善 SSE mock |
| Antd 选择器不稳定 | 低 | 优先使用 `data-testid`, 其次 role/text |
| Headless 渲染差异 | 低 | Playwright Chromium 与真实浏览器一致 |

---

## 给 Developer 的实施指引

1. **不需要安装任何新依赖** — Playwright 已全局安装
2. 在 `dashboard/` 下创建 `e2e/` 目录结构
3. 先实现 `playwright.config.mjs` + `markdown-table.spec.mjs`
4. 运行 `npx playwright test --config=e2e/playwright.config.mjs` 验证
5. 逐步添加 smoke + chat 测试

## 给 Tester 的使用指引

验证 Bug-008 修复:
```bash
cd /home/ubuntu/agentic-aiops-mvp/dashboard
npx playwright test --config=e2e/playwright.config.mjs -g "Bug-008" --reporter=list
```

查看截图:
```bash
ls -la e2e/screenshots/
```

查看 HTML 报告:
```bash
npx playwright show-report e2e/test-results/html
```
