# 企业级前端设计规范

**版本**: 1.0  
**作者**: Architect  
**日期**: 2026-02-03  
**状态**: 待评审

---

## 1. 设计目标

- **企业级**: 专业、可靠、大气
- **高性能**: 首屏 <2s, Bundle <100KB gzip
- **易用性**: 操作直观，信息层次清晰
- **可扩展**: 组件化，易于维护

---

## 2. 技术栈选型

### 2.1 框架对比

| 框架 | 优点 | 缺点 | 评分 |
|------|------|------|------|
| **Ant Design Pro** | 成熟稳定、文档全、模板丰富 | 相对较重 | 9/10 |
| Arco Design | 字节出品、现代感 | 社区较小 | 7/10 |
| Tremor | 专为 Dashboard | 组件较少 | 8/10 |
| MUI Pro | 当前已用 | 缺乏企业级模板 | 6/10 |

### 2.2 最终选型

```yaml
核心框架:
  UI库: Ant Design 5.x + Ant Design Pro Components
  图表: Apache ECharts 5.x
  状态: Zustand (轻量级)
  请求: TanStack Query (React Query)
  路由: React Router 6

构建工具:
  Bundler: Vite (保持)
  CSS: Tailwind CSS + Ant Design Token

质量保障:
  类型: TypeScript
  Lint: ESLint + Prettier
  测试: Vitest + Playwright
```

---

## 3. 视觉规范

### 3.1 配色方案

```css
/* 主色调 - 企业蓝 */
--color-primary: #1890ff;        /* 主色 */
--color-primary-hover: #40a9ff;  /* 悬停 */
--color-primary-active: #096dd9; /* 点击 */

/* 背景色 - 深色主题 */
--color-bg-layout: #0d1117;      /* 页面背景 */
--color-bg-container: #161b22;   /* 容器背景 */
--color-bg-elevated: #21262d;    /* 悬浮背景 */

/* 状态色 */
--color-success: #52c41a;        /* 成功/健康 */
--color-warning: #faad14;        /* 警告/中等 */
--color-error: #ff4d4f;          /* 错误/严重 */
--color-info: #1890ff;           /* 信息 */

/* 文字色 */
--color-text-primary: #e6edf3;   /* 主要文字 */
--color-text-secondary: #8b949e; /* 次要文字 */
--color-text-tertiary: #6e7681;  /* 辅助文字 */

/* 边框 */
--color-border: #30363d;         /* 边框色 */
```

### 3.2 字体规范

```css
/* 字体族 */
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 
             'Helvetica Neue', Arial, 'Noto Sans', sans-serif;

/* 字号层级 */
--font-size-xs: 12px;    /* 辅助信息 */
--font-size-sm: 14px;    /* 正文 */
--font-size-base: 16px;  /* 标题3 */
--font-size-lg: 20px;    /* 标题2 */
--font-size-xl: 24px;    /* 标题1 */
--font-size-2xl: 32px;   /* 大标题 */
--font-size-3xl: 48px;   /* 统计数字 */

/* 字重 */
--font-weight-normal: 400;
--font-weight-medium: 500;
--font-weight-bold: 600;
```

### 3.3 间距系统

```css
/* 基础单位 8px */
--spacing-xs: 4px;
--spacing-sm: 8px;
--spacing-md: 16px;
--spacing-lg: 24px;
--spacing-xl: 32px;
--spacing-2xl: 48px;
```

### 3.4 圆角

```css
--radius-sm: 4px;   /* 小组件 */
--radius-md: 8px;   /* 卡片 */
--radius-lg: 12px;  /* 大卡片 */
--radius-xl: 16px;  /* 模态框 */
```

---

## 4. 布局规范

### 4.1 整体布局

```
┌─────────────────────────────────────────────────────────────────┐
│  Header (56px)                              [Search] [User] [⚙] │
├──────────┬──────────────────────────────────────────────────────┤
│          │                                                       │
│  Sidebar │  Main Content Area                                   │
│  (240px) │                                                       │
│          │  ┌─────────────────────────────────────────────────┐ │
│  📊 概览  │  │  Statistic Cards (4 列)                        │ │
│  🔴 Issues│  │  ┌────┐ ┌────┐ ┌────┐ ┌────┐                  │ │
│  🔍 诊断  │  │  │ 12 │ │  3 │ │  5 │ │99% │                  │ │
│  📈 指标  │  │  └────┘ └────┘ └────┘ └────┘                  │ │
│  🔧 修复  │  └─────────────────────────────────────────────────┘ │
│  ⚙️ 设置  │                                                       │
│          │  ┌─────────────────────┐ ┌─────────────────────────┐ │
│          │  │  Chart Panel       │ │  Issue List            │ │
│          │  │  (ECharts)         │ │  (ProTable)            │ │
│          │  └─────────────────────┘ └─────────────────────────┘ │
│          │                                                       │
├──────────┴──────────────────────────────────────────────────────┤
│  Footer  (可选)                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 响应式断点

```css
/* 断点 */
--breakpoint-xs: 480px;   /* 手机 */
--breakpoint-sm: 576px;   /* 小平板 */
--breakpoint-md: 768px;   /* 平板 */
--breakpoint-lg: 992px;   /* 小桌面 */
--breakpoint-xl: 1200px;  /* 桌面 */
--breakpoint-2xl: 1600px; /* 大屏 */
```

---

## 5. 组件规范

### 5.1 统计卡片 (Statistic Card)

```tsx
// 设计规范
interface StatisticCard {
  title: string;           // 标题 (12px, secondary)
  value: number | string;  // 数值 (32px, bold)
  prefix?: ReactNode;      // 前缀图标
  suffix?: string;         // 后缀单位
  trend?: 'up' | 'down';   // 趋势
  trendValue?: string;     // 趋势数值 (如 +12%)
  status?: 'success' | 'warning' | 'error'; // 状态色
}

