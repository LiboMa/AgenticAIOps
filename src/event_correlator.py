"""
Event Correlator - Multi-source AWS Data Collection & Correlation

Step 1 of the RCA ↔ SOP Enhancement.
This module is READ-ONLY — it collects and correlates data but never modifies resources.

Data Sources (parallel collection via asyncio):
1. CloudWatch Metrics   — CPU, Memory, Network, Disk for EC2/RDS/Lambda
2. CloudWatch Alarms    — Active ALARM/INSUFFICIENT_DATA states
3. CloudTrail Events    — Recent API calls (changes, errors)
4. AWS Health Events    — Service disruptions affecting our resources
5. CloudWatch Logs      — Error log patterns (optional)

Design Decisions:
- All calls are read-only (zero risk)
- Parallel collection via asyncio.gather (<5s target)
- Structured output for RCA Engine consumption
- Graceful degradation: if one source fails, others continue
- Service-specific cooldown periods (Lambda 5m, EC2 15m, RDS 30m)
"""

import asyncio
import boto3
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict
from concurrent.futures import ThreadPoolExecutor
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Thread pool for boto3 calls (boto3 is not async-native)
_executor = ThreadPoolExecutor(max_workers=8)


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class MetricDataPoint:
    """A single metric measurement."""
    namespace: str          # AWS/EC2, AWS/RDS, etc.
    metric_name: str        # CPUUtilization, etc.
    resource_id: str        # i-xxx, db-xxx, etc.
    value: float
    unit: str
    timestamp: str
    stat: str = "Average"   # Average, Maximum, Sum


@dataclass
class AlarmInfo:
    """CloudWatch alarm state."""
    name: str
    state: str              # OK, ALARM, INSUFFICIENT_DATA
    metric_name: str
    namespace: str
    threshold: float
    comparison: str
    resource_id: str = ""
    reason: str = ""
    updated_at: str = ""


@dataclass
class TrailEvent:
    """CloudTrail API event."""
    event_name: str         # RunInstances, StopInstances, etc.
    event_source: str       # ec2.amazonaws.com, etc.
    username: str
    timestamp: str
    resource_type: str = ""
    resource_id: str = ""
    error_code: str = ""    # Non-empty if the call failed
    error_message: str = ""
    read_only: bool = True


@dataclass
class HealthEvent:
    """AWS Health event."""
    service: str
    event_type: str
    status: str             # open, upcoming, closed
    description: str
    start_time: str = ""
    affected_resources: List[str] = field(default_factory=list)


