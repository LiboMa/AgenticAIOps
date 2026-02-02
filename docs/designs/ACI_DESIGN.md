# Agent-Cloud Interface (ACI) 设计文档

**版本**: 1.1  
**作者**: Architect  
**日期**: 2026-02-02  
**参考**: AIOpsLab Framework (arXiv:2501.06706)

---

## 1. 概述

### 1.1 背景

Agent-Cloud Interface (ACI) 是 AIOpsLab 提出的核心概念，定义了 AI Agent 与云环境交互的标准接口。本设计将 ACI 引入 AgenticAIOps 项目，**基于已集成的 AWS EKS MCP Server** 实现，确保可用性。

### 1.2 目标

- ✅ 基于 AWS EKS MCP Server 实现（已集成 16 个工具）
- ✅ 提供统一的 ACI 封装层
- ✅ 与现有 Strands Agent 无缝集成
- ✅ 最终可用，不是纯设计

### 1.3 现有资源

```
已集成 AWS EKS MCP Server:
├── 集群: testing-cluster
├── 区域: ap-southeast-1
├── 工具数: 16 个
└── 文件: mcp_agent.py
```

---

## 2. AWS EKS MCP 工具清单

### 2.1 已集成的 16 个 MCP 工具

| # | 工具名 | 类型 | 功能描述 |
|---|--------|------|----------|
| 1 | `get_cloudwatch_logs` | Telemetry | 从 CloudWatch 获取日志 |
| 2 | `get_cloudwatch_metrics` | Telemetry | 从 CloudWatch 获取指标 |
| 3 | `get_pod_logs` | Telemetry | 获取 Pod 日志 |
| 4 | `get_k8s_events` | Telemetry | 获取 K8s 事件 |
| 5 | `list_k8s_resources` | Context | 列出 K8s 资源 |
| 6 | `list_api_versions` | Context | 列出 K8s API 版本 |
| 7 | `manage_k8s_resource` | Operation | 管理单个 K8s 资源 |
| 8 | `apply_yaml` | Operation | 应用 K8s YAML 文件 |
| 9 | `generate_app_manifest` | Operation | 生成 K8s manifest |
| 10 | `manage_eks_stacks` | Operation | 管理 EKS CloudFormation 栈 |
| 11 | `add_inline_policy` | Operation | 添加 IAM 内联策略 |
| 12 | `get_policies_for_role` | Context | 获取 IAM 角色策略 |
| 13 | `get_eks_vpc_config` | Context | 获取 EKS VPC 配置 |
| 14 | `get_eks_insights` | Context | 获取 EKS 洞察信息 |
| 15 | `get_eks_metrics_guidance` | Context | 获取指标使用指南 |
| 16 | `search_eks_troubleshoot_guide` | Context | 搜索 EKS 故障排除指南 |

### 2.2 工具分类映射到 ACI

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ACI Layer (封装层)                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Telemetry API                    Operation API                      │
│  ┌─────────────────────────┐     ┌─────────────────────────┐       │
│  │ get_logs()              │     │ exec_kubectl()          │       │
│  │  ├─ get_pod_logs        │     │  ├─ manage_k8s_resource │       │
│  │  └─ get_cloudwatch_logs │     │  └─ list_k8s_resources  │       │
│  │                         │     │                         │       │
│  │ get_metrics()           │     │ apply_manifest()        │       │
│  │  └─ get_cloudwatch_     │     │  ├─ apply_yaml          │       │
│  │     metrics             │     │  └─ generate_app_       │       │
│  │                         │     │     manifest            │       │
│  │ get_events()            │     │                         │       │
│  │  └─ get_k8s_events      │     │ manage_eks()            │       │
│  └─────────────────────────┘     │  └─ manage_eks_stacks   │       │
│                                  └─────────────────────────┘       │
│                                                                      │
│  Context API                                                         │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ get_topology()         get_insights()        troubleshoot() │   │
│  │  └─ list_k8s_resources  └─ get_eks_insights   └─ search_eks │   │
│  │                                                 _troubleshoot│   │
│  │ get_vpc_config()       get_iam_policies()       _guide      │   │
│  │  └─ get_eks_vpc_config  └─ get_policies_for_role            │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
              ┌────────────────────────────────┐
              │     AWS EKS MCP Server         │
              │     (awslabs.eks-mcp-server)   │
              │         16 Tools               │
              └────────────────────────────────┘
