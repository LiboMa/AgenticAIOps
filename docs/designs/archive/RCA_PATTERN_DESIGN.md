# Root Cause Pattern 规则库设计

**版本**: 1.0  
**作者**: Architect  
**日期**: 2026-02-02  
**状态**: Phase 5.2 设计

---

## 1. 概述

设计一个基于规则的根因识别引擎，快速匹配已知故障模式，自动分级并推荐修复方案。

## 2. 架构

```
┌─────────────────────────────────────────────────────────────┐
│              Root Cause Pattern Engine                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  输入: Telemetry Data (Events, Metrics, Logs)               │
│                           │                                  │
│                           ▼                                  │
│  ┌─────────────────────────────────────────────────────────┐│
│  │              Symptom Extractor                           ││
│  │  events → ["OOMKilled", "CrashLoopBackOff"]             ││
│  │  metrics → ["memory > 90%", "cpu_throttled"]            ││
│  │  logs → ["OutOfMemoryError", "connection refused"]      ││
│  └─────────────────────────────────────────────────────────┘│
│                           │                                  │
│                           ▼                                  │
│  ┌─────────────────────────────────────────────────────────┐│
│  │              Pattern Matcher                             ││
│  │                                                          ││
│  │  for pattern in patterns:                                ││
│  │      if pattern.matches(symptoms):                       ││
│  │          return RCAResult(pattern)                       ││
│  └─────────────────────────────────────────────────────────┘│
│                           │                                  │
│                           ▼                                  │
│  ┌─────────────────────────────────────────────────────────┐│
│  │              RCA Result                                  ││
│  │  - root_cause: str                                       ││
│  │  - severity: low | medium | high                         ││
│  │  - confidence: float                                     ││
│  │  - remediation: Action                                   ││
│  │  - evidence: List[str]                                   ││
│  └─────────────────────────────────────────────────────────┘│
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Pattern 配置格式

### 3.1 YAML Schema

```yaml
# config/rca_patterns.yaml
version: "1.0"
patterns:
  - id: "oom-001"
    name: "OOM Kill - Memory Limit"
    description: "Pod 因内存超限被 OOM Killer 终止"
    
    # 匹配条件 (AND 逻辑)
    symptoms:
      events:
        - type: "Warning"
          reason: "OOMKilled"
      metrics:
        - name: "container_memory_usage_bytes"
          condition: "> 90%"
      logs:
        - pattern: "OutOfMemoryError|Cannot allocate memory"
          required: false  # 可选条件
    
    # 诊断结果
    root_cause: "内存限制过低或应用内存泄漏"
    severity: "medium"
    confidence: 0.9
    
    # 修复方案
    remediation:
      action: "increase_memory_limit"
      auto_execute: true
      params:
        increase_ratio: 1.5  # 增加 50%
        max_limit: "2Gi"
      rollback:
        action: "restore_memory_limit"
        
    # 相关文档
    references:
      - "https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/"

  - id: "crash-001"
    name: "CrashLoopBackOff - Application Error"
    description: "应用启动失败导致反复重启"
    
    symptoms:
      events:
        - reason: "CrashLoopBackOff"
        - reason: "BackOff"
      metrics:
        - name: "kube_pod_container_status_restarts_total"
          condition: "> 5"
    
    root_cause: "应用启动失败或配置错误"
    severity: "medium"
    confidence: 0.85
    
    remediation:
      action: "rollout_restart"
      auto_execute: true
      conditions:
        - "restarts < 10"  # 超过 10 次不自动修复
      fallback:
        action: "rollback_deployment"
        
  - id: "image-001"
    name: "ImagePullBackOff"
    description: "镜像拉取失败"
    
    symptoms:
      events:
        - reason: "ImagePullBackOff"
        - reason: "ErrImagePull"
    
    root_cause: "镜像不存在或仓库认证失败"
    severity: "high"  # 需要人工确认
    confidence: 0.95
    
    remediation:
      action: "manual_review"
      auto_execute: false
      suggestion: "检查镜像名称和仓库认证"
      
  - id: "cpu-001"
    name: "CPU Throttling"
    description: "CPU 被限流导致性能下降"
    
    symptoms:
      metrics:
        - name: "container_cpu_cfs_throttled_seconds_total"
          condition: "> 0"
          rate: "> 50%"
    
    root_cause: "CPU 限制过低"
    severity: "low"
    confidence: 0.8
    
    remediation:
      action: "increase_cpu_limit"
      auto_execute: true
      params:
        increase_ratio: 1.5
        max_limit: "2000m"

  - id: "network-001"
    name: "Service Connection Refused"
    description: "服务连接被拒绝"
    
    symptoms:
      events:
        - message: "connection refused"
      logs:
        - pattern: "ECONNREFUSED|Connection refused"
    
    root_cause: "目标服务不可用或网络隔离"
    severity: "high"
    confidence: 0.75
    
    remediation:
      action: "manual_review"
      auto_execute: false
      checklist:
        - "检查目标 Pod 是否运行"
        - "检查 Service 配置"
        - "检查 NetworkPolicy"

  - id: "pvc-001"
    name: "PVC Pending"
    description: "存储卷绑定失败"
    
    symptoms:
      events:
        - reason: "FailedBinding"
        - reason: "ProvisioningFailed"
    
    root_cause: "StorageClass 配置错误或存储资源不足"
    severity: "high"
    confidence: 0.9
    
    remediation:
      action: "manual_review"
      auto_execute: false
      suggestion: "检查 StorageClass 和存储配额"

  - id: "node-001"
    name: "Node NotReady"
    description: "节点不可用"
    
    symptoms:
      events:
        - reason: "NodeNotReady"
        - reason: "NodeStatusUnknown"
    
    root_cause: "节点网络故障或 kubelet 异常"
    severity: "high"
    confidence: 0.85
    
    remediation:
      action: "manual_review"
      auto_execute: false
      checklist:
        - "检查节点网络连通性"
        - "检查 kubelet 日志"
        - "考虑 drain 节点"
