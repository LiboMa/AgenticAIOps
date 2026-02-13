"""
Proactive Agent System (OpenClaw-inspired)

This module implements the proactive monitoring capabilities:
- Heartbeat: Periodic resource scanning
- Cron Jobs: Scheduled reports
- Event-driven: Alert-triggered analysis

Design reference: OpenClaw's HEARTBEAT.md + Cron Jobs pattern
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class TaskType(Enum):
    HEARTBEAT = "heartbeat"
    CRON = "cron"
    EVENT = "event"


@dataclass
class ProactiveTask:
    """A proactive task definition"""
    name: str
    task_type: TaskType
    action: str  # Action to perform: "scan", "report", "security_check"
    interval_seconds: Optional[int] = None  # For heartbeat/cron
    cron_expr: Optional[str] = None  # For cron jobs
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProactiveResult:
    """Result from a proactive task"""
    task_name: str
    task_type: TaskType
    status: str  # "ok", "alert", "error"
    timestamp: datetime
    findings: List[Dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    details: Optional[Dict[str, Any]] = None


class ProactiveAgentSystem:
    """
    Proactive Agent System - OpenClaw-inspired design
    
    Core patterns:
    1. Heartbeat: "无事不扰，有事报告" (No news = silence, news = push)
    2. Cron: Scheduled tasks with configurable intervals
    3. Event: Alert-triggered immediate analysis
    """
    
    def __init__(self, agent=None):
        self.agent = agent
        self.tasks: Dict[str, ProactiveTask] = {}
        self.results_queue: asyncio.Queue = asyncio.Queue()
        self.callbacks: Dict[str, Callable] = {}
        self._running = False
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._last_detect_result = None  # DetectResult from last quick_scan
        
        # Default tasks
        self._init_default_tasks()
    
    def _init_default_tasks(self):
        """Initialize default proactive tasks"""
        # Heartbeat - every 5 minutes
        self.tasks["heartbeat"] = ProactiveTask(
            name="heartbeat",
            task_type=TaskType.HEARTBEAT,
            action="quick_scan",
            interval_seconds=300,  # 5 minutes
            config={
                "services": ["ec2", "lambda", "s3", "rds"],
                "check_issues": True,
            }
        )
        
        # Daily report - every 24 hours at 8:00
        self.tasks["daily_report"] = ProactiveTask(
            name="daily_report",
            task_type=TaskType.CRON,
            action="full_report",
            interval_seconds=86400,  # 24 hours
            cron_expr="0 8 * * *",
            config={
                "include_metrics": True,
                "include_security": True,
            }
        )
        
        # Security scan - every 12 hours
        self.tasks["security_scan"] = ProactiveTask(
            name="security_scan",
            task_type=TaskType.CRON,
            action="security_check",
            interval_seconds=43200,  # 12 hours
            config={
                "check_iam": True,
                "check_s3_public": True,
                "check_security_groups": True,
            }
        )
    
    def register_callback(self, event_type: str, callback: Callable):
        """Register a callback for result notifications"""
        self.callbacks[event_type] = callback
    
    async def start(self):
        """Start the proactive agent system"""
        if self._running:
            return
        
        self._running = True
        logger.info("🚀 Proactive Agent System started")
        
        # Start heartbeat loop
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
    
    async def stop(self):
        """Stop the proactive agent system"""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        logger.info("🛑 Proactive Agent System stopped")
    
    async def _heartbeat_loop(self):
        """Main heartbeat loop - runs periodic checks"""
        while self._running:
            try:
                for task_name, task in self.tasks.items():
                    if not task.enabled:
                        continue
                    
                    # Check if task should run
                    if task.interval_seconds and self._should_run(task):
                        result = await self._execute_task(task)
                        await self._handle_result(result)
                        task.last_run = datetime.now(timezone.utc)
                
                # Sleep for 30 seconds between checks
                await asyncio.sleep(30)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat loop error: {e}")
                await asyncio.sleep(60)  # Wait before retry
    
    def _should_run(self, task: ProactiveTask) -> bool:
        """Check if a task should run based on its schedule"""
        if task.last_run is None:
            return True
        
        if task.interval_seconds:
            elapsed = (datetime.now(timezone.utc) - task.last_run).total_seconds()
            return elapsed >= task.interval_seconds
        
        return False
    
    async def _execute_task(self, task: ProactiveTask) -> ProactiveResult:
        """Execute a proactive task"""
        logger.info(f"🔄 Executing proactive task: {task.name}")
        
        try:
            if task.action == "quick_scan":
                return await self._action_quick_scan(task)
            elif task.action == "full_report":
                return await self._action_full_report(task)
            elif task.action == "security_check":
                return await self._action_security_check(task)
            else:
                return ProactiveResult(
                    task_name=task.name,
                    task_type=task.task_type,
                    status="error",
                    timestamp=datetime.now(timezone.utc),
                    summary=f"Unknown action: {task.action}"
                )
        except Exception as e:
            logger.error(f"Task execution error: {e}")
            return ProactiveResult(
                task_name=task.name,
                task_type=task.task_type,
                status="error",
                timestamp=datetime.now(timezone.utc),
                summary=f"Error: {str(e)}"
            )
    
    async def _action_quick_scan(self, task: ProactiveTask) -> ProactiveResult:
        """Quick scan action - delegates to DetectAgent (R3: ProactiveAgent only schedules)."""
        findings = []

        try:
            from src.detect_agent import get_detect_agent

            detect_agent = get_detect_agent()
            detect_result = await detect_agent.run_detection(
                source="proactive_scan",
                services=task.config.get("services", ["ec2", "rds", "lambda"]),
                lookback_minutes=15,
            )

            # Cache the DetectResult for _handle_result to pass to Orchestrator
            self._last_detect_result = detect_result

            if detect_result.error:
                logger.error(f"DetectAgent error: {detect_result.error}")
            else:
                # Convert anomalies to findings
                for anomaly in detect_result.anomalies_detected:
                    findings.append({
                        "type": anomaly.get("type", "unknown"),
                        "resource": anomaly.get("resource", ""),
                        "metric": anomaly.get("metric", ""),
                        "value": anomaly.get("value", 0),
                        "severity": anomaly.get("severity", "warning"),
                        "description": anomaly.get("description", ""),
                    })

                # Convert firing alarms from correlated event
                if detect_result.correlated_event:
                    for alarm in detect_result.correlated_event.alarms:
                        if alarm.state == "ALARM":
                            findings.append({
                                "type": "cloudwatch_alarm",
                                "resource": alarm.resource_id,
                                "metric": alarm.metric_name,
                                "value": alarm.threshold,
                                "severity": "high",
                                "description": f"ALARM: {alarm.name} — {alarm.reason[:100]}",
                            })

        except Exception as e:
            logger.error(f"Quick scan via DetectAgent failed: {e}")
            self._last_detect_result = None

        status = "ok" if len(findings) == 0 else "alert"
        summary = "HEARTBEAT_OK" if status == "ok" else f"{len(findings)} issues detected"

        return ProactiveResult(
            task_name=task.name,
            task_type=task.task_type,
            status=status,
            timestamp=datetime.now(timezone.utc),
            findings=findings,
            summary=summary,
            details={
                "detect_id": getattr(self._last_detect_result, 'detect_id', None),
                "freshness": getattr(self._last_detect_result, 'freshness_label', None),
            },
        )
    
    async def _action_full_report(self, task: ProactiveTask) -> ProactiveResult:
        """Full report action - generate comprehensive daily report using real AWS data."""
        try:
            from src.aws_scanner import get_scanner
            scanner = get_scanner()
            scan_result = scanner.scan_all_resources()
            
            services = scan_result.get("services", {})
            summary_data = scan_result.get("summary", {})
            issues = summary_data.get("issues_found", [])
            
            # Build report from real data
            lines = ["📊 **Daily Health Report**\n"]
            
            for svc_name, svc_data in services.items():
                if isinstance(svc_data, dict) and "count" in svc_data:
                    status_info = svc_data.get("status", {})
                    extra = ""
                    if status_info:
                        parts = [f"{v} {k}" for k, v in status_info.items() if v > 0]
                        if parts:
                            extra = f" ({', '.join(parts)})"
                    lines.append(f"**{svc_name.upper()}**: {svc_data['count']} resources{extra}")
            
            lines.append(f"\n**Issues**: {len(issues)} found")
            for issue in issues:
                lines.append(f"  - [{issue.get('severity', '?').upper()}] {issue.get('service')}: {issue.get('type')}")
            
            lines.append(f"\nReport generated at: {datetime.now(timezone.utc).isoformat()}")
            report_summary = "\n".join(lines)
            
        except Exception as e:
            logger.error(f"Full report generation error: {e}")
            report_summary = f"⚠️ Report generation failed: {e}"
        
        return ProactiveResult(
            task_name=task.name,
            task_type=task.task_type,
            status="ok",
            timestamp=datetime.now(timezone.utc),
            summary=report_summary
        )
    
    async def _action_security_check(self, task: ProactiveTask) -> ProactiveResult:
        """Security check action - scan for real security issues using aws_scanner."""
        findings = []
        
        try:
            from src.aws_scanner import get_scanner
            scanner = get_scanner()
            
            # IAM check
            if task.config.get("check_iam", True):
                iam_result = scanner._scan_iam()
                users_no_mfa = iam_result.get("users_without_mfa", [])
                for user in users_no_mfa:
                    findings.append({
                        "type": "iam_no_mfa",
                        "resource": user,
                        "severity": "critical",
                        "description": f"IAM user '{user}' has no MFA enabled",
                    })
            
            # S3 public access check
            if task.config.get("check_s3_public", True):
                s3_result = scanner._scan_s3()
                for bucket in s3_result.get("buckets", []):
                    if bucket.get("public", False):
                        findings.append({
                            "type": "s3_public_bucket",
                            "resource": bucket["name"],
                            "severity": "critical",
                            "description": f"S3 bucket '{bucket['name']}' has public access",
                        })
            
            # Security group check
            if task.config.get("check_security_groups", True):
                # Check for overly permissive security groups via CloudWatch alarms
                cw_result = scanner._scan_cloudwatch_alarms()
                for alarm in cw_result.get("alarms", []):
                    if alarm.get("state") == "ALARM" and "security" in alarm.get("name", "").lower():
                        findings.append({
                            "type": "security_alarm",
                            "resource": alarm.get("name", ""),
                            "severity": "high",
                            "description": f"Security-related alarm firing: {alarm['name']}",
                        })
        except Exception as e:
            logger.error(f"Security check error: {e}")
        
        status = "ok" if len(findings) == 0 else "alert"
        summary = "Security check complete. No new issues." if status == "ok" else f"{len(findings)} security issues found"
        
        return ProactiveResult(
            task_name=task.name,
            task_type=task.task_type,
            status=status,
            timestamp=datetime.now(timezone.utc),
            findings=findings,
            summary=summary
        )
    
    async def _handle_result(self, result: ProactiveResult):
        """Handle task result - notify if needed, trigger RCA pipeline for alerts."""
        # OpenClaw pattern: "无事不扰，有事报告"
        if result.status == "ok":
            # Silent - just log
            logger.info(f"✅ {result.task_name}: {result.summary}")
        else:
            # Alert - push notification + trigger incident pipeline
            logger.warning(f"🚨 {result.task_name}: {result.summary}")
            await self.results_queue.put(result)

            # Trigger IncidentOrchestrator with DetectAgent's cached result (R3)
            if self._last_detect_result is not None:
                try:
                    from src.incident_orchestrator import get_orchestrator

                    orchestrator = get_orchestrator()
                    incident = await orchestrator.handle_incident(
                        trigger_type="proactive",
                        trigger_data={
                            "task_name": result.task_name,
                            "findings_count": len(result.findings),
                            "summary": result.summary,
                        },
                        detect_result=self._last_detect_result,
                        auto_execute=False,
                    )
                    logger.info(f"Incident pipeline triggered: {incident.incident_id} → {incident.status.value}")
                except Exception as e:
                    logger.error(f"Failed to trigger incident pipeline: {e}")

            # Call registered callbacks
            if "alert" in self.callbacks:
                await self.callbacks["alert"](result)
    
    async def trigger_event(self, event_type: str, event_data: Dict[str, Any]) -> ProactiveResult:
        """Trigger an event-driven task (e.g., CloudWatch alert)"""
        logger.info(f"⚡ Event triggered: {event_type}")
        
        # Create ad-hoc task for the event
        task = ProactiveTask(
            name=f"event_{event_type}",
            task_type=TaskType.EVENT,
            action="analyze_alert",
            config={"event_data": event_data}
        )
        
        # Execute analysis
        result = await self._execute_task(task)
        await self._handle_result(result)
        
        return result
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status of the proactive system"""
        return {
            "running": self._running,
            "tasks": {
                name: {
                    "enabled": task.enabled,
                    "last_run": task.last_run.isoformat() if task.last_run else None,
                    "interval_seconds": task.interval_seconds,
                    "action": task.action,
                }
                for name, task in self.tasks.items()
            }
        }
    
    def enable_task(self, task_name: str, enabled: bool = True):
        """Enable or disable a task"""
        if task_name in self.tasks:
            self.tasks[task_name].enabled = enabled
            logger.info(f"Task {task_name} {'enabled' if enabled else 'disabled'}")
    
    def update_task_interval(self, task_name: str, interval_seconds: int):
        """Update task interval"""
        if task_name in self.tasks:
            self.tasks[task_name].interval_seconds = interval_seconds
            logger.info(f"Task {task_name} interval updated to {interval_seconds}s")
    
    def get_last_detect_result(self):
        """
        Return the last DetectResult from quick_scan.

        IncidentOrchestrator can consume this via
        handle_incident(detect_result=...) to skip Stage 1.
        """
        return self._last_detect_result


# Singleton instance
proactive_system: Optional[ProactiveAgentSystem] = None


def get_proactive_system(agent=None) -> ProactiveAgentSystem:
    """Get or create the proactive system singleton"""
    global proactive_system
    if proactive_system is None:
        proactive_system = ProactiveAgentSystem(agent=agent)
    return proactive_system
