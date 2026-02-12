/**
 * AgenticAIOps E2E Test Fixtures
 * 
 * Extends Playwright's base test with:
 * - API mocking (so E2E tests work without live backend)
 * - Common page objects
 * - Helper utilities
 */
import { test as base, expect } from '@playwright/test';

/**
 * Mock API responses for /api/chat
 * Allows E2E tests to run independently of the backend
 */
const MOCK_RESPONSES = {
  // Markdown table response — for Bug-008 verification
  table: {
    response: `Here are the current pod statuses:

| Pod Name | Namespace | Status | Restarts | CPU | Memory |
|----------|-----------|--------|----------|-----|--------|
| api-server-7d4b | production | Running | 0 | 45m | 128Mi |
| worker-node-3f2a | production | Running | 2 | 120m | 256Mi |
| redis-cache-1b8c | production | Running | 0 | 15m | 64Mi |
| nginx-ingress-9e1f | kube-system | Running | 0 | 8m | 32Mi |

All pods are healthy. Worker node has 2 restarts in the last 24h — worth monitoring.`,
    model: 'claude-sonnet',
    tokens: 245,
    latency: 1.2,
  },

  // Default response
  default: {
    response: `✅ **Health Check Complete**

All systems operational:
- **API Server**: Running (latency: 12ms)
- **Database**: Connected (pool: 8/20)
- **Cache**: Hit rate 94.3%
- **Queue**: 0 pending jobs

No issues detected.`,
    model: 'claude-sonnet',
    tokens: 120,
    latency: 0.8,
  },

  // Complex nested markdown (lists + code + table)
  complex: {
    response: `## RCA Analysis

**Root Cause**: OOMKilled on worker pods

### Evidence
1. Memory usage spiked at 14:32 UTC
2. No HPA configured for the deployment

\`\`\`yaml
resources:
  limits:
    memory: "256Mi"  # Too low
  requests:
    memory: "128Mi"
\`\`\`

### Affected Resources

| Resource | Impact | Severity |
|----------|--------|----------|
| worker-deployment | 3 pods restarted | High |
| api-gateway | Timeout errors | Medium |
| user-service | Degraded | Low |

### Recommendation
Increase memory limits to \`512Mi\` and enable HPA.`,
    model: 'claude-opus',
    tokens: 380,
    latency: 3.1,
  },

  // Edge case: single-row table (minimal)
  singleRowTable: {
    response: `Only one result found:

| Metric | Value |
|--------|-------|
| CPU Usage | 98.7% |

Action required.`,
    model: 'claude-sonnet',
    tokens: 45,
    latency: 0.5,
  },

  // Edge case: large table (20 rows)
  largeTable: {
    response: `## Full Resource Inventory

| # | Resource | Type | Region | Status | Age | CPU | Memory | Disk | Network |
|---|----------|------|--------|--------|-----|-----|--------|------|---------|
| 1 | web-frontend-a1b2 | Pod | us-east-1 | Running | 14d | 120m | 256Mi | 1Gi | 10Mbps |
| 2 | web-frontend-c3d4 | Pod | us-east-1 | Running | 14d | 115m | 248Mi | 1Gi | 9Mbps |
| 3 | api-server-e5f6 | Pod | us-east-1 | Running | 7d | 200m | 512Mi | 2Gi | 25Mbps |
| 4 | api-server-g7h8 | Pod | us-east-1 | Running | 7d | 195m | 504Mi | 2Gi | 24Mbps |
| 5 | worker-i9j0 | Pod | us-west-2 | Running | 3d | 500m | 1Gi | 5Gi | 5Mbps |
| 6 | worker-k1l2 | Pod | us-west-2 | CrashLoop | 3d | 0m | 0Mi | 5Gi | 0Mbps |
| 7 | redis-m3n4 | Pod | us-east-1 | Running | 30d | 50m | 128Mi | 512Mi | 15Mbps |
| 8 | redis-o5p6 | Pod | us-east-1 | Running | 30d | 48m | 124Mi | 512Mi | 14Mbps |
| 9 | postgres-q7r8 | Pod | us-east-1 | Running | 60d | 300m | 2Gi | 50Gi | 30Mbps |
| 10 | postgres-s9t0 | Pod | us-east-1 | Running | 60d | 290m | 1.9Gi | 50Gi | 28Mbps |
| 11 | kafka-u1v2 | Pod | us-west-2 | Running | 21d | 400m | 1Gi | 20Gi | 50Mbps |
| 12 | kafka-w3x4 | Pod | us-west-2 | Running | 21d | 380m | 980Mi | 20Gi | 48Mbps |
| 13 | kafka-y5z6 | Pod | us-west-2 | Running | 21d | 410m | 1Gi | 20Gi | 52Mbps |
| 14 | nginx-a7b8 | Pod | us-east-1 | Running | 45d | 30m | 64Mi | 256Mi | 100Mbps |
| 15 | nginx-c9d0 | Pod | us-east-1 | Running | 45d | 28m | 60Mi | 256Mi | 98Mbps |
| 16 | monitor-e1f2 | Pod | us-east-1 | Running | 10d | 80m | 256Mi | 1Gi | 5Mbps |
| 17 | logger-g3h4 | Pod | us-east-1 | Running | 10d | 60m | 192Mi | 10Gi | 8Mbps |
| 18 | cron-i5j6 | Pod | us-west-2 | Completed | 1d | 0m | 0Mi | 512Mi | 0Mbps |
| 19 | batch-k7l8 | Pod | us-west-2 | Running | 2d | 800m | 2Gi | 10Gi | 3Mbps |
| 20 | etcd-m9n0 | Pod | us-east-1 | Running | 90d | 100m | 512Mi | 8Gi | 20Mbps |

Total: 20 resources across 2 regions. 1 pod in CrashLoop state.`,
    model: 'claude-opus',
    tokens: 820,
    latency: 4.2,
  },

  // Edge case: table with special characters and empty cells
  specialCharsTable: {
    response: `## Alert Summary

| Alert | Source | Message | Resolved? |
|-------|--------|---------|-----------|
| CPU > 95% | prometheus | Node \`ip-10-0-1-42\` critical | ✅ Yes |
| OOM Kill | k8s-events | Pod **worker-xyz** killed | ❌ No |
| Disk 90% | cloudwatch |  |  |
| Latency p99 > 2s | datadog | API gateway — \`/api/v2/users\` | ⚠️ Investigating |

Notes:
- Row 3 has empty message & resolution (edge case for rendering)
- Special chars: \`backticks\`, **bold**, emojis ✅❌⚠️`,
    model: 'claude-sonnet',
    tokens: 200,
    latency: 1.5,
  },

  // Edge case: multiple tables in a single response
  multiTable: {
    response: `## Comparison Report

### Before (2024-01-01)

| Service | Latency | Error Rate |
|---------|---------|------------|
| API | 120ms | 0.5% |
| Web | 45ms | 0.1% |

### After (2024-01-15)

| Service | Latency | Error Rate |
|---------|---------|------------|
| API | 85ms | 0.2% |
| Web | 38ms | 0.05% |

Improvements: API latency down 29%, error rate down 60%.`,
    model: 'claude-sonnet',
    tokens: 180,
    latency: 1.1,
  },
};