```

---

## 4. Python 实现

### 4.1 数据模型

```python
# src/rca/models.py

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Any

class Severity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

@dataclass
class Symptom:
    """症状定义"""
    source: str  # events, metrics, logs
    field: str   # reason, name, pattern
    value: str
    condition: Optional[str] = None
    required: bool = True

@dataclass
class Remediation:
    """修复方案"""
    action: str
    auto_execute: bool
    params: Dict[str, Any] = field(default_factory=dict)
    conditions: List[str] = field(default_factory=list)
    rollback: Optional[Dict] = None
    suggestion: Optional[str] = None
    checklist: List[str] = field(default_factory=list)

@dataclass
class Pattern:
    """故障模式"""
    id: str
    name: str
    description: str
    symptoms: List[Symptom]
    root_cause: str
    severity: Severity
    confidence: float
    remediation: Remediation
    references: List[str] = field(default_factory=list)

@dataclass
class RCAResult:
    """诊断结果"""
    pattern_id: str
    pattern_name: str
    root_cause: str
    severity: Severity
    confidence: float
    matched_symptoms: List[str]
    remediation: Remediation
    evidence: List[str] = field(default_factory=list)
    timestamp: str = ""
```

### 4.2 Pattern Matcher

```python
# src/rca/pattern_matcher.py

import yaml
import re
from typing import List, Optional, Dict, Any
from .models import Pattern, RCAResult, Severity, Remediation, Symptom

