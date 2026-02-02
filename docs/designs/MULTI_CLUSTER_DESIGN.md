# Multi-Cluster / Multi-Region 架构设计

**版本**: 1.0  
**作者**: Architect  
**日期**: 2026-02-02  
**状态**: 设计草案

---

## 1. 背景

当前 AgenticAIOps 支持单一 EKS 集群。生产环境通常有：
- 多个环境 (dev, staging, prod)
- 多个 Region (ap-southeast-1, us-east-1, eu-west-1)
- 多个集群 (业务线隔离)

## 2. 架构方案

### 2.1 方案对比

| 维度 | 方案 A: 集中式 | 方案 B: 分布式 |
|------|---------------|---------------|
| 架构 | 单 Agent + 多 ACI | 多 Agent + 中央协调 |
| 复杂度 | 低 | 高 |
| 延迟 | 跨 Region 有延迟 | 本地低延迟 |
| 成本 | 低 | 高 (多部署) |
| 适用场景 | < 10 集群 | > 10 集群 |
| **推荐** | ✅ MVP 阶段 | 后期扩展 |

### 2.2 推荐方案: 集中式 + 集群注册表

```
┌─────────────────────────────────────────────────────────────┐
│                    Multi-Cluster Architecture                │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│                         User                                 │
│                           │                                  │
│                           ▼                                  │
│  ┌─────────────────────────────────────────────────────────┐│
│  │                   AI Agent Layer                         ││
│  │            (Orchestrator + Workers)                      ││
│  └─────────────────────────────────────────────────────────┘│
│                           │                                  │
│                           ▼                                  │
│  ┌─────────────────────────────────────────────────────────┐│
│  │               Cluster Registry                           ││
│  │                                                          ││
│  │  ┌─────────────────────────────────────────────────────┐││
│  │  │ prod-ap-1   │ prod-us-1   │ staging   │ dev        │││
│  │  │ ap-se-1     │ us-east-1   │ ap-se-1   │ local      │││
│  │  └─────────────────────────────────────────────────────┘││
│  └─────────────────────────────────────────────────────────┘│
│                           │                                  │
│                           ▼                                  │
│  ┌─────────────────────────────────────────────────────────┐│
│  │                  ACI (Unified Interface)                 ││
│  │                                                          ││
│  │  get_logs(cluster="prod-ap-1", namespace="app")         ││
│  │  get_metrics(cluster="prod-us-1", namespace="payment")  ││
│  │  get_events(cluster="staging", type="Warning")          ││
│  └─────────────────────────────────────────────────────────┘│
│        │              │              │              │        │
│        ▼              ▼              ▼              ▼        │
│   ┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐     │
│   │EKS AP  │    │EKS US  │    │EKS STG │    │EKS DEV │     │
│   │Prom AP │    │Prom US │    │Prom STG│    │Prom DEV│     │
│   │CW AP   │    │CW US   │    │CW STG  │    │CW DEV  │     │
│   └────────┘    └────────┘    └────────┘    └────────┘     │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## 3. 核心组件设计

### 3.1 Cluster Registry (集群注册表)

```python
# src/aci/cluster_registry.py

from dataclasses import dataclass
from typing import Dict, List, Optional
from enum import Enum

class ClusterEnvironment(Enum):
    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"

@dataclass
class ClusterConfig:
    """集群配置"""
    name: str                      # prod-ap-1
    region: str                    # ap-southeast-1
    environment: ClusterEnvironment
    kube_context: str              # kubectl context name
    prometheus_url: Optional[str]  # Prometheus endpoint
    cloudwatch_group: Optional[str] # CloudWatch log group
    tags: Dict[str, str] = None    # 自定义标签
    
    @property
    def full_name(self) -> str:
        return f"{self.name}@{self.region}"