/**
 * Centralized timeouts — adjust per environment via E2E_SLOW=1
 * (Reviewer feedback: avoid hardcoded timeouts scattered across specs)
 */
const isSlow = !!process.env.E2E_SLOW || !!process.env.CI;
export const TIMEOUTS = {
  /** Wait for an assistant response to appear in the DOM */
  response: isSlow ? 30_000 : 15_000,
  /** Wait for a specific UI element to be visible */
  element: isSlow ? 20_000 : 10_000,
  /** Short pause (only used in screenshot tests) */
  settle: isSlow ? 3_000 : 1_000,
};

/**
 * Extended test fixture with API mocking support.
 */
export const test = base.extend({
  /**
   * mockApi: intercepts /api/chat and returns controlled responses.
   * Use `mockApi.setResponse(key)` to switch mock data.
   */
  mockApi: async ({ page }, use) => {
    let currentKey = 'default';

    const mock = {
      setResponse(key) {
        currentKey = key;
      },
      getResponses() {
        return MOCK_RESPONSES;
      },
    };

    // Intercept all /api/chat calls
    // ⚠️ RISK: Current mock uses JSON (matching AgentChat.jsx's fetch→json pattern).
    //    If frontend switches to SSE streaming (text/event-stream), this mock
    //    MUST be updated to use route.fulfill with chunked SSE format.
    //    Ref: Reviewer feedback 2026-02-12, Orchestrator confirmation.
    await page.route('**/api/chat', async (route) => {
      const body = MOCK_RESPONSES[currentKey] || MOCK_RESPONSES.default;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(body),
      });
    });

    // Intercept other API calls to prevent network errors
    await page.route('**/api/**', async (route) => {
      const url = route.request().url();
      // Let /api/chat through (handled above)
      if (url.includes('/api/chat')) {
        return route.fallback();
      }
      // Default empty response for other endpoints
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: [], status: 'ok' }),
      });
    });

    await use(mock);
  },
});

export { expect };
export { MOCK_RESPONSES };