class PatternMatcher:
    """规则匹配引擎"""
    
    def __init__(self, config_path: str = "config/rca_patterns.yaml"):
        self.patterns = self._load_patterns(config_path)
    
    def _load_patterns(self, path: str) -> List[Pattern]:
        """加载规则配置"""
        with open(path, 'r') as f:
            config = yaml.safe_load(f)
        
        patterns = []
        for p in config.get('patterns', []):
            patterns.append(self._parse_pattern(p))
        return patterns
    
    def _parse_pattern(self, data: Dict) -> Pattern:
        """解析单个规则"""
        symptoms = []
        for source, items in data.get('symptoms', {}).items():
            for item in items:
                symptoms.append(Symptom(
                    source=source,
                    field=list(item.keys())[0] if isinstance(item, dict) else 'value',
                    value=list(item.values())[0] if isinstance(item, dict) else item,
                    required=item.get('required', True) if isinstance(item, dict) else True
                ))
        
        remediation_data = data.get('remediation', {})
        remediation = Remediation(
            action=remediation_data.get('action', 'manual_review'),
            auto_execute=remediation_data.get('auto_execute', False),
            params=remediation_data.get('params', {}),
            conditions=remediation_data.get('conditions', []),
            rollback=remediation_data.get('rollback'),
            suggestion=remediation_data.get('suggestion'),
            checklist=remediation_data.get('checklist', [])
        )
        
        return Pattern(
            id=data['id'],
            name=data['name'],
            description=data.get('description', ''),
            symptoms=symptoms,
            root_cause=data['root_cause'],
            severity=Severity(data.get('severity', 'medium')),
            confidence=data.get('confidence', 0.8),
            remediation=remediation,
            references=data.get('references', [])
        )
    
    def match(self, telemetry: Dict[str, Any]) -> Optional[RCAResult]:
        """匹配规则"""
        events = telemetry.get('events', [])
        metrics = telemetry.get('metrics', {})
        logs = telemetry.get('logs', [])
        
        best_match = None
        best_confidence = 0
        
        for pattern in self.patterns:
            matched, evidence = self._match_pattern(pattern, events, metrics, logs)
            if matched and pattern.confidence > best_confidence:
                best_match = RCAResult(
                    pattern_id=pattern.id,
                    pattern_name=pattern.name,
                    root_cause=pattern.root_cause,
                    severity=pattern.severity,
                    confidence=pattern.confidence,
                    matched_symptoms=[s.value for s in pattern.symptoms],
                    remediation=pattern.remediation,
                    evidence=evidence
                )
                best_confidence = pattern.confidence
        
        return best_match
    
    def _match_pattern(self, pattern: Pattern, 
                       events: List, metrics: Dict, logs: List) -> tuple:
        """匹配单个规则"""
        evidence = []
        required_matched = 0
        required_total = sum(1 for s in pattern.symptoms if s.required)
        
        for symptom in pattern.symptoms:
            matched = False
            
            if symptom.source == 'events':
                for event in events:
                    if self._match_event(symptom, event):
                        matched = True
                        evidence.append(f"Event: {event.get('reason', event)}")
                        break
                        
            elif symptom.source == 'metrics':
                if self._match_metric(symptom, metrics):
                    matched = True
                    evidence.append(f"Metric: {symptom.field} {symptom.condition}")
                    
            elif symptom.source == 'logs':
                for log in logs:
                    if self._match_log(symptom, log):
                        matched = True
                        evidence.append(f"Log: matched pattern '{symptom.value}'")
                        break
            
            if matched and symptom.required:
                required_matched += 1
            elif not matched and symptom.required:
                return False, []
        
        # 至少匹配一个必需症状
        return required_matched > 0, evidence
    
    def _match_event(self, symptom: Symptom, event: Dict) -> bool:
        """匹配事件"""
        if symptom.field == 'reason':
            return event.get('reason') == symptom.value
        elif symptom.field == 'type':
            return event.get('type') == symptom.value
        elif symptom.field == 'message':
            return symptom.value.lower() in event.get('message', '').lower()
        return False
    
    def _match_metric(self, symptom: Symptom, metrics: Dict) -> bool:
        """匹配指标"""
        # 简化实现，实际需要解析条件表达式
        value = metrics.get(symptom.field)
        if value is None:
            return False
        # TODO: 解析 condition 表达式
        return True
    
    def _match_log(self, symptom: Symptom, log: str) -> bool:
        """匹配日志"""
        pattern = symptom.value
        return bool(re.search(pattern, log, re.IGNORECASE))
    
    def get_pattern(self, pattern_id: str) -> Optional[Pattern]:
        """获取指定规则"""
        for p in self.patterns:
            if p.id == pattern_id:
                return p
        return None
    
    def list_patterns(self) -> List[Dict]:
        """列出所有规则"""
        return [
            {
                "id": p.id,
                "name": p.name,
                "severity": p.severity.value,
                "auto_execute": p.remediation.auto_execute
            }
            for p in self.patterns
        ]
```

### 4.3 集成 ACI

```python
# src/rca/rca_engine.py

from datetime import datetime
from typing import Optional
from src.aci import AgentCloudInterface
from src.voting import MultiAgentVoting, TaskType
from .pattern_matcher import PatternMatcher
from .models import RCAResult, Severity