// 尺寸
Width: 240px (可响应式缩放)
Height: 120px
Padding: 24px
```

### 5.2 Issue 卡片

```tsx
interface IssueCard {
  id: string;
  title: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  status: 'open' | 'in_progress' | 'resolved';
  namespace: string;
  createdAt: Date;
  assignee?: string;
}

// 状态徽标颜色
critical: #ff4d4f (红)
high: #fa8c16 (橙)
medium: #faad14 (黄)
low: #52c41a (绿)
```

### 5.3 数据表格 (Pro Table)

```tsx
// 功能要求
- 虚拟滚动 (>1000 行)
- 列排序
- 列筛选
- 行选择
- 分页
- 导出 (CSV/Excel)
- 列配置持久化

// 行高
Default: 54px
Compact: 40px
```

### 5.4 图表规范

```tsx
// ECharts 主题配置
{
  backgroundColor: 'transparent',
  textStyle: { color: '#e6edf3' },
  axisLine: { lineStyle: { color: '#30363d' } },
  splitLine: { lineStyle: { color: '#21262d' } },
  series: {
    lineStyle: { width: 2 },
    areaStyle: { opacity: 0.1 }
  }
}

// 图表类型使用场景
- 时间序列: 折线图 (Line)
- 占比分布: 饼图/环图 (Pie/Donut)
- 对比数据: 柱状图 (Bar)
- 状态追踪: 热力图 (Heatmap)
```

---

## 6. 交互规范

### 6.1 加载状态

```
1. 骨架屏 (Skeleton)
   - 首次加载使用
   - 保持布局稳定

2. Spin 加载
   - 数据刷新时使用
   - 显示加载提示文字

3. 进度条 (NProgress)
   - 页面跳转时使用
   - 顶部细进度条
```

### 6.2 操作反馈

```
1. 成功操作
   - 绿色 Toast 提示
   - 2s 后自动消失

2. 危险操作
   - 二次确认弹窗
   - 红色警告文字
   - 需手动输入确认 (如删除)

3. 异常处理
   - 错误边界兜底
   - 友好错误页面
   - 重试按钮
```

### 6.3 动画

```css
/* 过渡动画 */
--transition-fast: 150ms ease;
--transition-normal: 300ms ease;
--transition-slow: 500ms ease;

/* 使用场景 */
- 按钮悬停: fast
- 面板展开: normal
- 页面切换: slow
```

---

## 7. 性能要求

```yaml
指标:
  LCP (Largest Contentful Paint): < 2.5s
  FID (First Input Delay): < 100ms
  CLS (Cumulative Layout Shift): < 0.1
  Bundle Size: < 100KB gzip (主包)

优化策略:
  - 代码分割 (React.lazy)
  - 图片懒加载
  - 虚拟列表
  - 请求缓存 (TanStack Query)
  - 组件按需加载
```

---

## 8. 页面清单

| 页面 | 路由 | 功能 |
|------|------|------|
| Dashboard | `/` | 概览统计 + 快速入口 |
| Issues | `/issues` | Issue 列表 + CRUD |
| Issue Detail | `/issues/:id` | Issue 详情 + 修复 |
| Diagnosis | `/diagnosis` | RCA 诊断 + 结果 |
| Metrics | `/metrics` | 实时指标 + 图表 |
| Health | `/health` | 健康检查状态 |
| Runbooks | `/runbooks` | Runbook 管理 |
| Settings | `/settings` | 系统设置 |

---

## 9. 实施计划

| 阶段 | 内容 | 预计时间 |
|------|------|----------|
| **Phase 1** | 迁移到 Ant Design Pro 框架 | 1 天 |
| **Phase 2** | 实现 Dashboard 概览页 | 1 天 |
| **Phase 3** | 重构 Issue Center | 0.5 天 |
| **Phase 4** | 图表组件 (ECharts) | 0.5 天 |
| **Phase 5** | 性能优化 + 测试 | 1 天 |

**总计: 4 天**

---

**设计状态**: 📝 待评审  
**下一步**: @Reviewer 评审，通过后 @Developer 开始实现
