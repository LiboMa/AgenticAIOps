"""
Health Check Scheduler

Uses APScheduler for periodic health checks with configurable intervals.
"""

import logging
from datetime import datetime, UTC
from typing import Optional, Callable, Dict, Any, List

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .models import HealthCheckConfig, CheckType, HealthCheckResult
from .checker import HealthChecker

logger = logging.getLogger(__name__)


class HealthCheckScheduler:
    """
    Scheduled health check manager using APScheduler.
    
    Runs periodic health checks and stores results.
    Can trigger callbacks on status changes.
    
    Example:
        scheduler = HealthCheckScheduler(
            config=HealthCheckConfig(interval_seconds=60)
        )
        
        # Optional: add callback for status changes
        scheduler.on_status_change = lambda result: print(f"Status: {result.status}")
        
        scheduler.start()
        # ...
        scheduler.stop()
    """
    
    def __init__(
        self,
        config: Optional[HealthCheckConfig] = None,
        checker: Optional[HealthChecker] = None,
    ):
        """
        Initialize the scheduler.
        
        Args:
            config: Health check configuration
            checker: HealthChecker instance (created if None)
        """
        self.config = config or HealthCheckConfig()
        self.checker = checker or HealthChecker(config=self.config)
        
        self._scheduler: Optional[BackgroundScheduler] = None
        self._last_result: Optional[HealthCheckResult] = None
        self._results_history: List[HealthCheckResult] = []
        self._max_history = 100
        
        # Callbacks
        self.on_status_change: Optional[Callable[[HealthCheckResult], None]] = None
        self.on_critical: Optional[Callable[[HealthCheckResult], None]] = None
        self.on_check_complete: Optional[Callable[[HealthCheckResult], None]] = None
    
    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._scheduler is not None and self._scheduler.running
    
    @property
    def last_result(self) -> Optional[HealthCheckResult]:
        """Get the last health check result."""
        return self._last_result
    
    def start(self) -> None:
        """Start the health check scheduler."""
        if not self.config.enabled:
            logger.info("Health check scheduler is disabled")
            return
        
        if self.is_running:
            logger.warning("Health check scheduler is already running")
            return
        
        self._scheduler = BackgroundScheduler()
        
        # Add the health check job
        self._scheduler.add_job(
            self._run_check,
            trigger=IntervalTrigger(seconds=self.config.interval_seconds),
            id='health_check',
            name='Periodic Health Check',
            replace_existing=True,
            next_run_time=datetime.now(UTC),  # Run immediately
        )
        
        self._scheduler.start()
        logger.info(
            f"Health check scheduler started "
            f"(interval={self.config.interval_seconds}s)"
        )
    
    def stop(self) -> None:
        """Stop the health check scheduler."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Health check scheduler stopped")
        
        self._scheduler = None
    
    def run_now(self) -> HealthCheckResult:
        """
        Run health check immediately (outside of schedule).
        
        Returns:
            HealthCheckResult
        """
        return self._run_check()
    
    def _run_check(self) -> HealthCheckResult:
        """Execute the health check."""
        logger.debug("Running scheduled health check")
        
        try:
            namespaces = self.config.namespaces or None
            result = self.checker.run_full_check(namespaces=namespaces)
            
            # Store result
            self._store_result(result)
            
            # Fire callbacks
            if self.on_check_complete:
                self.on_check_complete(result)
            
            # Check for status change
            if self._last_result:
                if result.status != self._last_result.status:
                    logger.info(
                        f"Health status changed: "
                        f"{self._last_result.status.value} -> {result.status.value}"
                    )
                    if self.on_status_change:
                        self.on_status_change(result)
            
            # Check for critical status
            from .models import CheckStatus
            if result.status == CheckStatus.CRITICAL:
                logger.warning(f"Critical health check result: {result.critical_count} critical items")
                if self.on_critical:
                    self.on_critical(result)
            
            self._last_result = result
            return result
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            from .models import CheckStatus
            return HealthCheckResult(
                check_type=CheckType.FULL,
                status=CheckStatus.UNKNOWN,
                items=[],
            )
    
    def _store_result(self, result: HealthCheckResult) -> None:
        """Store result in history."""
        self._results_history.append(result)
        
        # Trim history
        if len(self._results_history) > self._max_history:
            self._results_history = self._results_history[-self._max_history:]
    
    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent health check history."""
        return [r.to_dict() for r in self._results_history[-limit:]]
    
    def get_status(self) -> Dict[str, Any]:
        """Get scheduler status."""
        return {
            "running": self.is_running,
            "enabled": self.config.enabled,
            "interval_seconds": self.config.interval_seconds,
            "namespaces": self.config.namespaces,
            "check_types": [ct.value for ct in self.config.check_types],
            "last_check": self._last_result.to_dict() if self._last_result else None,
            "history_count": len(self._results_history),
        }
    
    def update_config(self, config: HealthCheckConfig) -> None:
        """
        Update scheduler configuration.
        
        Restarts the scheduler if it was running.
        """
        was_running = self.is_running
        
        if was_running:
            self.stop()
        
        self.config = config
        self.checker.config = config
        
        if was_running:
            self.start()
