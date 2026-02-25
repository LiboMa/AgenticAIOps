"""
Pydantic request/response models shared across routers.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel


# =============================================================================
# Chat
# =============================================================================

class ChatRequest(BaseModel):
    message: str
    model: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    intent: Optional[str] = None
    confidence: Optional[float] = None
    ui_action: Optional[dict] = None
    model_used: Optional[str] = None


# =============================================================================
# A2UI
# =============================================================================

class A2UIWidgetConfig(BaseModel):
    id: Optional[str] = None
    type: str
    config: dict
    span: Optional[int] = 8

class A2UIGenerateRequest(BaseModel):
    prompt: str

class A2UIGenerateResponse(BaseModel):
    success: bool
    widget: Optional[A2UIWidgetConfig] = None
    message: str


# =============================================================================
# RCA
# =============================================================================

class RCAReport(BaseModel):
    id: str
    title: str
    status: str
    severity: str
    createdAt: str
    resolvedAt: Optional[str]
    rootCause: str
    symptoms: List[str]
    diagnosis: dict
    solution: str
    commands: List[str]

class RCAAnalyzeRequest(BaseModel):
    symptoms: List[str] = []
    namespace: Optional[str] = None
    pod: Optional[str] = None
    auto_execute: bool = False

class RCAFeedbackRequest(BaseModel):
    execution_id: str
    sop_id: str
    rca_pattern_id: str
    success: bool
    root_cause_confirmed: bool = False
    resolution_time_seconds: int = 0
    notes: str = ""


# =============================================================================
# Plugins / Clusters / Manifests
# =============================================================================

class PluginCreateRequest(BaseModel):
    plugin_type: str
    name: str
    config: dict = {}

class ClusterAddRequest(BaseModel):
    cluster_id: str
    name: str
    region: str
    plugin_type: str
    config: dict = {}

class ManifestRequest(BaseModel):
    name: str
    type: str
    description: str = ""
    icon: str = "🔌"
    enabled: bool = True
    config: dict = {}


# =============================================================================
# ACI
# =============================================================================

class ACILogsRequest(BaseModel):
    namespace: str = "default"
    pod_name: Optional[str] = None
    severity: str = "all"
    duration_minutes: int = 30
    limit: int = 100

class ACIMetricsRequest(BaseModel):
    namespace: str = "default"
    metric_names: List[str] = ["cpu_usage", "memory_usage"]

class ACIEventsRequest(BaseModel):
    namespace: str = "default"
    event_type: str = "all"
    duration_minutes: int = 60
    limit: int = 50

class DiagnosisRequest(BaseModel):
    namespace: str = "default"
    query: str = "What is wrong with this namespace?"


# =============================================================================
# Issues
# =============================================================================

class IssueCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    severity: str = "medium"
    namespace: str = "default"
    resource_type: str = "Pod"
    resource_name: str = ""
    root_cause: Optional[str] = None
    remediation: Optional[str] = None
    pattern_id: Optional[str] = None
    auto_fixable: bool = False

class IssueUpdateRequest(BaseModel):
    status: Optional[str] = None
    severity: Optional[str] = None
    root_cause: Optional[str] = None
    remediation: Optional[str] = None


# =============================================================================
# Proactive
# =============================================================================

class ProactiveToggleRequest(BaseModel):
    task_name: str
    enabled: bool

class ProactiveIntervalRequest(BaseModel):
    task_name: str
    interval_seconds: int

class EventTriggerRequest(BaseModel):
    event_type: str
    event_data: dict = {}


# =============================================================================
# Notifications
# =============================================================================

class AlertRequest(BaseModel):
    title: str
    message: str
    level: str = "warning"
    details: Optional[Dict[str, Any]] = None


# =============================================================================
# Knowledge / SOP / Vector
# =============================================================================

class IncidentLearnRequest(BaseModel):
    incident_id: str
    title: str
    description: str
    service: str
    severity: str
    symptoms: List[str] = []
    root_cause: str = ""
    resolution: str = ""
    resolution_steps: List[str] = []

class FeedbackRequest(BaseModel):
    pattern_id: str
    helpful: bool
    comment: str = ""

class SOPSuggestRequest(BaseModel):
    service: str
    keywords: List[str] = []
    severity: Optional[str] = None

class SOPExecuteRequest(BaseModel):
    sop_id: str
    triggered_by: str = "api"
    context: Dict[str, Any] = {}

class VectorIndexRequest(BaseModel):
    doc_id: str
    title: str
    description: str
    content: str
    doc_type: str
    category: str = ""
    service: str = ""
    severity: str = ""
    tags: List[str] = []

class SemanticSearchRequest(BaseModel):
    query: str
    doc_type: Optional[str] = None
    service: Optional[str] = None
    limit: int = 5

class PatternAddRequest(BaseModel):
    title: str
    description: str
    resource_type: str
    severity: str = "medium"
    symptoms: List[str] = []
    root_cause: str = ""
    remediation: str = ""
    tags: List[str] = []
    quality_score: float = 0.8

class RCARequest(BaseModel):
    id: str = ""
    title: str
    description: str = ""
    resource_type: str


# =============================================================================
# Scanner
# =============================================================================

class SetRegionRequest(BaseModel):
    region: str

class MonitorResourceRequest(BaseModel):
    resource_id: str
    resource_type: str
    name: str = ""
    service: str

class CloudWatchLogsRequest(BaseModel):
    log_group: str
    filter_pattern: str = ""
    limit: int = 100
    hours: int = 1