@dataclass
class CorrelatedEvent:
    """
    Correlated event bundle — all data collected for a single analysis.
    
    This is the primary output consumed by the RCA Engine.
    """
    # Collection metadata
    collection_id: str
    timestamp: str
    duration_ms: int            # How long collection took
    region: str
    
    # Data from each source
    metrics: List[MetricDataPoint] = field(default_factory=list)
    alarms: List[AlarmInfo] = field(default_factory=list)
    trail_events: List[TrailEvent] = field(default_factory=list)
    health_events: List[HealthEvent] = field(default_factory=list)
    
    # Collection status per source
    source_status: Dict[str, str] = field(default_factory=dict)
    
    # Pre-computed summaries
    anomalies: List[Dict[str, Any]] = field(default_factory=list)
    recent_changes: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "collection_id": self.collection_id,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "region": self.region,
            "source_status": self.source_status,
            "metrics_count": len(self.metrics),
            "alarms_count": len(self.alarms),
            "alarms_firing": len([a for a in self.alarms if a.state == "ALARM"]),
            "trail_events_count": len(self.trail_events),
            "trail_errors": len([e for e in self.trail_events if e.error_code]),
            "health_events_count": len(self.health_events),
            "anomalies_count": len(self.anomalies),
            "recent_changes_count": len(self.recent_changes),
            "metrics": [asdict(m) for m in self.metrics],
            "alarms": [asdict(a) for a in self.alarms],
            "trail_events": [asdict(e) for e in self.trail_events],
            "health_events": [asdict(h) for h in self.health_events],
            "anomalies": self.anomalies,
            "recent_changes": self.recent_changes,
        }
    
    def to_rca_telemetry(self) -> Dict[str, Any]:
        """Convert to the telemetry format expected by RCA Engine."""
        events = []
        
        # Convert alarms to RCA events
        for alarm in self.alarms:
            if alarm.state == "ALARM":
                events.append({
                    "reason": f"CloudWatch ALARM: {alarm.name}",
                    "message": alarm.reason,
                    "type": "Warning",
                    "source": "cloudwatch_alarm",
                })
        
        # Convert trail errors to RCA events
        for trail in self.trail_events:
            if trail.error_code:
                events.append({
                    "reason": f"API Error: {trail.event_name} → {trail.error_code}",
                    "message": trail.error_message,
                    "type": "Warning",
                    "source": "cloudtrail",
                })
        
        # Convert anomalies
        for anomaly in self.anomalies:
            events.append({
                "reason": anomaly.get("type", "anomaly"),
                "message": anomaly.get("description", ""),
                "type": "Warning",
                "source": "metric_anomaly",
            })
        
        # Build metrics dict
        metrics = {}
        for m in self.metrics:
            key = f"{m.resource_id}:{m.metric_name}"
            metrics[key] = m.value
        
        return {
            "events": events,
            "metrics": metrics,
            "logs": [],  # Step 2: add CloudWatch Logs Insights
        }
    
    def summary(self) -> str:
        """Human-readable summary."""
        firing = [a for a in self.alarms if a.state == "ALARM"]
        errors = [e for e in self.trail_events if e.error_code]
        changes = [e for e in self.trail_events if not e.read_only]
        
        lines = [
            f"📊 **数据采集报告** ({self.region})",
            f"采集耗时: {self.duration_ms}ms",
            "",
        ]
        
        # Alarms
        if firing:
            lines.append(f"🚨 **{len(firing)} 个告警触发中:**")
            for a in firing:
                lines.append(f"  - `{a.name}` ({a.metric_name} {a.comparison} {a.threshold})")
        else:
            lines.append("✅ 无活跃告警")
        
        # Anomalies
        if self.anomalies:
            lines.append(f"\n⚠️ **{len(self.anomalies)} 个指标异常:**")
            for an in self.anomalies[:5]:
                lines.append(f"  - {an.get('resource', '?')}: {an.get('description', '?')}")
        
        # Recent changes
        if changes:
            lines.append(f"\n🔄 **{len(changes)} 个近期变更:**")
            for c in changes[:5]:
                lines.append(f"  - `{c.event_name}` by {c.username} ({c.timestamp})")
        
        # Errors
        if errors:
            lines.append(f"\n❌ **{len(errors)} 个 API 错误:**")
            for e in errors[:5]:
                lines.append(f"  - `{e.event_name}` → {e.error_code}")
        
        # Source status
        lines.append("\n**数据源状态:**")
        for src, status in self.source_status.items():
            icon = "✅" if status == "ok" else "❌"
            lines.append(f"  {icon} {src}: {status}")
        
        return "\n".join(lines)


# =============================================================================
# Collectors (each runs in thread pool for parallelism)
# =============================================================================

