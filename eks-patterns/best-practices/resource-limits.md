# EKS Pattern: 资源限制最佳实践

## 概述
**类型**: 最佳实践 | **级别**: 核心
**关键词**: resources, limits, requests, QoS, 资源配置

## QoS 类别

| QoS Class | 条件 | 驱逐优先级 |
|-----------|------|-----------|
| Guaranteed | requests = limits (CPU & Memory) | 最低 (最后被驱逐) |
| Burstable | requests < limits | 中等 |
| BestEffort | 无 resources 设置 | 最高 (最先被驱逐) |

## 推荐配置

| 应用类型 | CPU req:lim | Memory req:lim |
|----------|-------------|----------------|
| Web 前端 | 100m:500m | 128Mi:256Mi |
| API 服务 | 250m:1000m | 256Mi:512Mi |
| Java 应用 | 500m:2000m | 1Gi:2Gi |
| 数据库 | 1000m:2000m | 2Gi:4Gi |

## Java 应用特别注意

- `-Xmx` 设为 memory limits 的 **75%**
- 例: limits=2Gi → `-Xmx=1536m`
- 预留空间给 Metaspace、Stack、Native Memory

```yaml
resources:
  requests:
    memory: "1Gi"
    cpu: "500m"
  limits:
    memory: "2Gi"
    cpu: "2000m"
env:
  - name: JAVA_OPTS
    value: "-Xmx1536m -Xms512m"
```

## Namespace 级别限制

### LimitRange (默认值和上下限)
```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
spec:
  limits:
  - default:
      memory: "256Mi"
      cpu: "500m"
    defaultRequest:
      memory: "128Mi"
      cpu: "100m"
    type: Container
```

### ResourceQuota (总量限制)
```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: compute-quota
spec:
  hard:
    requests.cpu: "10"
    requests.memory: "20Gi"
    limits.cpu: "20"
    limits.memory: "40Gi"
```

## 相关 Pattern
- OOM Killed 处理
- HPA 配置指南
- Pod Pending 处理