class RCAEngine:
    """根因分析引擎"""
    
    def __init__(self):
        self.aci = AgentCloudInterface()
        self.matcher = PatternMatcher()
        self.voting = MultiAgentVoting()
    
    def analyze(self, namespace: str, 
                pod: Optional[str] = None) -> RCAResult:
        """执行根因分析"""
        
        # 1. 收集遥测数据
        telemetry = self._collect_telemetry(namespace, pod)
        
        # 2. 规则匹配 (快速路径)
        result = self.matcher.match(telemetry)
        
        if result and result.confidence >= 0.85:
            result.timestamp = datetime.now().isoformat()
            return result
        
        # 3. 如果规则匹配置信度不够，使用 Multi-Agent Voting
        if result is None or result.confidence < 0.85:
            voting_result = self._voting_analysis(telemetry)
            if voting_result:
                return voting_result
        
        # 4. 返回规则匹配结果 (即使置信度较低)
        if result:
            result.timestamp = datetime.now().isoformat()
            return result
        
        # 5. 无法诊断
        return RCAResult(
            pattern_id="unknown",
            pattern_name="Unknown Issue",
            root_cause="无法自动诊断，需要人工分析",
            severity=Severity.HIGH,
            confidence=0.0,
            matched_symptoms=[],
            remediation=Remediation(
                action="manual_review",
                auto_execute=False
            ),
            evidence=[]
        )
    
    def _collect_telemetry(self, namespace: str, 
                          pod: Optional[str]) -> dict:
        """收集遥测数据"""
        events = self.aci.get_events(namespace=namespace)
        metrics = self.aci.get_metrics(namespace=namespace)
        logs = self.aci.get_logs(namespace=namespace, pod=pod) if pod else None
        
        return {
            "events": events.data if events.success else [],
            "metrics": metrics.data if metrics.success else {},
            "logs": logs.data if logs and logs.success else []
        }
    
    def _voting_analysis(self, telemetry: dict) -> Optional[RCAResult]:
        """使用 Multi-Agent Voting 分析"""
        # 构造分析上下文
        context = f"""
        Events: {telemetry['events'][:5]}
        Metrics: {telemetry['metrics']}
        Logs: {telemetry['logs'][:10] if telemetry['logs'] else 'N/A'}
        """
        
        result = self.voting.vote(
            task_type=TaskType.ANALYSIS,
            query="分析以下遥测数据，确定根因",
            context=context
        )
        
        if result.consensus:
            severity = self._infer_severity(result.final_answer)
            return RCAResult(
                pattern_id="voting-result",
                pattern_name="Multi-Agent Analysis",
                root_cause=result.final_answer,
                severity=severity,
                confidence=result.confidence,
                matched_symptoms=[],
                remediation=Remediation(
                    action="manual_review",
                    auto_execute=False,
                    suggestion=result.final_answer
                ),
                evidence=[]
            )
        
        return None
    
    def _infer_severity(self, diagnosis: str) -> Severity:
        """根据诊断推断严重程度"""
        high_keywords = ["node", "network", "pvc", "critical", "down"]
        low_keywords = ["throttl", "evict", "cleanup"]
        
        diagnosis_lower = diagnosis.lower()
        
        if any(kw in diagnosis_lower for kw in high_keywords):
            return Severity.HIGH
        elif any(kw in diagnosis_lower for kw in low_keywords):
            return Severity.LOW
        else:
            return Severity.MEDIUM
```

---

## 5. API 端点

```python
# api_server.py 新增

@app.get("/api/rca/patterns")
async def list_patterns():
    """列出所有规则"""
    matcher = PatternMatcher()
    return {"patterns": matcher.list_patterns()}

@app.get("/api/rca/patterns/{pattern_id}")
async def get_pattern(pattern_id: str):
    """获取规则详情"""
    matcher = PatternMatcher()
    pattern = matcher.get_pattern(pattern_id)
    if not pattern:
        raise HTTPException(404, "Pattern not found")
    return pattern

@app.post("/api/rca/analyze")
async def analyze_rca(request: RCARequest):
    """执行根因分析"""
    engine = RCAEngine()
    result = engine.analyze(
        namespace=request.namespace,
        pod=request.pod
    )
    return result
```

---

## 6. 测试用例

```python
# tests/test_rca_patterns.py

def test_oom_pattern_match():
    """测试 OOM 规则匹配"""
    matcher = PatternMatcher()
    
    telemetry = {
        "events": [{"reason": "OOMKilled", "type": "Warning"}],
        "metrics": {"container_memory_usage_bytes": 95},
        "logs": ["java.lang.OutOfMemoryError: Java heap space"]
    }
    
    result = matcher.match(telemetry)
    
    assert result is not None
    assert result.pattern_id == "oom-001"
    assert result.severity == Severity.MEDIUM
    assert result.remediation.auto_execute == True

def test_image_pull_pattern():
    """测试镜像拉取失败规则"""
    matcher = PatternMatcher()
    
    telemetry = {
        "events": [{"reason": "ImagePullBackOff"}],
        "metrics": {},
        "logs": []
    }
    
    result = matcher.match(telemetry)
    
    assert result is not None
    assert result.pattern_id == "image-001"
    assert result.severity == Severity.HIGH
    assert result.remediation.auto_execute == False  # 需要人工确认
```

---

## 7. 扩展点

1. **条件表达式解析**: 支持复杂的 metric 条件 (>, <, ==, between)
2. **权重匹配**: 不同症状权重不同
3. **时间窗口**: 症状在指定时间窗口内出现
4. **关联规则**: Pattern 之间的关联和排斥

---

**设计状态**: ✅ 完成  
**下一步**: @Developer 开始实现