class EventCorrelator:
    """
    Collects and correlates data from multiple AWS sources.
    
    All operations are READ-ONLY.
    Uses asyncio.gather for parallel collection (<5s target).
    """
    
    def __init__(self, region: str = "ap-southeast-1"):
        self.region = region
        self._session = boto3.Session(region_name=region)
    
    async def collect(
        self,
        services: List[str] = None,
        lookback_minutes: int = 60,
        include_trail: bool = True,
        include_health: bool = True,
    ) -> CorrelatedEvent:
        """
        Collect data from all sources in parallel.
        
        Args:
            services: Filter by services (ec2, rds, lambda). None = all.
            lookback_minutes: How far back to look for events/metrics.
            include_trail: Include CloudTrail events.
            include_health: Include AWS Health events.
            
        Returns:
            CorrelatedEvent with all collected data.
        """
        import hashlib
        start_time = datetime.now(timezone.utc)
        collection_id = hashlib.sha256(
            f"{start_time.isoformat()}:{self.region}".encode()
        ).hexdigest()[:12]
        
        services = services or ["ec2", "rds", "lambda"]
        
        # Parallel collection
        tasks = [
            self._collect_metrics(services, lookback_minutes),
            self._collect_alarms(),
        ]
        if include_trail:
            tasks.append(self._collect_trail_events(lookback_minutes))
        if include_health:
            tasks.append(self._collect_health_events())
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Unpack results
        duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
        
        event = CorrelatedEvent(
            collection_id=collection_id,
            timestamp=start_time.isoformat(),
            duration_ms=duration_ms,
            region=self.region,
        )
        
        # Metrics (index 0)
        if isinstance(results[0], Exception):
            event.source_status["metrics"] = f"error: {results[0]}"
            logger.error(f"Metrics collection failed: {results[0]}")
        else:
            event.metrics = results[0]
            event.source_status["metrics"] = "ok"
        
        # Alarms (index 1)
        if isinstance(results[1], Exception):
            event.source_status["alarms"] = f"error: {results[1]}"
            logger.error(f"Alarms collection failed: {results[1]}")
        else:
            event.alarms = results[1]
            event.source_status["alarms"] = "ok"
        
        # Trail (index 2 if included)
        trail_idx = 2
        if include_trail and trail_idx < len(results):
            if isinstance(results[trail_idx], Exception):
                event.source_status["cloudtrail"] = f"error: {results[trail_idx]}"
                logger.error(f"CloudTrail collection failed: {results[trail_idx]}")
            else:
                event.trail_events = results[trail_idx]
                event.source_status["cloudtrail"] = "ok"
        
        # Health (last if included)
        health_idx = trail_idx + (1 if include_trail else 0)
        if include_health and health_idx < len(results):
            if isinstance(results[health_idx], Exception):
                event.source_status["health"] = f"error: {results[health_idx]}"
                logger.error(f"Health collection failed: {results[health_idx]}")
            else:
                event.health_events = results[health_idx]
                event.source_status["health"] = "ok"
        
        # Post-processing: detect anomalies from metrics
        event.anomalies = self._detect_anomalies(event.metrics)
        
        # Post-processing: extract recent changes from trail
        event.recent_changes = self._extract_changes(event.trail_events)
        
        logger.info(
            f"Collection {collection_id} complete in {duration_ms}ms: "
            f"{len(event.metrics)} metrics, {len(event.alarms)} alarms, "
            f"{len(event.trail_events)} trail events, "
            f"{len(event.anomalies)} anomalies"
        )
        
        return event
    
    # =========================================================================
    # Individual Collectors (run in thread pool)
    # =========================================================================
    
    async def _collect_metrics(
        self, services: List[str], lookback_minutes: int
    ) -> List[MetricDataPoint]:
        """Collect CloudWatch metrics for specified services."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _executor, self._sync_collect_metrics, services, lookback_minutes
        )
    
    def _sync_collect_metrics(
        self, services: List[str], lookback_minutes: int
    ) -> List[MetricDataPoint]:
        """Synchronous metric collection (runs in thread)."""
        cw = self._session.client('cloudwatch')
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=lookback_minutes)
        metrics = []
        
        # Define key metrics per service
        metric_defs = {
            "ec2": [
                ("AWS/EC2", "CPUUtilization", "InstanceId", "Percent"),
                ("AWS/EC2", "NetworkIn", "InstanceId", "Bytes"),
                ("AWS/EC2", "StatusCheckFailed", "InstanceId", "Count"),
            ],
            "rds": [
                ("AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", "Percent"),
                ("AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier", "Count"),
                ("AWS/RDS", "FreeStorageSpace", "DBInstanceIdentifier", "Bytes"),
                ("AWS/RDS", "ReadLatency", "DBInstanceIdentifier", "Seconds"),
            ],
            "lambda": [
                ("AWS/Lambda", "Errors", "FunctionName", "Count"),
                ("AWS/Lambda", "Duration", "FunctionName", "Milliseconds"),
                ("AWS/Lambda", "Throttles", "FunctionName", "Count"),
                ("AWS/Lambda", "ConcurrentExecutions", "FunctionName", "Count"),
            ],
        }
        
        for service in services:
            if service not in metric_defs:
                continue
            
            for namespace, metric_name, dim_name, unit in metric_defs[service]:
                try:
                    # Use list_metrics to find actual resources
                    paginator = cw.get_paginator('list_metrics')
                    for page in paginator.paginate(
                        Namespace=namespace,
                        MetricName=metric_name,
                        RecentlyActive='PT3H',
                    ):
                        for m in page.get('Metrics', [])[:10]:  # Limit per metric
                            dims = {d['Name']: d['Value'] for d in m.get('Dimensions', [])}
                            resource_id = dims.get(dim_name, 'unknown')
                            
                            # Get latest value
                            stats = cw.get_metric_statistics(
                                Namespace=namespace,
                                MetricName=metric_name,
                                Dimensions=m['Dimensions'],
                                StartTime=start_time,
                                EndTime=end_time,
                                Period=300,  # 5 min
                                Statistics=['Average', 'Maximum'],
                            )
                            
                            datapoints = stats.get('Datapoints', [])
                            if datapoints:
                                latest = sorted(datapoints, key=lambda x: x['Timestamp'])[-1]
                                metrics.append(MetricDataPoint(
                                    namespace=namespace,
                                    metric_name=metric_name,
                                    resource_id=resource_id,
                                    value=round(latest.get('Average', 0), 2),
                                    unit=unit,
                                    timestamp=latest['Timestamp'].isoformat(),
                                    stat="Average",
                                ))
                except ClientError as e:
                    logger.warning(f"Failed to collect {namespace}/{metric_name}: {e}")
                except Exception as e:
                    logger.warning(f"Unexpected error collecting {metric_name}: {e}")
        
        return metrics
    
    async def _collect_alarms(self) -> List[AlarmInfo]:
        """Collect CloudWatch alarm states."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self._sync_collect_alarms)
    
    def _sync_collect_alarms(self) -> List[AlarmInfo]:
        """Synchronous alarm collection."""
        cw = self._session.client('cloudwatch')
        alarms = []
        
        try:
            paginator = cw.get_paginator('describe_alarms')
            for page in paginator.paginate(
                StateValue='ALARM',  # Only firing alarms
                MaxRecords=50,
            ):
                for alarm in page.get('MetricAlarms', []):
                    dims = {d['Name']: d['Value'] for d in alarm.get('Dimensions', [])}
                    resource_id = next(iter(dims.values()), '') if dims else ''
                    
                    alarms.append(AlarmInfo(
                        name=alarm['AlarmName'],
                        state=alarm['StateValue'],
                        metric_name=alarm.get('MetricName', ''),
                        namespace=alarm.get('Namespace', ''),
                        threshold=alarm.get('Threshold', 0),
                        comparison=alarm.get('ComparisonOperator', ''),
                        resource_id=resource_id,
                        reason=alarm.get('StateReason', '')[:200],
                        updated_at=alarm.get('StateUpdatedTimestamp', datetime.now(timezone.utc)).isoformat(),
                    ))
            
            # Also get INSUFFICIENT_DATA alarms (potential issues)
            for page in paginator.paginate(
                StateValue='INSUFFICIENT_DATA',
                MaxRecords=20,
            ):
                for alarm in page.get('MetricAlarms', []):
                    dims = {d['Name']: d['Value'] for d in alarm.get('Dimensions', [])}
                    resource_id = next(iter(dims.values()), '') if dims else ''
                    
                    alarms.append(AlarmInfo(
                        name=alarm['AlarmName'],
                        state=alarm['StateValue'],
                        metric_name=alarm.get('MetricName', ''),
                        namespace=alarm.get('Namespace', ''),
                        threshold=alarm.get('Threshold', 0),
                        comparison=alarm.get('ComparisonOperator', ''),
                        resource_id=resource_id,
                        reason=alarm.get('StateReason', '')[:200],
                        updated_at=alarm.get('StateUpdatedTimestamp', datetime.now(timezone.utc)).isoformat(),
                    ))
        except ClientError as e:
            logger.error(f"Failed to describe alarms: {e}")
        
        return alarms
    
    async def _collect_trail_events(
        self, lookback_minutes: int
    ) -> List[TrailEvent]:
        """Collect CloudTrail events."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _executor, self._sync_collect_trail, lookback_minutes
        )
    
    def _sync_collect_trail(self, lookback_minutes: int) -> List[TrailEvent]:
        """Synchronous CloudTrail collection with retry and page limit.
        
        Bug-013: CloudTrail API throttles under load. Mitigations:
        - Exponential backoff retry (3 attempts, 1s/2s/4s)
        - Max 3 pages to cap total API calls
        - Specific ThrottlingException handling
        """
        ct = self._session.client('cloudtrail')
        events = []
        
        start_time = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
        max_pages = 3  # Cap pages to reduce API pressure
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                paginator = ct.get_paginator('lookup_events')
                page_count = 0
                for page in paginator.paginate(
                    StartTime=start_time,
                    EndTime=datetime.now(timezone.utc),
                    MaxResults=50,
                    LookupAttributes=[{
                        'AttributeKey': 'ReadOnly',
                        'AttributeValue': 'false'
                    }],
                ):
                    page_count += 1
                    for event in page.get('Events', []):
                        resources = event.get('Resources', [])
                        resource_type = resources[0]['ResourceType'] if resources else ''
                        resource_id = resources[0]['ResourceName'] if resources else ''
                        
                        # Parse CloudTrail event for error info
                        detail = {}
                        try:
                            detail = json.loads(event.get('CloudTrailEvent', '{}'))
                        except (json.JSONDecodeError, TypeError):
                            pass
                        
                        events.append(TrailEvent(
                            event_name=event.get('EventName', ''),
                            event_source=event.get('EventSource', ''),
                            username=event.get('Username', 'unknown'),
                            timestamp=event.get('EventTime', datetime.now(timezone.utc)).isoformat(),
                            resource_type=resource_type,
                            resource_id=resource_id,
                            error_code=detail.get('errorCode', ''),
                            error_message=detail.get('errorMessage', '')[:200] if detail.get('errorMessage') else '',
                            read_only=False,
                        ))
                    
                    if page_count >= max_pages:
                        logger.info(f"CloudTrail: hit page limit ({max_pages}), collected {len(events)} events")
                        break
                
                # Success — exit retry loop
                return events
                
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', '')
                if error_code in ('ThrottlingException', 'Throttling', 'RequestLimitExceeded'):
                    backoff = 2 ** attempt  # 1s, 2s, 4s
                    logger.warning(
                        f"CloudTrail throttled (attempt {attempt + 1}/{max_retries}), "
                        f"backing off {backoff}s"
                    )
                    time.sleep(backoff)
                    events = []  # Reset for retry
                    continue
                else:
                    logger.error(f"CloudTrail lookup failed: {e}")
                    return events
        
        logger.error(f"CloudTrail collection failed after {max_retries} retries")
        return events
    
    async def _collect_health_events(self) -> List[HealthEvent]:
        """Collect AWS Health events."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self._sync_collect_health)
    
    def _sync_collect_health(self) -> List[HealthEvent]:
        """Synchronous AWS Health collection."""
        events = []
        
        try:
            # Health API requires us-east-1 for global events
            health = boto3.client('health', region_name='us-east-1')
            
            response = health.describe_events(
                filter={
                    'eventStatusCodes': ['open', 'upcoming'],
                },
                maxResults=10,
            )
            
            for event in response.get('events', []):
                events.append(HealthEvent(
                    service=event.get('service', ''),
                    event_type=event.get('eventTypeCode', ''),
                    status=event.get('statusCode', ''),
                    description=event.get('eventTypeCategory', ''),
                    start_time=event.get('startTime', datetime.now(timezone.utc)).isoformat(),
                ))
        except ClientError as e:
            # Health API may not be available in all accounts
            logger.warning(f"AWS Health API failed (may need Business/Enterprise support): {e}")
        except Exception as e:
            logger.warning(f"AWS Health collection error: {e}")
        
        return events
    
    # =========================================================================
    # Post-Processing
    # =========================================================================
    
    def _detect_anomalies(self, metrics: List[MetricDataPoint]) -> List[Dict[str, Any]]:
        """
        Detect anomalies from collected metrics using simple thresholds.
        
        Step 2 will enhance this with CloudWatch Anomaly Detection API.
        """
        anomalies = []
        
        # Threshold definitions
        thresholds = {
            "CPUUtilization": {"warn": 70, "critical": 90, "unit": "%"},
            "DatabaseConnections": {"warn": 80, "critical": 100, "unit": "connections"},
            "Errors": {"warn": 5, "critical": 20, "unit": "errors"},
            "Throttles": {"warn": 5, "critical": 20, "unit": "throttles"},
            "StatusCheckFailed": {"warn": 0.5, "critical": 1, "unit": "checks"},
            "ReadLatency": {"warn": 0.01, "critical": 0.05, "unit": "seconds"},
        }
        
        for m in metrics:
            if m.metric_name in thresholds:
                t = thresholds[m.metric_name]
                severity = None
                
                if m.value >= t["critical"]:
                    severity = "critical"
                elif m.value >= t["warn"]:
                    severity = "warning"
                
                if severity:
                    anomalies.append({
                        "resource": m.resource_id,
                        "metric": m.metric_name,
                        "value": m.value,
                        "threshold": t["critical"] if severity == "critical" else t["warn"],
                        "severity": severity,
                        "type": f"{m.metric_name}_anomaly",
                        "description": f"{m.resource_id}: {m.metric_name} = {m.value}{t['unit']} (threshold: {t['warn']}{t['unit']})",
                    })
        
        return anomalies
    
    def _extract_changes(self, trail_events: List[TrailEvent]) -> List[Dict[str, Any]]:
        """Extract significant changes from CloudTrail events."""
        # Mutating events that may cause issues
        significant_events = {
            'RunInstances', 'TerminateInstances', 'StopInstances', 'StartInstances',
            'ModifyInstanceAttribute', 'AuthorizeSecurityGroupIngress',
            'RevokeSecurityGroupIngress', 'CreateSecurityGroup', 'DeleteSecurityGroup',
            'ModifyDBInstance', 'RebootDBInstance', 'DeleteDBInstance',
            'UpdateFunctionConfiguration', 'UpdateFunctionCode',
            'PutBucketPolicy', 'DeleteBucketPolicy',
            'CreateStack', 'UpdateStack', 'DeleteStack',
        }
        
        changes = []
        for event in trail_events:
            if event.event_name in significant_events or event.error_code:
                changes.append({
                    "event": event.event_name,
                    "source": event.event_source,
                    "user": event.username,
                    "resource": event.resource_id,
                    "timestamp": event.timestamp,
                    "error": event.error_code or None,
                    "is_error": bool(event.error_code),
                })
        
        return changes


# =============================================================================
# Convenience Functions
# =============================================================================

_correlator: Optional[EventCorrelator] = None


def get_correlator(region: str = "ap-southeast-1") -> EventCorrelator:
    """Get or create the event correlator singleton."""
    global _correlator
    if _correlator is None:
        _correlator = EventCorrelator(region=region)
    return _correlator


async def quick_collect(
    services: List[str] = None,
    lookback_minutes: int = 60,
) -> CorrelatedEvent:
    """Quick data collection — convenience wrapper."""
    correlator = get_correlator()
    return await correlator.collect(
        services=services,
        lookback_minutes=lookback_minutes,
    )