class ClusterRegistry:
    """集群注册表 - 单例模式"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._clusters = {}
            cls._instance._default = None
        return cls._instance
    
    def register(self, config: ClusterConfig):
        """注册集群"""
        self._clusters[config.name] = config
        if self._default is None:
            self._default = config.name
    
    def unregister(self, name: str):
        """注销集群"""
        if name in self._clusters:
            del self._clusters[name]
    
    def get(self, name: str) -> ClusterConfig:
        """获取集群配置"""
        if name not in self._clusters:
            raise ValueError(f"Cluster '{name}' not found")
        return self._clusters[name]
    
    def list(self, 
             environment: ClusterEnvironment = None,
             region: str = None) -> List[ClusterConfig]:
        """列出集群 (可过滤)"""
        clusters = list(self._clusters.values())
        if environment:
            clusters = [c for c in clusters if c.environment == environment]
        if region:
            clusters = [c for c in clusters if c.region == region]
        return clusters
    
    @property
    def default(self) -> str:
        return self._default
    
    @default.setter
    def default(self, name: str):
        if name not in self._clusters:
            raise ValueError(f"Cluster '{name}' not registered")
        self._default = name


# 初始化示例
def init_clusters():
    registry = ClusterRegistry()
    
    registry.register(ClusterConfig(
        name="prod-ap",
        region="ap-southeast-1",
        environment=ClusterEnvironment.PRODUCTION,
        kube_context="arn:aws:eks:ap-southeast-1:123:cluster/prod",
        prometheus_url="http://prometheus.prod-ap:9090",
        cloudwatch_group="/eks/prod-ap"
    ))
    
    registry.register(ClusterConfig(
        name="prod-us",
        region="us-east-1",
        environment=ClusterEnvironment.PRODUCTION,
        kube_context="arn:aws:eks:us-east-1:123:cluster/prod",
        prometheus_url="http://prometheus.prod-us:9090",
        cloudwatch_group="/eks/prod-us"
    ))
    
    registry.register(ClusterConfig(
        name="staging",
        region="ap-southeast-1",
        environment=ClusterEnvironment.STAGING,
        kube_context="arn:aws:eks:ap-southeast-1:123:cluster/staging",
        prometheus_url="http://prometheus.staging:9090"
    ))
    
    return registry
```

### 3.2 Multi-Cluster ACI

```python
# src/aci/multi_cluster_aci.py

import asyncio
from typing import List, Dict, Any, Optional
from .cluster_registry import ClusterRegistry, ClusterConfig
from .aci import AgentCloudInterface, ACIResult

class MultiClusterACI:
    """支持多集群的 ACI"""
    
    def __init__(self):
        self.registry = ClusterRegistry()
        self._aci_pool: Dict[str, AgentCloudInterface] = {}
    
    def _get_aci(self, cluster: str) -> AgentCloudInterface:
        """获取或创建 ACI 实例"""
        if cluster not in self._aci_pool:
            config = self.registry.get(cluster)
            self._aci_pool[cluster] = AgentCloudInterface(
                kube_context=config.kube_context,
                prometheus_url=config.prometheus_url
            )
        return self._aci_pool[cluster]
    
    # ========== 单集群操作 ==========
    
    def get_logs(self, 
                 cluster: str = None,
                 namespace: str = "default",
                 **kwargs) -> ACIResult:
        """获取日志"""
        cluster = cluster or self.registry.default
        aci = self._get_aci(cluster)
        result = aci.get_logs(namespace=namespace, **kwargs)
        result.metadata["cluster"] = cluster
        return result
    
    def get_metrics(self,
                    cluster: str = None,
                    namespace: str = "default",
                    **kwargs) -> ACIResult:
        """获取指标"""
        cluster = cluster or self.registry.default
        aci = self._get_aci(cluster)
        result = aci.get_metrics(namespace=namespace, **kwargs)
        result.metadata["cluster"] = cluster
        return result
    
    def get_events(self,
                   cluster: str = None,
                   namespace: str = None,
                   **kwargs) -> ACIResult:
        """获取事件"""
        cluster = cluster or self.registry.default
        aci = self._get_aci(cluster)
        result = aci.get_events(namespace=namespace, **kwargs)
        result.metadata["cluster"] = cluster
        return result
    
    # ========== 跨集群聚合操作 ==========
    
    async def get_all_events(self,
                             clusters: List[str] = None,
                             event_type: str = "Warning") -> Dict[str, ACIResult]:
        """并行获取多集群事件"""
        if clusters is None:
            clusters = [c.name for c in self.registry.list()]
        
        async def fetch_events(cluster: str):
            aci = self._get_aci(cluster)
            return cluster, aci.get_events(type=event_type)
        
        tasks = [fetch_events(c) for c in clusters]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        return {
            cluster: result 
            for cluster, result in results 
            if not isinstance(result, Exception)
        }
    
    def get_cluster_overview(self) -> Dict[str, Any]:
        """获取所有集群概览"""
        overview = {
            "clusters": [],
            "total_pods": 0,
            "total_warnings": 0
        }
        
        for config in self.registry.list():
            try:
                aci = self._get_aci(config.name)
                pods = aci.kubectl(["get", "pods", "-A", "--no-headers"])
                events = aci.get_events(type="Warning")
                
                pod_count = len(pods.data.strip().split('\n')) if pods.data else 0
                warning_count = len(events.data) if events.data else 0
                
                overview["clusters"].append({
                    "name": config.name,
                    "region": config.region,
                    "environment": config.environment.value,
                    "pods": pod_count,
                    "warnings": warning_count,
                    "status": "healthy" if warning_count == 0 else "warning"
                })
                
                overview["total_pods"] += pod_count
                overview["total_warnings"] += warning_count
                
            except Exception as e:
                overview["clusters"].append({
                    "name": config.name,
                    "region": config.region,
                    "status": "unreachable",
                    "error": str(e)
                })
        
        return overview
```

### 3.3 API 端点扩展

```python
# api_server.py 新增端点

@app.get("/api/clusters")
async def list_clusters():
    """列出所有注册的集群"""
    registry = ClusterRegistry()
    return {
        "clusters": [
            {
                "name": c.name,
                "region": c.region,
                "environment": c.environment.value
            }
            for c in registry.list()
        ],
        "default": registry.default
    }

@app.get("/api/clusters/overview")
async def clusters_overview():
    """获取所有集群概览"""
    aci = MultiClusterACI()
    return aci.get_cluster_overview()

@app.post("/api/clusters/{cluster}/switch")
async def switch_cluster(cluster: str):
    """切换默认集群"""
    registry = ClusterRegistry()
    registry.default = cluster
    return {"message": f"Switched to {cluster}", "current": cluster}

# 修改现有端点支持 cluster 参数
@app.get("/api/aci/pods")
async def get_pods(cluster: str = None, namespace: str = "default"):
    """获取 Pod 列表 (支持指定集群)"""
    aci = MultiClusterACI()
    return aci.kubectl(
        cluster=cluster,
        command=["get", "pods", "-n", namespace, "-o", "json"]
    )
```

### 3.4 前端扩展

```jsx
// dashboard/src/components/ClusterSelector.jsx (更新)

import { useState, useEffect } from 'react';
import { Select, MenuItem, Chip, Box } from '@mui/material';

export default function ClusterSelector({ onClusterChange }) {
  const [clusters, setClusters] = useState([]);
  const [current, setCurrent] = useState('');
  
  useEffect(() => {
    fetch('/api/clusters')
      .then(res => res.json())
      .then(data => {
        setClusters(data.clusters);
        setCurrent(data.default);
      });
  }, []);
  
  const handleChange = async (e) => {
    const cluster = e.target.value;
    await fetch(`/api/clusters/${cluster}/switch`, { method: 'POST' });
    setCurrent(cluster);
    onClusterChange(cluster);
  };
  
  const getEnvColor = (env) => {
    switch(env) {
      case 'production': return 'error';
      case 'staging': return 'warning';
      default: return 'default';
    }
  };
  
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
      <Select value={current} onChange={handleChange} size="small">
        {clusters.map(c => (
          <MenuItem key={c.name} value={c.name}>
            {c.name}
            <Chip 
              label={c.region} 
              size="small" 
              sx={{ ml: 1 }}
            />
            <Chip 
              label={c.environment} 
              size="small" 
              color={getEnvColor(c.environment)}
              sx={{ ml: 1 }}
            />
          </MenuItem>
        ))}
      </Select>
    </Box>
  );
}


// 新增: 全局概览组件
// dashboard/src/components/ClustersOverview.jsx

export default function ClustersOverview() {
  const [overview, setOverview] = useState(null);
  
  useEffect(() => {
    fetch('/api/clusters/overview')
      .then(res => res.json())
      .then(setOverview);
  }, []);
  
  if (!overview) return <CircularProgress />;
  
  return (
    <Grid container spacing={2}>
      {overview.clusters.map(cluster => (
        <Grid item xs={12} md={4} key={cluster.name}>
          <Card>
            <CardContent>
              <Typography variant="h6">{cluster.name}</Typography>
              <Typography color="textSecondary">{cluster.region}</Typography>
              <Chip label={cluster.environment} />
              <Box mt={2}>
                <Typography>Pods: {cluster.pods}</Typography>
                <Typography>Warnings: {cluster.warnings}</Typography>
                <Chip 
                  label={cluster.status}
                  color={cluster.status === 'healthy' ? 'success' : 'warning'}
                />
              </Box>
            </CardContent>
          </Card>
        </Grid>
      ))}
    </Grid>
  );
}
```

## 4. 配置管理

### 4.1 配置文件

```yaml
# config/clusters.yaml

clusters:
  - name: prod-ap
    region: ap-southeast-1
    environment: production
    kube_context: arn:aws:eks:ap-southeast-1:123456789:cluster/prod
    prometheus:
      url: http://prometheus.monitoring.svc:9090
      auth: none
    cloudwatch:
      log_group: /eks/prod-ap
      
  - name: prod-us
    region: us-east-1
    environment: production
    kube_context: arn:aws:eks:us-east-1:123456789:cluster/prod
    prometheus:
      url: http://prometheus.monitoring.svc:9090
    cloudwatch:
      log_group: /eks/prod-us
      
  - name: staging
    region: ap-southeast-1
    environment: staging
    kube_context: arn:aws:eks:ap-southeast-1:123456789:cluster/staging

default: prod-ap
```

### 4.2 环境变量

```bash
# .env
CLUSTER_CONFIG_PATH=/app/config/clusters.yaml
DEFAULT_CLUSTER=prod-ap
```

## 5. 实施计划

| 阶段 | 内容 | 预计时间 |
|------|------|----------|
| **Phase 5.1** | ClusterRegistry 实现 | 0.5 天 |
| **Phase 5.2** | MultiClusterACI 实现 | 1 天 |
| **Phase 5.3** | API 端点扩展 | 0.5 天 |
| **Phase 5.4** | 前端集群选择器 | 0.5 天 |
| **Phase 5.5** | 测试 + 文档 | 0.5 天 |

---

## 6. 后续扩展

- **联邦 Prometheus**: Thanos 或 Cortex 实现跨集群指标聚合
- **集中日志**: 使用 AWS OpenSearch 聚合多集群日志
- **Service Mesh**: Istio 多集群服务网格
- **GitOps**: ArgoCD 多集群部署管理

---

**设计状态**: 📝 待评审  
**适用场景**: < 10 个集群的中小规模多集群环境
