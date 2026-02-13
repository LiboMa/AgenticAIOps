"""
Detect Agent — Bridges existing data collection to Incident Orchestrator.

Architecture (per CLOSED_LOOP_AIOPS_DESIGN.md):
    Detect Agent (持续采集+异常检测)
         │ 检测到异常 → 传递已采集数据
         ▼
    RCA Agent (不再重新采集)
         │
         ▼
    Action Agent (SOP 匹配 + 安全执行)

This module wraps AWSScanner + EventCorrelator so that:
1. Data is collected ONCE and cached
2. IncidentOrchestrator receives pre_collected_event (skips Stage 1)
3. Manual `incident run` also reuses cached data if fresh enough
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class DetectAgent:
    """
    Detect Agent: owns data collection and anomaly detection.
    
    Provides pre-collected data to IncidentOrchestrator,
    eliminating duplicate AWS API calls.
    """
    
    CACHE_TTL_SECONDS = 300  # 5 minutes
    
    def __init__(self, region: str = "ap-southeast-1"):
        self.region = region
        self._cached_event = None
        self._cache_timestamp: float = 0
        self._collecting = False
    
    @property
    def has_fresh_data(self) -> bool:
        if self._cached_event is None:
            return False
        return (time.time() - self._cache_timestamp) < self.CACHE_TTL_SECONDS
    
    @property
    def cache_age_seconds(self) -> float:
        if self._cached_event is None:
            return float('inf')
        return time.time() - self._cache_timestamp
    
    async def collect(
        self,
        services: Optional[List[str]] = None,
        lookback_minutes: int = 15,
        force_refresh: bool = False,
    ):
        """Collect from AWS — returns cached data if fresh."""
        if self.has_fresh_data and not force_refresh and services is None:
            logger.info(
                f"DetectAgent: Reusing cached data "
                f"(age={self.cache_age_seconds:.0f}s)"
            )
            return self._cached_event
        
        if self._collecting:
            for _ in range(60):
                await asyncio.sleep(1)
                if not self._collecting and self._cached_event is not None:
                    return self._cached_event
        
        self._collecting = True
        try:
            from src.event_correlator import get_correlator
            correlator = get_correlator(self.region)
            
            start = time.time()
            event = await correlator.collect(
                services=services,
                lookback_minutes=lookback_minutes,
            )
            duration = time.time() - start
            
            if services is None:
                self._cached_event = event
                self._cache_timestamp = time.time()
                logger.info(f"DetectAgent: Collected in {duration:.1f}s, cached")
            
            return event
        finally:
            self._collecting = False
    
    async def trigger_incident(
        self,
        trigger_type: str = "detect_agent",
        services: Optional[List[str]] = None,
        auto_execute: bool = False,
        dry_run: bool = True,
        lookback_minutes: int = 15,
    ):
        """
        Full detect → RCA → SOP pipeline, reusing cached data.
        
        1. Detect Agent collects data (or reuses cache)
        2. Passes pre_collected_event to IncidentOrchestrator
        3. Orchestrator skips Stage 1, goes directly to RCA
        """
        from src.incident_orchestrator import get_orchestrator
        
        event = await self.collect(
            services=services,
            lookback_minutes=lookback_minutes,
        )
        
        orchestrator = get_orchestrator(self.region)
        incident = await orchestrator.handle_incident(
            trigger_type=trigger_type,
            trigger_data={"source": "detect_agent", "cache_age": self.cache_age_seconds},
            services=services,
            auto_execute=auto_execute,
            dry_run=dry_run,
            pre_collected_event=event,
        )
        
        return incident
    
    def invalidate_cache(self):
        self._cached_event = None
        self._cache_timestamp = 0
    
    def status(self) -> Dict[str, Any]:
        return {
            "has_cached_data": self._cached_event is not None,
            "cache_age_seconds": round(self.cache_age_seconds, 1) if self._cached_event else None,
            "cache_ttl_seconds": self.CACHE_TTL_SECONDS,
            "cache_fresh": self.has_fresh_data,
            "collecting": self._collecting,
        }


# Singleton
_detect_agent: Optional[DetectAgent] = None


def get_detect_agent(region: str = "ap-southeast-1") -> DetectAgent:
    """Get or create the singleton DetectAgent."""
    global _detect_agent
    if _detect_agent is None or _detect_agent.region != region:
        _detect_agent = DetectAgent(region=region)
    return _detect_agent