```

---

## 3. ACI 封装层设计

### 3.1 架构

```python
# src/aci/__init__.py

from .interface import AgentCloudInterface

__all__ = ["AgentCloudInterface"]
```

### 3.2 主接口类

```python
# src/aci/interface.py

"""
Agent-Cloud Interface (ACI) - 基于 AWS EKS MCP Server

封装 16 个 MCP 工具，提供统一的 ACI 接口。
"""

from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum
import os

from mcp import StdioServerParameters, stdio_client
from strands.tools.mcp import MCPClient


class ACIResultStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    PARTIAL = "partial"


@dataclass
class ACIResult:
    """ACI 操作结果"""
    status: ACIResultStatus
    data: Any
    metadata: Dict[str, Any]
    error: Optional[str] = None


class AgentCloudInterface:
    """
    Agent-Cloud Interface - 统一的 Agent-Cloud 交互接口
    
    基于 AWS EKS MCP Server 实现，提供:
    - Telemetry API: 日志、指标、事件获取
    - Operation API: kubectl 操作、manifest 应用
    - Context API: 拓扑、配置、故障排除
    """
    
    def __init__(
        self,
        cluster_name: str = "testing-cluster",
        region: str = "ap-southeast-1"
    ):
        self.cluster_name = cluster_name
        self.region = region
        self._mcp_client = None
        self._tools = {}
    
    def _get_mcp_client(self) -> MCPClient:
        """获取或创建 MCP 客户端"""
        if self._mcp_client is None:
            self._mcp_client = MCPClient(
                lambda: stdio_client(
                    StdioServerParameters(
                        command="uvx",
                        args=["awslabs.eks-mcp-server@latest"],
                        env={
                            "AWS_REGION": self.region,
                            "EKS_CLUSTER_NAME": self.cluster_name,
                            **os.environ
                        }
                    )
                )
            )
        return self._mcp_client
    
    # ==================== Telemetry API ====================
    
    def get_logs(
        self,
        source: str = "pod",  # "pod" or "cloudwatch"
        namespace: str = "default",
        pod_name: Optional[str] = None,
        log_group: Optional[str] = None,
        duration_minutes: int = 5,
        filter_pattern: Optional[str] = None
    ) -> ACIResult:
        """
        获取日志数据
        
        Args:
            source: 日志来源 ("pod" 或 "cloudwatch")
            namespace: K8s 命名空间 (pod 日志)
            pod_name: Pod 名称 (pod 日志)
            log_group: CloudWatch 日志组 (cloudwatch 日志)
            duration_minutes: 时间范围
            filter_pattern: 过滤模式
        
        Returns:
            ACIResult 包含日志数据
        
        底层工具:
            - get_pod_logs
            - get_cloudwatch_logs
        """
        try:
            with self._get_mcp_client() as mcp:
                if source == "pod":
                    # 使用 get_pod_logs MCP 工具
                    result = mcp.call_tool(
                        "get_pod_logs",
                        namespace=namespace,
                        pod_name=pod_name,
                        tail_lines=100
                    )
                else:
                    # 使用 get_cloudwatch_logs MCP 工具
                    result = mcp.call_tool(
                        "get_cloudwatch_logs",
                        log_group=log_group,
                        duration_minutes=duration_minutes,
                        filter_pattern=filter_pattern
                    )
                
                return ACIResult(
                    status=ACIResultStatus.SUCCESS,
                    data=result,
                    metadata={"source": source, "duration": duration_minutes}
                )
        except Exception as e:
            return ACIResult(
                status=ACIResultStatus.ERROR,
                data=None,
                metadata={},
                error=str(e)
            )
    
    def get_metrics(
        self,
        resource_type: str,  # "pod", "node", "service"
        namespace: str = "default",
        metric_names: Optional[List[str]] = None,
        duration_minutes: int = 5
    ) -> ACIResult:
        """
        获取 CloudWatch 指标
        
        底层工具: get_cloudwatch_metrics
        """
        try:
            with self._get_mcp_client() as mcp:
                result = mcp.call_tool(
                    "get_cloudwatch_metrics",
                    resource_type=resource_type,
                    namespace=namespace,
                    metric_names=metric_names or ["CPUUtilization", "MemoryUtilization"],
                    duration_minutes=duration_minutes
                )
                return ACIResult(
                    status=ACIResultStatus.SUCCESS,
                    data=result,
                    metadata={"resource_type": resource_type}
                )
        except Exception as e:
            return ACIResult(
                status=ACIResultStatus.ERROR,
                data=None,
                metadata={},
                error=str(e)
            )
    
    def get_events(
        self,
        namespace: str = "default",
        resource_name: Optional[str] = None,
        resource_kind: Optional[str] = None
    ) -> ACIResult:
        """
        获取 K8s 事件
        
        底层工具: get_k8s_events
        """
        try:
            with self._get_mcp_client() as mcp:
                result = mcp.call_tool(
                    "get_k8s_events",
                    namespace=namespace,
                    resource_name=resource_name,
                    resource_kind=resource_kind
                )
                return ACIResult(
                    status=ACIResultStatus.SUCCESS,
                    data=result,
                    metadata={"namespace": namespace}
                )
        except Exception as e:
            return ACIResult(
                status=ACIResultStatus.ERROR,
                data=None,
                metadata={},
                error=str(e)
            )
    
    # ==================== Operation API ====================
    
    def kubectl(
        self,
        operation: str,  # "get", "describe", "delete", "patch"
        resource_kind: str,
        resource_name: Optional[str] = None,
        namespace: str = "default",
        **kwargs
    ) -> ACIResult:
        """
        执行 kubectl 操作
        
        底层工具:
            - manage_k8s_resource
            - list_k8s_resources
        """
        try:
            with self._get_mcp_client() as mcp:
                if operation in ["get", "list"]:
                    result = mcp.call_tool(
                        "list_k8s_resources",
                        kind=resource_kind,
                        namespace=namespace
                    )
                else:
                    result = mcp.call_tool(
                        "manage_k8s_resource",
                        operation=operation,
                        kind=resource_kind,
                        name=resource_name,
                        namespace=namespace,
                        **kwargs
                    )
                
                return ACIResult(
                    status=ACIResultStatus.SUCCESS,
                    data=result,
                    metadata={"operation": operation, "kind": resource_kind}
                )
        except Exception as e:
            return ACIResult(
                status=ACIResultStatus.ERROR,
                data=None,
                metadata={},
                error=str(e)
            )
    
    def apply_manifest(
        self,
        yaml_path: Optional[str] = None,
        generate: bool = False,
        app_name: Optional[str] = None,
        image: Optional[str] = None,
        replicas: int = 1
    ) -> ACIResult:
        """
        应用 K8s manifest
        
        底层工具:
            - apply_yaml
            - generate_app_manifest
        """
        try:
            with self._get_mcp_client() as mcp:
                if generate:
                    # 生成并应用
                    result = mcp.call_tool(
                        "generate_app_manifest",
                        app_name=app_name,
                        image=image,
                        replicas=replicas
                    )
                else:
                    # 应用现有文件
                    result = mcp.call_tool(
                        "apply_yaml",
                        yaml_path=yaml_path
                    )
                
                return ACIResult(
                    status=ACIResultStatus.SUCCESS,
                    data=result,
                    metadata={"generated": generate}
                )
        except Exception as e:
            return ACIResult(
                status=ACIResultStatus.ERROR,
                data=None,
                metadata={},
                error=str(e)
            )
    
    def manage_eks_stack(
        self,
        operation: str,  # "list", "describe", "create", "update", "delete"
        stack_name: Optional[str] = None,
        **kwargs
    ) -> ACIResult:
        """
        管理 EKS CloudFormation 栈
        
        底层工具: manage_eks_stacks
        """
        try:
            with self._get_mcp_client() as mcp:
                result = mcp.call_tool(
                    "manage_eks_stacks",
                    operation=operation,
                    stack_name=stack_name,
                    **kwargs
                )
                return ACIResult(
                    status=ACIResultStatus.SUCCESS,
                    data=result,
                    metadata={"operation": operation}
                )
        except Exception as e:
            return ACIResult(
                status=ACIResultStatus.ERROR,
                data=None,
                metadata={},
                error=str(e)
            )
    
    # ==================== Context API ====================
    
    def get_topology(
        self,
        namespace: str = "default"
    ) -> ACIResult:
        """
        获取集群拓扑信息
        
        底层工具: list_k8s_resources (多次调用)
        """
        try:
            with self._get_mcp_client() as mcp:
                # 获取多种资源
                pods = mcp.call_tool("list_k8s_resources", kind="pods", namespace=namespace)
                services = mcp.call_tool("list_k8s_resources", kind="services", namespace=namespace)
                deployments = mcp.call_tool("list_k8s_resources", kind="deployments", namespace=namespace)
                
                return ACIResult(
                    status=ACIResultStatus.SUCCESS,
                    data={
                        "pods": pods,
                        "services": services,
                        "deployments": deployments
                    },
                    metadata={"namespace": namespace}
                )
        except Exception as e:
            return ACIResult(
                status=ACIResultStatus.ERROR,
                data=None,
                metadata={},
                error=str(e)
            )
    
    def get_eks_insights(self) -> ACIResult:
        """
        获取 EKS 集群洞察
        
        底层工具: get_eks_insights
        """
        try:
            with self._get_mcp_client() as mcp:
                result = mcp.call_tool("get_eks_insights")
                return ACIResult(
                    status=ACIResultStatus.SUCCESS,
                    data=result,
                    metadata={"cluster": self.cluster_name}
                )
        except Exception as e:
            return ACIResult(
                status=ACIResultStatus.ERROR,
                data=None,
                metadata={},
                error=str(e)
            )
    
    def get_vpc_config(self) -> ACIResult:
        """
        获取 VPC 配置
        
        底层工具: get_eks_vpc_config
        """
        try:
            with self._get_mcp_client() as mcp:
                result = mcp.call_tool("get_eks_vpc_config")
                return ACIResult(
                    status=ACIResultStatus.SUCCESS,
                    data=result,
                    metadata={"cluster": self.cluster_name}
                )
        except Exception as e:
            return ACIResult(
                status=ACIResultStatus.ERROR,
                data=None,
                metadata={},
                error=str(e)
            )
    
    def troubleshoot(
        self,
        query: str
    ) -> ACIResult:
        """
        搜索故障排除指南
        
        底层工具: search_eks_troubleshoot_guide
        """
        try:
            with self._get_mcp_client() as mcp:
                result = mcp.call_tool(
                    "search_eks_troubleshoot_guide",
                    query=query
                )
                return ACIResult(
                    status=ACIResultStatus.SUCCESS,
                    data=result,
                    metadata={"query": query}
                )
        except Exception as e:
            return ACIResult(
                status=ACIResultStatus.ERROR,
                data=None,
                metadata={},
                error=str(e)
            )
    
    # ==================== IAM API ====================
    
    def get_iam_policies(
        self,
        role_name: str
    ) -> ACIResult:
        """
        获取 IAM 角色策略
        
        底层工具: get_policies_for_role
        """
        try:
            with self._get_mcp_client() as mcp:
                result = mcp.call_tool(
                    "get_policies_for_role",
                    role_name=role_name
                )
                return ACIResult(
                    status=ACIResultStatus.SUCCESS,
                    data=result,
                    metadata={"role": role_name}
                )
        except Exception as e:
            return ACIResult(
                status=ACIResultStatus.ERROR,
                data=None,
                metadata={},
                error=str(e)
            )
    
    def add_iam_policy(
        self,
        role_name: str,
        policy_name: str,
        policy_document: Dict[str, Any]
    ) -> ACIResult:
        """
        添加 IAM 内联策略
        
        底层工具: add_inline_policy
        """
        try:
            with self._get_mcp_client() as mcp:
                result = mcp.call_tool(
                    "add_inline_policy",
                    role_name=role_name,
                    policy_name=policy_name,
                    policy_document=policy_document
                )
                return ACIResult(
                    status=ACIResultStatus.SUCCESS,
                    data=result,
                    metadata={"role": role_name, "policy": policy_name}
                )
        except Exception as e:
            return ACIResult(
                status=ACIResultStatus.ERROR,
                data=None,
                metadata={},
                error=str(e)
            )
