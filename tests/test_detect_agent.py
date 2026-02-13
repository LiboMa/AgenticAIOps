"""
Tests for DetectAgent — Step 1 delivery.

Covers:
- DetectResult TTL / is_stale / freshness_label (R1)
- DetectAgent.run_detection() delegates to EventCorrelator (R3)
- Singleton + asyncio.Lock concurrency (R5)
- Cache and persistence
- Health endpoint
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure project root on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.detect_agent import DetectAgent, DetectResult, get_detect_agent, DETECT_CACHE_DIR
from src.event_correlator import CorrelatedEvent


# =============================================================================
# Fixtures
# =============================================================================

def _make_correlated_event(**overrides) -> CorrelatedEvent:
    """Factory for a minimal CorrelatedEvent."""
    defaults = dict(
        collection_id="test-collect-001",
        timestamp=datetime.now(timezone.utc).isoformat(),
        duration_ms=1200,
        region="ap-southeast-1",
        metrics=[],
        alarms=[],
        trail_events=[],
        health_events=[],
        source_status={"metrics": "ok", "alarms": "ok"},
        anomalies=[
            {"resource": "i-abc123", "metric": "CPUUtilization", "value": 95, "severity": "critical"},
        ],
        recent_changes=[],
    )
    defaults.update(overrides)
    return CorrelatedEvent(**defaults)


def _make_detect_result(age_seconds: float = 0, ttl_seconds: int = 300, **overrides) -> DetectResult:
    """Factory for DetectResult with controllable age."""
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    defaults = dict(
        detect_id="det-test001",
        timestamp=ts.isoformat(),
        source="proactive_scan",
        ttl_seconds=ttl_seconds,
        region="ap-southeast-1",
    )
    defaults.update(overrides)
    return DetectResult(**defaults)


# =============================================================================
# DetectResult — TTL / freshness (R1)
# =============================================================================

class TestDetectResult:
    """Tests for DetectResult dataclass properties."""

    def test_fresh_result(self):
        """Result created just now should be fresh and not stale."""
        r = _make_detect_result(age_seconds=0)
        assert not r.is_stale
        assert r.freshness_label == "fresh"
        assert r.age_seconds < 5  # allow small delta

    def test_warm_result(self):
        """Result aged 120s with 300s TTL should be warm."""
        r = _make_detect_result(age_seconds=120, ttl_seconds=300)
        assert not r.is_stale
        assert r.freshness_label == "warm"

    def test_stale_result(self):
        """Result older than TTL should be stale."""
        r = _make_detect_result(age_seconds=600, ttl_seconds=300)
        assert r.is_stale
        assert r.freshness_label == "stale"

    def test_boundary_fresh_warm(self):
        """Result at exactly 59s should be fresh."""
        r = _make_detect_result(age_seconds=59, ttl_seconds=300)
        assert r.freshness_label == "fresh"

    def test_boundary_warm_stale(self):
        """Result at exactly TTL+1 should be stale."""
        r = _make_detect_result(age_seconds=301, ttl_seconds=300)
        assert r.is_stale
        assert r.freshness_label == "stale"

    def test_custom_ttl(self):
        """Custom TTL should be respected."""
        r = _make_detect_result(age_seconds=90, ttl_seconds=120)
        assert not r.is_stale
        assert r.freshness_label == "warm"  # 90s > 60s boundary, < 120s TTL

        r2 = _make_detect_result(age_seconds=121, ttl_seconds=120)
        assert r2.is_stale

    def test_to_dict_contains_freshness(self):
        """Serialized dict should include freshness metadata."""
        r = _make_detect_result(age_seconds=30)
        d = r.to_dict()
        assert "freshness_label" in d
        assert "is_stale" in d
        assert "age_seconds" in d
        assert d["freshness_label"] == "fresh"
        assert d["is_stale"] is False

    def test_summary_string(self):
        """Summary should be a readable one-liner."""
        r = _make_detect_result(age_seconds=10, anomalies_detected=[{"x": 1}])
        s = r.summary()
        assert "DetectResult" in s
        assert "fresh" in s
        assert "anomalies=1" in s

    def test_detect_result_with_error(self):
        """Error result should serialize cleanly."""
        r = _make_detect_result(error="boto3 timeout")
        d = r.to_dict()
        assert d["error"] == "boto3 timeout"
        assert d["has_correlated_event"] is False


# =============================================================================
# DetectAgent — run_detection (R3: delegates to EventCorrelator)
# =============================================================================

class TestDetectAgent:
    """Tests for DetectAgent core logic."""

    @pytest.fixture
    def mock_correlator(self):
        """Mock EventCorrelator with async collect()."""
        correlator = MagicMock()
        event = _make_correlated_event()
        correlator.collect = AsyncMock(return_value=event)
        return correlator

    @pytest.fixture
    def agent(self, mock_correlator):
        """DetectAgent with mocked correlator."""
        a = DetectAgent.__new__(DetectAgent)
        a.region = "ap-southeast-1"
        a._correlator = mock_correlator
        a._collecting = asyncio.Lock()
        a._latest = None
        a._cache = {}
        os.makedirs(DETECT_CACHE_DIR, exist_ok=True)
        return a

    @pytest.mark.asyncio
    async def test_run_detection_delegates(self, agent, mock_correlator):
        """run_detection must call EventCorrelator.collect(), not reimplement."""
        result = await agent.run_detection(source="proactive_scan")

        mock_correlator.collect.assert_called_once()
        assert result.correlated_event is not None
        assert result.source == "proactive_scan"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_run_detection_passes_params(self, agent, mock_correlator):
        """Services and lookback should be forwarded to correlator."""
        await agent.run_detection(
            services=["ec2", "rds"],
            lookback_minutes=30,
        )

        mock_correlator.collect.assert_called_once_with(
            services=["ec2", "rds"],
            lookback_minutes=30,
        )

    @pytest.mark.asyncio
    async def test_run_detection_captures_anomalies(self, agent):
        """Anomalies from CorrelatedEvent should propagate to DetectResult."""
        result = await agent.run_detection()
        assert len(result.anomalies_detected) == 1
        assert result.anomalies_detected[0]["resource"] == "i-abc123"

    @pytest.mark.asyncio
    async def test_run_detection_caches_result(self, agent):
        """Result should be cached as latest and by ID."""
        result = await agent.run_detection()

        assert agent._latest is result
        assert agent._cache[result.detect_id] is result

    @pytest.mark.asyncio
    async def test_run_detection_persists_to_disk(self, agent):
        """Result JSON should be written to detect_cache dir."""
        result = await agent.run_detection()

        path = os.path.join(DETECT_CACHE_DIR, f"{result.detect_id}.json")
        assert os.path.exists(path)

        with open(path) as f:
            data = json.load(f)
        assert data["detect_id"] == result.detect_id
        assert data["has_correlated_event"] is True

    @pytest.mark.asyncio
    async def test_run_detection_handles_error(self, agent, mock_correlator):
        """If correlator raises, result should capture the error."""
        mock_correlator.collect = AsyncMock(side_effect=Exception("AWS timeout"))

        result = await agent.run_detection()

        assert result.error == "AWS timeout"
        assert result.correlated_event is None
        assert agent._latest is result  # still cached

    @pytest.mark.asyncio
    async def test_custom_ttl(self, agent):
        """TTL parameter should be set on the result."""
        result = await agent.run_detection(ttl_seconds=120)
        assert result.ttl_seconds == 120


# =============================================================================
# Cache access
# =============================================================================

class TestDetectAgentCache:

    @pytest.fixture
    def agent_with_results(self):
        """Agent pre-loaded with a fresh and a stale result."""
        a = DetectAgent.__new__(DetectAgent)
        a.region = "ap-southeast-1"
        a._correlator = MagicMock()
        a._collecting = asyncio.Lock()
        a._cache = {}

        fresh = _make_detect_result(age_seconds=30, detect_id="det-fresh")
        stale = _make_detect_result(age_seconds=600, detect_id="det-stale", ttl_seconds=300)

        a._latest = fresh
        a._cache["det-fresh"] = fresh
        a._cache["det-stale"] = stale
        return a

    def test_get_latest(self, agent_with_results):
        r = agent_with_results.get_latest()
        assert r is not None
        assert r.detect_id == "det-fresh"

    def test_get_latest_fresh_returns_fresh(self, agent_with_results):
        r = agent_with_results.get_latest_fresh()
        assert r is not None
        assert r.detect_id == "det-fresh"

    def test_get_latest_fresh_returns_none_when_stale(self):
        a = DetectAgent.__new__(DetectAgent)
        a._latest = _make_detect_result(age_seconds=600, ttl_seconds=300)
        assert a.get_latest_fresh() is None

    def test_get_result_by_id(self, agent_with_results):
        r = agent_with_results.get_result("det-stale")
        assert r is not None
        assert r.detect_id == "det-stale"

    def test_get_result_missing(self, agent_with_results):
        assert agent_with_results.get_result("det-nonexist") is None


# =============================================================================
# Concurrency (R5)
# =============================================================================

class TestConcurrency:

    @pytest.mark.asyncio
    async def test_concurrent_detections_serialized(self):
        """Two concurrent run_detection() calls must not overlap."""
        agent = DetectAgent.__new__(DetectAgent)
        agent.region = "ap-southeast-1"
        agent._collecting = asyncio.Lock()
        agent._latest = None
        agent._cache = {}
        os.makedirs(DETECT_CACHE_DIR, exist_ok=True)

        call_order = []

        async def slow_collect(**kwargs):
            call_order.append("start")
            await asyncio.sleep(0.1)
            call_order.append("end")
            return _make_correlated_event()

        correlator = MagicMock()
        correlator.collect = slow_collect
        agent._correlator = correlator

        # Launch two concurrent detections
        await asyncio.gather(
            agent.run_detection(source="a"),
            agent.run_detection(source="b"),
        )

        # Should be serialized: start-end-start-end, not start-start-end-end
        assert call_order == ["start", "end", "start", "end"]


# =============================================================================
# Health (R5)
# =============================================================================

class TestHealth:

    def test_health_no_results(self):
        a = DetectAgent.__new__(DetectAgent)
        a.region = "ap-southeast-1"
        a._collecting = asyncio.Lock()
        a._latest = None
        a._cache = {}

        h = a.health()
        assert h["status"] == "idle"
        assert h["latest_detect_id"] is None
        assert h["cache_size"] == 0

    def test_health_with_result(self):
        a = DetectAgent.__new__(DetectAgent)
        a.region = "ap-southeast-1"
        a._collecting = asyncio.Lock()
        a._cache = {"det-x": _make_detect_result(detect_id="det-x")}
        a._latest = a._cache["det-x"]

        h = a.health()
        assert h["status"] == "idle"
        assert h["latest_detect_id"] == "det-x"
        assert h["cache_size"] == 1
        assert h["latest_freshness"] == "fresh"


# =============================================================================
# Singleton
# =============================================================================

class TestSingleton:

    @pytest.mark.asyncio
    async def test_singleton_returns_same_instance(self):
        """get_detect_agent should return the same instance."""
        import src.detect_agent as mod
        mod._detect_agent = None  # reset

        with patch.object(DetectAgent, '__init__', return_value=None) as mock_init:
            mock_init.return_value = None
            # Patch to avoid real AWS init
            a1 = DetectAgent.__new__(DetectAgent)
            a1.region = "ap-southeast-1"
            a1._correlator = MagicMock()
            a1._collecting = asyncio.Lock()
            a1._latest = None
            a1._cache = {}

            mod._detect_agent = a1

            result1 = await get_detect_agent()
            result2 = await get_detect_agent()

            assert result1 is result2

        mod._detect_agent = None  # cleanup
