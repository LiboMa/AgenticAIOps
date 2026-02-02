# Frontend API 接口设计

**版本**: 1.0  
**作者**: Architect  
**日期**: 2026-02-02  
**状态**: 待评审

---

## 1. 概述

设计 Dashboard 前端与 ACI 的 API 接口，实现真实数据接入。

## 2. API 端点设计

### 2.1 基础信息

```
Base URL: http://localhost:8000/api
Content-Type: application/json
```

### 2.2 端点列表

| 端点 | 方法 | 描述 | ACI 调用 |
|------|------|------|----------|
| `/api/aci/pods` | GET | 获取 Pod 列表 | `kubectl(["get", "pods"])` |
| `/api/aci/events` | GET | 获取 K8s 事件 | `get_events()` |
| `/api/aci/logs` | GET | 获取 Pod 日志 | `get_logs()` |
| `/api/aci/metrics` | GET | 获取指标数据 | `get_metrics()` |
| `/api/aci/diagnose` | POST | 触发诊断 | Multi-Agent Voting |

---

## 3. 详细接口定义

### 3.1 GET /api/aci/pods

获取指定 namespace 的 Pod 列表。

**请求参数:**
```json
{
  "namespace": "default",  // 可选，默认 "default"
  "label_selector": ""     // 可选，标签选择器
}
```

**响应:**
```json
{
  "success": true,
  "data": {
    "pods": [
      {
        "name": "nginx-deployment-abc123",
        "namespace": "default",
        "status": "Running",
        "ready": "1/1",
        "restarts": 0,
        "age": "2d",
        "node": "ip-10-0-1-100",
        "cpu": "50m",
        "memory": "128Mi"
      }
    ],
    "total": 5
  },
  "timestamp": "2026-02-02T14:50:00Z"
}
```

---

### 3.2 GET /api/aci/events

获取 K8s 事件列表。

**请求参数:**
```json
{
  "namespace": "default",    // 可选
  "type": "Warning",         // 可选: Normal, Warning
  "limit": 50,               // 可选，默认 50
  "since_minutes": 30        // 可选，最近 N 分钟
}
```

**响应:**
```json
{
  "success": true,
  "data": {
    "events": [
      {
        "timestamp": "2026-02-02T14:45:00Z",
        "type": "Warning",
        "reason": "OOMKilled",
        "object": "pod/memory-stress",
        "message": "Container killed due to OOM",
        "count": 3
      }
    ],
    "total": 10
  },
  "timestamp": "2026-02-02T14:50:00Z"
}
```

---

### 3.3 GET /api/aci/logs

获取 Pod 日志。

**请求参数:**
```json
{
  "namespace": "default",    // 必填
  "pod": "nginx-abc123",     // 必填
  "container": "",           // 可选，多容器时指定
  "lines": 100,              // 可选，默认 100
  "severity": ""             // 可选: error, warn, info
}
```

**响应:**
```json
{
  "success": true,
  "data": {
    "logs": [
      {
        "timestamp": "2026-02-02T14:45:00Z",
        "level": "error",
        "message": "OutOfMemoryError: Java heap space"
      }
    ],
    "pod": "nginx-abc123",
    "container": "main"
  },
  "timestamp": "2026-02-02T14:50:00Z"
}
```

---

### 3.4 GET /api/aci/metrics

获取指标数据 (来自 Prometheus)。

**请求参数:**
```json
{
  "namespace": "default",    // 必填
  "metric_type": "cpu",      // 必填: cpu, memory, network, restarts
  "time_range": "1h",        // 可选: 5m, 15m, 1h, 6h, 24h
  "pod": ""                  // 可选，不填则返回 namespace 级别
}
```

**响应:**
```json
{
  "success": true,
  "data": {
    "metric_type": "cpu",
    "unit": "millicores",
    "series": [
      {
        "pod": "nginx-abc123",
        "values": [
          {"timestamp": "2026-02-02T14:00:00Z", "value": 50},
          {"timestamp": "2026-02-02T14:05:00Z", "value": 75},
          {"timestamp": "2026-02-02T14:10:00Z", "value": 100}
        ]
      }
    ]
  },
  "timestamp": "2026-02-02T14:50:00Z"
}
```

---

### 3.5 POST /api/aci/diagnose

触发 Multi-Agent 诊断。

**请求:**
```json
{
  "namespace": "stress-test",
  "description": "Pod 频繁重启",
  "context": {
    "pod": "memory-stress",
    "symptom": "OOMKilled"
  }
}
```

**响应:**
```json
{
  "success": true,
  "data": {
    "diagnosis_id": "diag-20260202-001",
    "status": "completed",
    "result": {
      "root_cause": "OOM - 内存溢出",
      "confidence": 0.95,
      "consensus": true,
      "evidence": [
        "Events: 3 次 OOMKilled",
        "Metrics: 内存使用率 100%",
        "Logs: Java heap space error"
      ],
      "recommendation": "增加 memory limit 到 256Mi",
      "agent_votes": {
        "architect": {"answer": "oom", "weight": 0.32},
        "developer": {"answer": "oom", "weight": 0.24},
        "tester": {"answer": "oom", "weight": 0.18}
      }
    },
    "duration_ms": 2500
  },
  "timestamp": "2026-02-02T14:50:00Z"
}
```

---

## 4. 前端组件映射

| 前端组件 | API 端点 | 刷新间隔 |
|----------|----------|----------|
| **EKSStatus.jsx** | `/api/aci/pods` | 10s |
| **Anomalies.jsx** | `/api/aci/events` | 5s |
| **LogViewer** (新增) | `/api/aci/logs` | 实时/手动 |
| **MetricsChart** (新增) | `/api/aci/metrics` | 30s |
| **RCAReports.jsx** | `/api/aci/diagnose` | 手动触发 |

---

## 5. WebSocket 实时推送 (可选)

```
WS Endpoint: ws://localhost:8000/ws/aci

订阅消息:
{
  "action": "subscribe",
  "channels": ["events", "metrics"]
}

推送消息:
{
  "channel": "events",
  "data": { ... }
}
```

---

## 6. 错误处理

所有 API 错误返回统一格式:

```json
{
  "success": false,
  "error": {
    "code": "ACI_TIMEOUT",
    "message": "Failed to connect to Kubernetes API",
    "details": "Connection refused"
  },
  "timestamp": "2026-02-02T14:50:00Z"
}
```

**错误码:**
| Code | 描述 |
|------|------|
| `ACI_TIMEOUT` | ACI 调用超时 |
| `ACI_AUTH_ERROR` | 认证失败 |
| `ACI_NOT_FOUND` | 资源不存在 |
| `ACI_FORBIDDEN` | 操作被拒绝 |
| `INVALID_PARAM` | 参数错误 |

---

## 7. 实施清单

### 后端 (api_server.py)
- [ ] 实现 `/api/aci/pods` 端点
- [ ] 实现 `/api/aci/events` 端点
- [ ] 实现 `/api/aci/logs` 端点
- [ ] 实现 `/api/aci/metrics` 端点
- [ ] 实现 `/api/aci/diagnose` 端点

### 前端 (dashboard/)
- [ ] 更新 EKSStatus.jsx 调用真实 API
- [ ] 更新 Anomalies.jsx 调用真实 API
- [ ] 新增 LogViewer.jsx 组件
- [ ] 新增 MetricsChart.jsx 组件
- [ ] 更新 RCAReports.jsx 集成诊断 API

---

**设计状态**: 📝 待评审  
**下一步**: @Reviewer 评审，通过后 @Developer 实现
