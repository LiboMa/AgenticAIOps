# Frontend Refresh Design — v2.0 (简约·克制·Solid)

> **Status**: DRAFT — 待 Ma Ronnie + 团队评审
> **Author**: Architect
> **Date**: 2026-03-08
> **Triggered by**: Ma Ronnie — "Web前端交互已经严重和功能脱节，简约、克制、功能一定要Solid"

---

## §1 问题分析

### 1.1 数据驱动的差距

| 维度 | 数值 |
|------|------|
| 后端 API 端点 | **135** |
| 前端已接入 API | **37** (27%) |
| 未接入的后端 API | **105** (78%) |
| 前端页面 | 13 个文件 (仅 4 个活跃) |
| 前端代码量 | 8,771 行 JSX |
| deprecated 文件 | 2 个 (未清理) |
| UI 框架 | **2 套混用** (Antd 21处 + MUI 42处) |

### 1.2 完全缺失的后端能力

| 后端模块 | API 数 | 功能 | 前端状态 |
|----------|--------|------|----------|
| topology/ | 9 | 拓扑+传播+变更追踪 | ❌ 零接入 |
| health-issues/ | 9 | 健康问题生命周期 | ❌ 零接入 |
| sop/ | 8 | SOP 管理+执行+审批 | ❌ 零接入 |
| rca/ | 7 | RCA 报告+分析+统计 | ❌ 零接入 |
| knowledge/ | 5 | 知识库+案例+统计 | ❌ 零接入 |
| proactive/ | 5 | 巡检+自动检测 | ❌ 零接入 |
| safety/ | 5 | 审批+安全门控 | ❌ 零接入 |
| chaos/ | 4 | 混沌实验 | ❌ 零接入 |
| cloudwatch/ | 4 | 监控指标查询 | ❌ 零接入 |

---

## §2 设计原则

Ma Ronnie 三字诀：

1. **简约** — 信息密度高，不加装饰性元素
2. **克制** — 不堆功能入口，按场景组织，一页一职责
3. **Solid** — 每个交互对应真实 API，有数据显示数据，无数据显示空状态

### 2.1 技术决策

| 决策 | 选择 | 理由 |
|------|------|------|
| UI 框架 | **Antd only** | 砍掉 MUI (42 处迁移)，统一视觉 |
| 图表 | **Recharts** (已有) | 轻量，已在 dependencies |
| 拓扑图 | **Phase 1: Antd Table/List; Phase 2: ReactFlow** | Phase 1 克制，Phase 2 再引入 (~200KB) |
| 状态管理 | **React Query** (已有) | 服务端状态缓存，已配置 |
| 主题 | **深色优先** | Ma Ronnie 偏好，运维场景适合 |
| 路由 | **3 核心视图** | 简约，不超过 5 个顶层入口 |

---

## §3 信息架构 — 3 视图

```
┌─────────────────────────────────────────────────┐
│  AgenticAIOps Dashboard                         │
│  ┌──────┐ ┌───────────┐ ┌──────────┐           │
│  │ Ops  │ │ Diagnose  │ │  Agent   │  ⚙ Config │
│  │ Hub  │ │           │ │ Console  │           │
│  └──────┘ └───────────┘ └──────────┘           │
└─────────────────────────────────────────────────┘
```

### View 1: 🏠 Ops Hub (运维中心) — 主视图

> "一眼看清系统健康状态"

| 区块 | 数据源 | 组件 |
|------|--------|------|
| Health Issues 列表 | `GET /api/health-issues` | `<HealthIssueList>` — 状态标签+严重度+时间 |
| Alert Feed | `GET /api/events/collect` | `<AlertFeed>` — 实时告警流 (5 种解析器标签) |
| Proactive Scan 状态 | `GET /api/proactive/status` | `<ProactiveBadge>` — 上次扫描时间+结果 |
| SOP 快捷执行 | `GET /api/sop/list` | `<SOPQuickActions>` — 最近建议的 SOP |
| Incident 统计 | `GET /api/incident/stats` | `<IncidentStats>` — 4 指标卡片 (open/resolved/MTTA/MTTR) |

**交互**:
- 点击 Health Issue → 展开详情 + RCA 报告
- 点击 Alert → 跳转 Diagnose 视图
- 点击 SOP → 确认执行 (接入 safety/ 审批)

### View 2: 🔍 Diagnose (诊断中心)

> "深入分析一个问题"