```

---

## 4. 与 Strands Agent 集成

### 4.1 注册 ACI 工具

```python
# 使用方式 1: 直接使用 MCP 工具 (推荐)
from strands import Agent
from strands.tools.mcp import MCPClient
from mcp import StdioServerParameters, stdio_client

eks_mcp = MCPClient(
    lambda: stdio_client(
        StdioServerParameters(
            command="uvx",
            args=["awslabs.eks-mcp-server@latest"],
            env={
                "AWS_REGION": "ap-southeast-1",
                "EKS_CLUSTER_NAME": "testing-cluster",
            }
        )
    )
)

with eks_mcp:
    tools = eks_mcp.list_tools_sync()
    agent = Agent(tools=tools)
    response = agent("检查 default namespace 的 pod 状态")
```

```python
# 使用方式 2: 通过 ACI 封装层 (可选)
from src.aci import AgentCloudInterface

aci = AgentCloudInterface(
    cluster_name="testing-cluster",
    region="ap-southeast-1"
)

# 获取日志
logs = aci.get_logs(source="pod", namespace="default", pod_name="nginx")

# 获取拓扑
topology = aci.get_topology(namespace="default")

# 执行 kubectl
result = aci.kubectl(operation="get", resource_kind="pods", namespace="default")
```

---

## 5. 实现计划

### 5.1 阶段划分

| 阶段 | 内容 | 预计时间 | 状态 |
|------|------|----------|------|
| **Phase 1** | ACI 封装类实现 | 0.5 天 | ⏳ |
| **Phase 2** | 单元测试 | 0.5 天 | ⏳ |
| **Phase 3** | 集成测试 (与现有系统) | 0.5 天 | ⏳ |
| **Phase 4** | 文档和示例 | 0.5 天 | ⏳ |

### 5.2 文件清单

```
新增文件:
├── src/aci/__init__.py           # 模块入口
├── src/aci/interface.py          # ACI 主类
├── tests/test_aci.py             # 单元测试
└── docs/designs/ACI_DESIGN.md    # 设计文档 (本文件)

