# A2UI (Agent-to-UI) Component Schema Design

**Version**: 1.0  
**Author**: Architect  
**Date**: 2026-02-04  
**Status**: Implementing

---

## 1. Overview

A2UI is a Grafana-like dynamic dashboard system where AI Agent can create, modify, and arrange UI components through conversation.

---

## 2. Core Concepts

### 2.1 Dashboard Structure

```
Dashboard
├── id: string
├── title: string
├── layout: GridLayout[]
└── panels: Panel[]
```

### 2.2 Panel Types

| Type | Description | Use Case |
|------|-------------|----------|
| `stat` | Single value with trend | KPI metrics |
| `table` | Data table with sorting/filter | Resource lists |
| `line-chart` | Time series line chart | Metrics over time |
| `bar-chart` | Bar chart | Comparisons |
| `pie-chart` | Pie/donut chart | Distributions |
| `gauge` | Gauge meter | Utilization |
| `alert-list` | Issue/alert list | Observability Center |
| `text` | Markdown text | Documentation |
| `logs` | Log viewer | Log analysis |

---

## 3. Panel Schema

```typescript
interface Panel {
  id: string;
  type: PanelType;
  title: string;
  description?: string;
  
  // Grid position (react-grid-layout)
  gridPos: {
    x: number;      // 0-23 columns
    y: number;      // row position
    w: number;      // width in grid units
    h: number;      // height in grid units
  };
  
  // Data source configuration
  dataSource: {
    type: 'api' | 'static' | 'websocket';
    endpoint?: string;       // API endpoint
    refreshInterval?: number; // ms
    query?: object;          // Query parameters
  };
  
  // Type-specific options
  options: PanelOptions;
}
```

### 3.1 Stat Panel Options

```typescript
interface StatPanelOptions {
  valueField: string;
  unit?: string;
  prefix?: string;
  suffix?: string;
  colorMode: 'value' | 'background';
  thresholds: {
    value: number;
    color: string;
  }[];
}
```

### 3.2 Table Panel Options

```typescript
interface TablePanelOptions {
  columns: {
    field: string;
    title: string;
    width?: number;
    sortable?: boolean;
    filterable?: boolean;
    render?: 'text' | 'tag' | 'status' | 'link' | 'action';
  }[];
  pagination: boolean;
  pageSize?: number;
  actions?: {
    label: string;
    action: 'fix' | 'ignore' | 'detail' | 'delete';
  }[];
}
```

### 3.3 Chart Panel Options

```typescript
interface ChartPanelOptions {
  chartType: 'line' | 'bar' | 'pie' | 'area';
  xField: string;
  yField: string | string[];
  legend?: boolean;
  smooth?: boolean;
  fill?: boolean;
}
```

---

## 4. Dashboard API

### 4.1 Endpoints

```
GET    /api/dashboards              - List all dashboards
GET    /api/dashboards/:id          - Get dashboard config
POST   /api/dashboards              - Create dashboard
PUT    /api/dashboards/:id          - Update dashboard
DELETE /api/dashboards/:id          - Delete dashboard

POST   /api/dashboards/:id/panels   - Add panel
PUT    /api/dashboards/:id/panels/:panelId - Update panel
DELETE /api/dashboards/:id/panels/:panelId - Remove panel
```

### 4.2 A2UI Agent API

```
POST   /api/a2ui/generate           - Generate panel from description
POST   /api/a2ui/modify             - Modify existing panel
POST   /api/a2ui/suggest            - Get AI suggestions
```

---

## 5. A2UI Workflow

```
┌─────────────────────────────────────────────────────────────┐
│  User: "Add a chart showing EC2 CPU usage over 24 hours"    │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  AI Agent Analysis:                                          │
│  - Intent: add_panel                                        │
│  - Panel type: line-chart                                   │
│  - Data: EC2 CPU metrics                                    │
│  - Time range: 24h                                          │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  Generated Panel Config:                                     │
│  {                                                           │
│    "id": "panel-123",                                       │
│    "type": "line-chart",                                    │
│    "title": "EC2 CPU Usage (24h)",                          │
│    "gridPos": { "x": 0, "y": 0, "w": 12, "h": 8 },         │
│    "dataSource": {                                          │
│      "type": "api",                                         │
│      "endpoint": "/api/aws/ec2/metrics",                    │
│      "query": { "metric": "cpu", "period": "24h" }          │
│    },                                                        │
│    "options": {                                             │
│      "chartType": "line",                                   │
│      "xField": "timestamp",                                 │
│      "yField": "value",                                     │
│      "smooth": true                                         │
│    }                                                         │
│  }                                                           │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  Frontend: Renders new panel in dashboard                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. Observability Center Panel

Special panel type for unified issue management:

```typescript
const observabilityCenterPanel: Panel = {
  id: "observability-center",
  type: "alert-list",
  title: "Observability Center",
  gridPos: { x: 0, y: 0, w: 24, h: 12 },
  dataSource: {
    type: "api",
    endpoint: "/api/issues",
    refreshInterval: 30000
  },
  options: {
    columns: [
      { field: "severity", title: "Severity", render: "status" },
      { field: "resource", title: "Resource" },
      { field: "issue", title: "Issue" },
      { field: "detected", title: "Detected", render: "time" },
      { field: "status", title: "Status", render: "tag" }
    ],
    actions: [
      { label: "Auto-Fix", action: "fix" },
      { label: "Ignore", action: "ignore" },
      { label: "Details", action: "detail" }
    ],
    groupBy: "severity",
    sortBy: "detected",
    sortOrder: "desc"
  }
};
```

---

## 7. React Components

```
src/components/a2ui/
├── Dashboard.jsx           - Main dashboard container
├── PanelGrid.jsx          - react-grid-layout wrapper
├── Panel.jsx              - Generic panel wrapper
├── panels/
│   ├── StatPanel.jsx      - Stat card
│   ├── TablePanel.jsx     - Data table
│   ├── ChartPanel.jsx     - Charts (line/bar/pie)
│   ├── GaugePanel.jsx     - Gauge meter
│   ├── AlertListPanel.jsx - Issue list
│   └── TextPanel.jsx      - Markdown text
└── PanelEditor.jsx        - Panel configuration editor
```

---

## 8. Implementation Priority

| Priority | Component | Description |
|----------|-----------|-------------|
| P0 | Dashboard + Grid | Basic layout system |
| P0 | AlertListPanel | Observability Center |
| P1 | StatPanel | KPI cards |
| P1 | TablePanel | Resource lists |
| P2 | ChartPanel | Metrics visualization |
| P2 | A2UI Agent API | AI-driven generation |

---

**Status**: Ready for implementation  
**Next**: @Developer start with P0 components
