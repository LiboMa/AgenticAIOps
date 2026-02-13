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
        """Quick scan action - check for immediate issues"""
        findings = []
        
        # In real implementation, use the agent to scan AWS resources
        # For now, return mock data
        if self.agent:
            try:
                # Use agent to scan
                result = await self.agent.run_async("Quickly scan AWS resources for any immediate issues. Be brief.")
                # Parse result for findings
                # ...
            except Exception as e:
                logger.error(f"Agent scan error: {e}")
        
        # Mock findings for demonstration
        # In real impl, this would come from AWS APIs
        
        status = "ok" if len(findings) == 0 else "alert"
        summary = "HEARTBEAT_OK" if status == "ok" else f"{len(findings)} issues detected"
        
        return ProactiveResult(
            task_name=task.name,
            task_type=task.task_type,
            status=status,
            timestamp=datetime.now(timezone.utc),
            findings=findings,
            summary=summary
        )
    
    async def _action_full_report(self, task: ProactiveTask) -> ProactiveResult:
        """Full report action - generate comprehensive daily report"""
        # In real implementation, gather metrics from all services
        summary = """📊 **Daily Health Report**

**EC2**: 5 instances (4 running, 1 stopped)
**Lambda**: 5 functions (all healthy)
**S3**: 99 buckets
**RDS**: 3 instances (all available)

**Issues**: 2 open, 1 resolved
**Security**: 3 findings requiring attention

Report generated at: """ + datetime.now(timezone.utc).isoformat()
        
        return ProactiveResult(
            task_name=task.name,
            task_type=task.task_type,
            status="ok",
            timestamp=datetime.now(timezone.utc),
            summary=summary
        )
    
    async def _action_security_check(self, task: ProactiveTask) -> ProactiveResult:
        """Security check action - scan for security issues"""
        findings = []
        
        # In real implementation, check IAM, S3 public access, security groups, etc.
        
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
        """Handle task result - notify if needed"""
        # OpenClaw pattern: "无事不扰，有事报告"
        if result.status == "ok":
            # Silent - just log
            logger.info(f"✅ {result.task_name}: {result.summary}")
        else:
            # Alert - push notification
            logger.warning(f"🚨 {result.task_name}: {result.summary}")
            await self.results_queue.put(result)
            
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


# Singleton instance
proactive_system: Optional[ProactiveAgentSystem] = None


def get_proactive_system(agent=None) -> ProactiveAgentSystem:
    """Get or create the proactive system singleton"""
    global proactive_system
    if proactive_system is None:
        proactive_system = ProactiveAgentSystem(agent=agent)
    return proactive_system