修改文件:
├── src/__init__.py               # 添加 ACI 导出
└── mcp_agent.py                  # 可选: 添加 ACI 集成示例
```

---

## 6. 安全考虑

### 6.1 MCP Server 安全模式

```
AWS EKS MCP Server 默认运行在:
- read-only mode (只读模式)
- restricted sensitive data access mode (限制敏感数据访问)

危险操作需要额外配置启用。
```

### 6.2 审计日志

所有 ACI 操作应记录审计日志：

```python
@dataclass
class ACIAuditEntry:
    timestamp: datetime
    agent_id: str
    operation: str
    mcp_tool: str
    parameters: Dict[str, Any]
    result_status: str
    duration_ms: int
```

---

## 7. 评审检查点

- [ ] ACI 封装是否正确调用 MCP 工具
- [ ] 错误处理是否完备
- [ ] 与现有 mcp_agent.py 是否兼容
- [ ] 是否符合 AIOpsLab 的 ACI 规范
- [ ] 测试覆盖率是否足够

---

**设计状态**: 📝 待评审  
**下一步**: 提交给 @Reviewer 评审，通过后交给 @Developer 实现

---

## 附录: MCP 工具完整列表

| 工具 | 描述 |
|------|------|
| `get_cloudwatch_logs` | 从 CloudWatch 获取日志 |
| `get_cloudwatch_metrics` | 从 CloudWatch 获取指标 |
| `get_pod_logs` | 获取 Pod 日志 |
| `get_k8s_events` | 获取 K8s 事件 |
| `list_k8s_resources` | 列出 K8s 资源 |
| `list_api_versions` | 列出 API 版本 |
| `manage_k8s_resource` | 管理 K8s 资源 |
| `apply_yaml` | 应用 YAML 文件 |
| `generate_app_manifest` | 生成应用 manifest |
| `manage_eks_stacks` | 管理 CloudFormation 栈 |
| `add_inline_policy` | 添加 IAM 内联策略 |
| `get_policies_for_role` | 获取角色策略 |
| `get_eks_vpc_config` | 获取 VPC 配置 |
| `get_eks_insights` | 获取 EKS 洞察 |
| `get_eks_metrics_guidance` | 获取指标指南 |
| `search_eks_troubleshoot_guide` | 搜索故障排除指南 |