| 区块 | 数据源 | 组件 |
|------|--------|------|
| Topology Graph | `GET /api/topology/vpc/{id}` | `<TopologyGraph>` — ReactFlow 拓扑图 |
| Propagation Overlay | `GET /api/topology/vpc/{id}/propagation` | 故障传播热力叠加 |
| Change Timeline | `GET /api/topology/vpc/{id}/changes` | `<ChangeTimeline>` — CloudTrail 变更时间线 |
| RCA Report | `GET /api/rca/reports/{id}` | `<RCAViewer>` — Markdown 渲染的 RCA 报告 |
| Knowledge Similar | `GET /api/knowledge/patterns` | `<SimilarCases>` — 历史相似案例卡片 |

**交互**:
- 拓扑图点击节点 → 显示传播路径 + 影响范围
- 变更时间线标记可疑变更 → 对应 RCA 证据
- RCA 报告内嵌 SOP 建议 → 一键执行

### View 3: 💬 Agent Console (对话中心) — 已有，增强

> "与 Agent 对话，附带上下文"

| 增强 | 数据源 | 变化 |
|------|--------|------|
| 右侧 Context Panel | 当前选中的 HealthIssue | 新增: 对话时显示相关拓扑+RCA |
| Safety 审批通知 | `GET /api/safety/approvals` | 新增: 危险操作弹窗审批 |
| Skills 状态 | `GET /api/registry/status` | 新增: 底部 Skills 可用状态 |

### Config 页面 (合并)

将现有 ScanConfig + SecurityDashboard + Settings 合并为一个 Config 页面:
- Scan 配置
- Skills 管理 (`/api/registry/status` + `/api/plugins`)
- 通知设置 (`/api/notifications/status`)

---

## §4 组件清单

### 4.1 新建组件 (12 个)

| 组件 | 文件 | 估算行数 | 优先级 |
|------|------|----------|--------|
| `HealthIssueList` | `components/HealthIssueList.jsx` | ~150 | P0 |
| `HealthIssueDetail` | `components/HealthIssueDetail.jsx` | ~200 | P0 |
| `AlertFeed` | `components/AlertFeed.jsx` | ~120 | P0 |
| `IncidentStats` | `components/IncidentStats.jsx` | ~80 | P0 |
| `TopologyGraph` | `components/TopologyGraph.jsx` | ~250 | P0 |
| `PropagationOverlay` | `components/PropagationOverlay.jsx` | ~100 | P1 |
| `ChangeTimeline` | `components/ChangeTimeline.jsx` | ~120 | P1 |
| `RCAViewer` | `components/RCAViewer.jsx` | ~150 | P0 |
| `SimilarCases` | `components/SimilarCases.jsx` | ~100 | P1 |
| `SOPQuickActions` | `components/SOPQuickActions.jsx` | ~100 | P1 |
| `SafetyApproval` | `components/SafetyApproval.jsx` | ~80 | P1 |
| `ProactiveBadge` | `components/ProactiveBadge.jsx` | ~50 | P2 |

### 4.2 重构组件 (5 个)

| 现有组件 | 变化 |
|----------|------|
| `AppV2.jsx` | 路由改为 3 视图 + Config |
| `AgentChat.jsx` | 右侧增加 Context Panel |
| `ChatPanel.jsx` / `ChatPanelPD.jsx` | 合并为一个 |
| `ObservabilityList.jsx` | 删除，功能迁入 Ops Hub |
| `SecurityDashboard.jsx` | 迁入 Config |

### 4.3 删除 (清理)

| 文件 | 理由 |
|------|------|
| `deprecated/IssueCenter.jsx` | deprecated |
| `deprecated/App.jsx` | deprecated |
| `IssueCenterPD.jsx` + `OverviewPD.jsx` | PagerDuty 专用，合并入通用 |
| `Diagnosis.jsx` + `CloudServices.jsx` + `Metrics.jsx` | 功能重叠，迁入新视图 |

---

## §5 MUI → Antd 迁移

42 处 MUI 引用需迁移：

| MUI 组件 | Antd 替代 |
|----------|-----------|
| `<Box>` | `<div>` + style |
| `<Typography>` | `<Typography.Text>` / `<Typography.Title>` |
| `<Paper>` | `<Card>` |
| `<Chip>` | `<Tag>` |
| `<IconButton>` | `<Button icon={...}>` |
| `<TextField>` | `<Input>` |
| `<Select>` / `<MenuItem>` | `<Select>` / `<Select.Option>` |
| `<Tabs>` / `<Tab>` | `<Tabs>` / `<Tabs.TabPane>` |
| `<LinearProgress>` | `<Progress>` |
| `@emotion/react` | 可删除 (Antd 不需要) |

