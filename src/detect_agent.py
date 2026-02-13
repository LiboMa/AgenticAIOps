"""
Detect Agent — Step 1 of Closed-Loop Enhancement

Wraps EventCorrelator.collect() with caching, TTL, and concurrency protection.
Does NOT duplicate collection logic — delegates to EventCorrelator.

Design ref: docs/designs/DETECT_AGENT_DATA_REUSE_DESIGN.md
Reviewer feedback: R1 (TTL/freshness), R3 (delegation), R5 (concurrency)
"""

import asyncio
import fcntl
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

from src.event_correlator import (
    CorrelatedEvent,
    EventCorrelator,
    get_correlator,
)

logger = logging.getLogger(__name__)

# Persistence directory
DETECT_CACHE_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'detect_cache')


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class DetectResult:
    """
    Output of a detection run.

    Wraps a CorrelatedEvent with freshness metadata so downstream
    consumers (IncidentOrchestrator) can decide whether to reuse or
    re-collect.
    """

    detect_id: str
    timestamp: str                                   # ISO-8601 UTC
    source: str                                      # "proactive_scan" | "alarm_trigger" | "manual"
    correlated_event: Optional[CorrelatedEvent] = None
    anomalies_detected: List[Dict[str, Any]] = field(default_factory=list)
    pattern_matches: List[Dict[str, Any]] = field(default_factory=list)

    # ── Freshness management (R1) ──
    ttl_seconds: int = 300                           # 5 min, aligned with heartbeat

    # ── Metadata ──
    collection_duration_ms: int = 0
    region: str = "ap-southeast-1"
    error: Optional[str] = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def age_seconds(self) -> float:
        """Seconds since this result was created."""
        ts = datetime.fromisoformat(self.timestamp)
        return (datetime.now(timezone.utc) - ts).total_seconds()

    @property
    def is_stale(self) -> bool:
        """True when data is older than TTL."""
        return self.age_seconds > self.ttl_seconds

    @property
    def freshness_label(self) -> str:
        """Human-readable freshness tag for logging / RCA context."""
        age = self.age_seconds
        if age < 60:
            return "fresh"       # < 1 min
        elif age < self.ttl_seconds:
            return "warm"        # 1-5 min
        return "stale"           # > TTL

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-safe dict (excludes CorrelatedEvent internals)."""
        return {
            "detect_id": self.detect_id,
            "timestamp": self.timestamp,
            "source": self.source,
            "ttl_seconds": self.ttl_seconds,
            "age_seconds": round(self.age_seconds, 1),
            "is_stale": self.is_stale,
            "freshness_label": self.freshness_label,
            "anomalies_detected": self.anomalies_detected,
            "pattern_matches": self.pattern_matches,
            "collection_duration_ms": self.collection_duration_ms,
            "region": self.region,
            "error": self.error,
            "has_correlated_event": self.correlated_event is not None,
        }

    def summary(self) -> str:
        """One-line summary for logs."""
        anomaly_count = len(self.anomalies_detected)
        return (
            f"DetectResult({self.detect_id}) "
            f"[{self.freshness_label}|{self.age_seconds:.0f}s] "
            f"anomalies={anomaly_count} "
            f"collect={self.collection_duration_ms}ms "
            f"source={self.source}"
        )


# =============================================================================
# Detect Agent
# =============================================================================

class DetectAgent:
    """
    Detection layer — owns data collection and caching.

    Delegates actual AWS calls to EventCorrelator (stable, read-only).
    Provides cached DetectResult to IncidentOrchestrator so Stage 1
    can be skipped when fresh data exists.

    Concurrency: asyncio.Lock ensures only one collection runs at a time (R5).
    """

    def __init__(self, region: str = "ap-southeast-1"):
        self.region = region
        self._correlator: EventCorrelator = get_correlator(region)
        self._collecting = asyncio.Lock()            # R5: mutual exclusion
        self._latest: Optional[DetectResult] = None
        self._cache: Dict[str, DetectResult] = {}

        # Ensure persistence dir exists
        os.makedirs(DETECT_CACHE_DIR, exist_ok=True)

    # ------------------------------------------------------------------
    # Core detection
    # ------------------------------------------------------------------

    async def run_detection(
        self,
        source: str = "proactive_scan",
        services: Optional[List[str]] = None,
        lookback_minutes: int = 15,
        ttl_seconds: int = 300,
    ) -> DetectResult:
        """
        Run a detection cycle.

        1. Acquire lock (only one collection at a time).
        2. Delegate to EventCorrelator.collect().
        3. Wrap result in DetectResult with TTL metadata.
        4. Cache and persist.

        Args:
            source: Origin of this detection run.
            services: AWS services to scan (default: ec2, rds, lambda).
            lookback_minutes: How far back to collect.
            ttl_seconds: TTL for this result.

        Returns:
            DetectResult with correlated event and anomalies.
        """
        async with self._collecting:
            detect_id = self._generate_id()
            now = datetime.now(timezone.utc)

            logger.info(f"[{detect_id}] Starting detection (source={source})")

            try:
                # Delegate to EventCorrelator — the ONLY collection path
                event: CorrelatedEvent = await self._correlator.collect(
                    services=services,
                    lookback_minutes=lookback_minutes,
                )

                result = DetectResult(
                    detect_id=detect_id,
                    timestamp=now.isoformat(),
                    source=source,
                    correlated_event=event,
                    anomalies_detected=event.anomalies,
                    ttl_seconds=ttl_seconds,
                    collection_duration_ms=event.duration_ms,
                    region=self.region,
                )

                logger.info(f"[{detect_id}] Detection complete: {result.summary()}")

            except Exception as e:
                logger.error(f"[{detect_id}] Detection failed: {e}")
                result = DetectResult(
                    detect_id=detect_id,
                    timestamp=now.isoformat(),
                    source=source,
                    ttl_seconds=ttl_seconds,
                    region=self.region,
                    error=str(e),
                )

            # Cache
            self._latest = result
            self._cache[detect_id] = result

            # Persist (with file lock — R5)
            self._persist_result(result)

            # Prune old entries
            self._prune_cache()

            return result

    # ------------------------------------------------------------------
    # Cache access
    # ------------------------------------------------------------------

    def get_latest(self) -> Optional[DetectResult]:
        """Return the most recent DetectResult (may be stale)."""
        return self._latest

    def get_latest_fresh(self) -> Optional[DetectResult]:
        """Return latest result only if still within TTL."""
        if self._latest and not self._latest.is_stale:
            return self._latest
        return None

    def get_result(self, detect_id: str) -> Optional[DetectResult]:
        """Lookup a specific result by ID."""
        return self._cache.get(detect_id)

    # ------------------------------------------------------------------
    # Health (R5)
    # ------------------------------------------------------------------

    def health(self) -> Dict[str, Any]:
        """Status snapshot for monitoring."""
        return {
            "status": "collecting" if self._collecting.locked() else "idle",
            "region": self.region,
            "latest_detect_id": self._latest.detect_id if self._latest else None,
            "latest_age_seconds": round(self._latest.age_seconds, 1) if self._latest else None,
            "latest_freshness": self._latest.freshness_label if self._latest else None,
            "latest_is_stale": self._latest.is_stale if self._latest else None,
            "cache_size": len(self._cache),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_id() -> str:
        """Short unique ID for this detection run."""
        now = datetime.now(timezone.utc).isoformat()
        return "det-" + hashlib.sha256(now.encode()).hexdigest()[:12]

    def _persist_result(self, result: DetectResult):
        """Write result to disk with file-level lock (R5)."""
        try:
            path = os.path.join(DETECT_CACHE_DIR, f"{result.detect_id}.json")
            with open(path, 'w') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump(result.to_dict(), f, indent=2, default=str)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            logger.debug(f"Persisted {result.detect_id} to {path}")
        except Exception as e:
            logger.warning(f"Failed to persist {result.detect_id}: {e}")

    def _prune_cache(self, max_entries: int = 50):
        """Remove oldest cached results beyond limit."""
        if len(self._cache) <= max_entries:
            return
        sorted_ids = sorted(
            self._cache.keys(),
            key=lambda k: self._cache[k].timestamp,
        )
        for old_id in sorted_ids[: len(sorted_ids) - max_entries]:
            del self._cache[old_id]


# =============================================================================
# Singleton (R5: asyncio.Lock protected)
# =============================================================================

_detect_agent: Optional[DetectAgent] = None
_init_lock = asyncio.Lock()


async def get_detect_agent(region: str = "ap-southeast-1") -> DetectAgent:
    """Get or create the DetectAgent singleton (async-safe)."""
    global _detect_agent
    async with _init_lock:
        if _detect_agent is None:
            _detect_agent = DetectAgent(region=region)
        return _detect_agent
