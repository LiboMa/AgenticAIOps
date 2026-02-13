"""
Detect Agent — Unified detection layer with result caching.

Encapsulates data collection (EventCorrelator + AWSScanner) and provides
cached DetectResult objects for downstream consumers (RCA, Orchestrator).

Architecture:
  ProactiveAgent (scheduler) → DetectAgent (collect + detect + cache)
                                    ↓
                             IncidentOrchestrator.handle_incident(detect_result=...)

Design ref: docs/designs/DETECT_AGENT_DATA_REUSE_DESIGN.md
"""

import asyncio
import fcntl
import json
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Default cache directory
DEFAULT_CACHE_DIR = "data/detect_cache"
DETECT_CACHE_DIR = DEFAULT_CACHE_DIR  # Alias for tests


@dataclass
class DetectResult:
    """
    Output of a Detect Agent detection cycle.

    Contains the collected CorrelatedEvent plus detection metadata
    (anomalies, pattern matches, source, freshness).

    This is the primary interface between Detect Agent and RCA Agent.
    """
    # Identity
    detect_id: str
    timestamp: str  # ISO format string
    source: str  # "proactive_scan" | "alarm_trigger" | "manual"

    # Freshness
    ttl_seconds: int = 300  # 5 min default, aligned with ProactiveAgent heartbeat

    # Region
    region: str = "ap-southeast-1"

    # Collected data (from EventCorrelator)
    correlated_event: Any = None  # CorrelatedEvent — Any to avoid circular import

    # Detection outputs
    anomalies_detected: List[Dict[str, Any]] = field(default_factory=list)
    pattern_matches: List[Dict[str, Any]] = field(default_factory=list)

    # Raw trigger data (alarm payload, etc.)
    raw_data: Dict[str, Any] = field(default_factory=dict)

    # Error (if collection failed)
    error: Optional[str] = None

    def _parse_timestamp(self) -> datetime:
        """Parse the ISO timestamp string to datetime."""
        if isinstance(self.timestamp, datetime):
            return self.timestamp
        return datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))

    @property
    def age_seconds(self) -> float:
        """How old this result is (seconds)."""
        return (datetime.now(timezone.utc) - self._parse_timestamp()).total_seconds()

    @property
    def is_stale(self) -> bool:
        """Whether data has exceeded its TTL."""
        return self.age_seconds > self.ttl_seconds

    @property
    def freshness_label(self) -> str:
        """Human-readable freshness indicator for logging/UI."""
        age = self.age_seconds
        if age < 60:
            return "fresh"       # < 1 min
        elif age < self.ttl_seconds:
            return "warm"        # 1 min – TTL
        else:
            return "stale"       # > TTL

    def summary(self) -> str:
        """One-line summary for logging."""
        return (
            f"DetectResult({self.detect_id}, {self.freshness_label}, "
            f"anomalies={len(self.anomalies_detected)}, source={self.source})"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for persistence / API response."""
        result = {
            "detect_id": self.detect_id,
            "timestamp": self.timestamp,
            "source": self.source,
            "region": self.region,
            "ttl_seconds": self.ttl_seconds,
            "age_seconds": round(self.age_seconds, 1),
            "is_stale": self.is_stale,
            "freshness_label": self.freshness_label,
            "freshness": self.freshness_label,  # alias
            "anomalies_detected": self.anomalies_detected,
            "pattern_matches": self.pattern_matches,
            "error": self.error,
            "has_correlated_event": self.correlated_event is not None,
        }
        if self.correlated_event and hasattr(self.correlated_event, "to_dict"):
            result["correlated_event"] = self.correlated_event.to_dict()
        return result


class DetectAgent:
    """
    Unified detection agent — collects, detects, caches.

    Responsibilities:
      - Run periodic detection cycles via EventCorrelator
      - Cache results as DetectResult with TTL
      - Provide latest result to RCA/Orchestrator
      - Mutex on collection to prevent concurrent AWS API storms
    """

    def __init__(self, region: str = "ap-southeast-1", cache_dir: str = DEFAULT_CACHE_DIR):
        self.region = region
        self._cache_dir = Path(cache_dir)
        self._cache: Dict[str, DetectResult] = {}
        self._latest: Optional[DetectResult] = None
        self._collecting = asyncio.Lock()  # R5: collection mutex

        # EventCorrelator — lazy init or injected
        from src.event_correlator import get_correlator
        self._correlator = get_correlator(self.region)

    async def run_detection(
        self,
        services: List[str] = None,
        lookback_minutes: int = 15,
        source: str = "proactive_scan",
        ttl_seconds: int = 300,
    ) -> DetectResult:
        """
        Execute a full detection cycle.

        Collects data via EventCorrelator, runs anomaly detection,
        caches the result, and returns it.

        Thread-safe: only one collection runs at a time (asyncio.Lock).
        """
        async with self._collecting:
            detect_id = f"det-{uuid.uuid4().hex[:12]}"
            now = datetime.now(timezone.utc)
            logger.info(f"[{detect_id}] Starting detection cycle (source={source})")

            try:
                event = await self._correlator.collect(
                    services=services,
                    lookback_minutes=lookback_minutes,
                )

                result = DetectResult(
                    detect_id=detect_id,
                    timestamp=now.isoformat(),
                    source=source,
                    region=self.region,
                    ttl_seconds=ttl_seconds,
                    correlated_event=event,
                    anomalies_detected=event.anomalies if event else [],
                    error=None,
                )

                logger.info(
                    f"[{detect_id}] Detection complete: "
                    f"{len(result.anomalies_detected)} anomalies, "
                    f"{event.duration_ms}ms collection"
                )
            except Exception as e:
                logger.error(f"[{detect_id}] Detection failed: {e}")
                result = DetectResult(
                    detect_id=detect_id,
                    timestamp=now.isoformat(),
                    source=source,
                    region=self.region,
                    ttl_seconds=ttl_seconds,
                    correlated_event=None,
                    anomalies_detected=[],
                    error=str(e),
                )

            # Cache
            self._cache[detect_id] = result
            self._latest = result

            # Persist (with file lock — R5)
            self._persist_result(result)

            return result

    def get_latest(self) -> Optional[DetectResult]:
        """Get the most recent DetectResult (may be stale — caller checks)."""
        return self._latest

    def get_latest_fresh(self) -> Optional[DetectResult]:
        """Get the latest result only if not stale."""
        if self._latest and not self._latest.is_stale:
            return self._latest
        return None

    def get_result(self, detect_id: str) -> Optional[DetectResult]:
        """Get a cached result by detect_id."""
        return self._cache.get(detect_id)

    def health(self) -> Dict[str, Any]:
        """Health check for monitoring / other agents. (R5)"""
        return {
            "status": "collecting" if self._collecting.locked() else "idle",
            "latest_detect_id": self._latest.detect_id if self._latest else None,
            "latest_age_seconds": round(self._latest.age_seconds, 1) if self._latest else None,
            "latest_freshness": self._latest.freshness_label if self._latest else None,
            "cache_size": len(self._cache),
        }

    def _persist_result(self, result: DetectResult):
        """Write DetectResult to disk with file lock (R5: concurrent safety)."""
        try:
            cache_dir = getattr(self, "_cache_dir", None) or Path(DEFAULT_CACHE_DIR)
            cache_dir = Path(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
            path = cache_dir / f"{result.detect_id}.json"

            with open(path, "w") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                json.dump(result.to_dict(), f, indent=2, default=str)
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            logger.debug(f"Persisted DetectResult to {path}")
        except Exception as e:
            logger.warning(f"Failed to persist DetectResult: {e}")


# ── Singleton ── (R5: process-level singleton with async lock)
_detect_agent: Optional[DetectAgent] = None
_singleton_lock = asyncio.Lock()


def get_detect_agent(region: str = "ap-southeast-1") -> DetectAgent:
    """Get or create the singleton DetectAgent (sync version for simple access)."""
    global _detect_agent
    if _detect_agent is None:
        _detect_agent = DetectAgent(region=region)
    return _detect_agent


async def get_detect_agent_async(region: str = "ap-southeast-1") -> DetectAgent:
    """Get or create the singleton DetectAgent (async version with lock)."""
    global _detect_agent
    async with _singleton_lock:
        if _detect_agent is None:
            _detect_agent = DetectAgent(region=region)
        return _detect_agent