完成后删除 `@mui/*` 和 `@emotion/*` 依赖 (~3 packages)。

---

## §6 API Hook 层

统一 API 调用，使用 React Query:

```javascript
// hooks/useHealthIssues.js
export const useHealthIssues = (params) =>
  useQuery({
    queryKey: ['health-issues', params],
    queryFn: () => api.get('/api/health-issues', { params }),
    refetchInterval: 10_000, // 10s 轮询 (告警场景敏感度高)
  })

// hooks/useTopology.js
export const useTopology = (vpcId) =>
  useQuery({
    queryKey: ['topology', vpcId],
    queryFn: () => api.get(`/api/topology/vpc/${vpcId}`),
  })

// hooks/useRCAReport.js  
export const useRCAReport = (reportId) =>
  useQuery({
    queryKey: ['rca-report', reportId],
    queryFn: () => api.get(`/api/rca/reports/${reportId}`),
    enabled: !!reportId,
  })
```

每个 API 模块一个 hook 文件，共 ~10 个 hooks 覆盖所有视图。

---

## §7 实施计划

### Phase 1: 骨架 + Ops Hub (2 天)
1. 重构 `AppV2.jsx` — 3 视图路由
2. `<HealthIssueList>` + `<AlertFeed>` + `<IncidentStats>`
3. MUI → Antd 迁移 (batch 1: pages/)
4. 删除 deprecated/ + 合并重复组件

### Phase 2: Diagnose 视图 (2 天)
5. 安装 ReactFlow: `npm install @xyflow/react`
6. `<TopologyGraph>` + `<PropagationOverlay>`
7. `<RCAViewer>` + `<ChangeTimeline>`
8. `<SimilarCases>` — Knowledge Flywheel 可视化

### Phase 3: 增强 + 清理 (1 天)
9. Agent Console Context Panel
10. `<SafetyApproval>` + `<SOPQuickActions>`
11. MUI → Antd 迁移 (batch 2: components/)
12. Config 页面合并
13. 删除 `@mui/*` 依赖

### 估算

| 维度 | 数值 |
|------|------|
| 新代码 | ~1,500 行 JSX |
| 删除代码 | ~2,000 行 (deprecated + 重复) |
| 净变化 | **-500 行** (更少代码，更多功能) |
| 新组件 | 12 个 |
| 删除文件 | 6-8 个 |
| 总工期 | **5 天** |
| 依赖变化 | Phase 1: +0 / -3 (MUI + emotion); Phase 2: +1 (ReactFlow) |

---

## §8 验收标准

1. **3 个视图全部可用** — Ops Hub / Diagnose / Agent Console
2. **MUI 零引用** — 删除所有 `@mui` 依赖
3. **核心 API 覆盖率 ≥80%** — 核心 API ~55 个，从当前 27% → 目标 80%
4. **深色主题一致** — 全站深色，无白色闪烁
5. **响应时间 <2s** — 所有页面首屏 <2s (React Query 缓存)
6. **零 console error** — 无 React warning / 无 404 API call
7. **代码量 ≤ 8,000 行** (soft target) — 比当前 8,771 行更少
8. **空状态 + Error Boundary** — 无数据时显示空状态，API 失败时 graceful fallback

---

## §9 Tester 验证清单

- [ ] Ops Hub: HealthIssue 列表加载 + 状态筛选
- [ ] Ops Hub: Alert Feed 实时更新
- [ ] Ops Hub: SOP 一键执行 + 审批流
- [ ] Diagnose: 拓扑图渲染 + 节点点击
- [ ] Diagnose: 故障传播叠加层
- [ ] Diagnose: RCA 报告 Markdown 渲染
- [ ] Agent Console: Context Panel 联动
- [ ] Config: Skills 列表 + 状态
- [ ] 深色主题一致性
- [ ] MUI 零残留
- [ ] 所有 API 调用 200 OK

---

*Trade-off*: 不做 SSR (Next.js)、不做 micro-frontend、不做 WebSocket 实时推送 (Phase 2)。
先用 React Query 30s 轮询，功能先 Solid，再考虑优化。
