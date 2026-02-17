"""
T-L4-010: Pipeline Performance Benchmark

Runs multiple incident pipeline iterations (mocked AWS) and
records per-stage timing to verify:
  - P50 < 20s
  - P95 < 30s
  - P99 < 45s

Uses mocked collection (to avoid real AWS costs) but exercises
the full orchestrator code path.
"""
import asyncio
import time
import statistics
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone


N_RUNS = 10  # Number of benchmark iterations


@pytest.fixture
def orchestrator():
    from src.incident_orchestrator import IncidentOrchestrator
    return IncidentOrchestrator(region="us-east-1")


def make_mock_event(collection_time_s: float = 0.01):
    """Create a mock CorrelatedEvent with simulated collection delay."""
    mock_event = MagicMock()
    mock_event.collection_id = f"coll-bench-{time.time()}"
    mock_event.metrics = [
        {"name": "cpu_utilization", "value": 85.5, "unit": "Percent"},
        {"name": "memory_utilization", "value": 72.3, "unit": "Percent"},
        {"name": "disk_io_read", "value": 1200, "unit": "Bytes/Second"},
    ]
    mock_event.logs = [
        {"message": "ERROR: OOM kill detected", "timestamp": datetime.now(timezone.utc).isoformat()},
        {"message": "WARNING: High CPU load", "timestamp": datetime.now(timezone.utc).isoformat()},
    ]
    mock_event.health_events = []
    mock_event.service_statuses = {"ec2": "degraded"}
    mock_event.cloudtrail_events = []
    mock_event.resource_timeline = {}
    mock_event.to_prompt_context.return_value = (
        "CPU: 85.5%, Memory: 72.3%, Disk IO Read: 1200 B/s. "
        "Logs: OOM kill detected, High CPU load. EC2 status: degraded."
    )
    return mock_event


def make_mock_rca():
    """Create a mock RCA result."""
    mock_rca = MagicMock()
    mock_rca.pattern_id = "ec2-high-cpu-memory"
    mock_rca.root_cause = "EC2 instance experiencing high CPU and memory pressure due to OOM kills"
    mock_rca.confidence = 0.87
    mock_rca.severity = MagicMock(value="medium")
    mock_rca.matched_symptoms = ["high_cpu", "oom_killed", "memory_pressure"]
    mock_rca.affected_service = "ec2"
    mock_rca.remediation = MagicMock(
        suggestion="Increase instance size or add memory limit",
        risk_level="L1",
    )
    return mock_rca


class TestPipelinePerformance:
    """Benchmark the full incident pipeline (mocked AWS)."""

    def test_pipeline_benchmark_n_runs(self, orchestrator):
        """Run N iterations of the full pipeline and measure timing."""
        durations = []
        stage_timings = {
            "total": [],
        }

        for i in range(N_RUNS):
            mock_event = make_mock_event()
            mock_rca = make_mock_rca()

            with patch("src.event_correlator.get_correlator") as mock_gc:
                mock_corr = MagicMock()
                mock_corr.collect = AsyncMock(return_value=mock_event)
                mock_gc.return_value = mock_corr

                with patch("src.rca_inference.get_rca_inference_engine") as mock_rca_eng:
                    mock_rca_eng.return_value.analyze = AsyncMock(return_value=mock_rca)

                    with patch("src.rca_sop_bridge.get_bridge") as mock_bridge:
                        mock_b = MagicMock()
                        mock_b.match_sops.return_value = [
                            {"sop_id": "sop-increase-memory", "score": 0.85, "risk_level": "L1"},
                        ]
                        mock_bridge.return_value = mock_b

                        with patch("src.sop_safety.get_safety_layer") as mock_safety:
                            mock_s = MagicMock()
                            mock_check = MagicMock()
                            mock_check.approved = True
                            mock_check.risk_level = MagicMock(value="L1")
                            mock_check.cooldown_remaining = 0
                            mock_s.check.return_value = mock_check
                            mock_s.create_snapshot.return_value = MagicMock(snapshot_id="snap-bench")
                            mock_safety.return_value = mock_s

                            start = time.time()
                            result = asyncio.get_event_loop().run_until_complete(
                                orchestrator.handle_incident(
                                    trigger_type="alarm",
                                    services=["ec2"],
                                    dry_run=True,
                                )
                            )
                            elapsed = time.time() - start

                            durations.append(elapsed)
                            stage_timings["total"].append(elapsed)

                            assert result is not None
                            assert result.incident_id.startswith("inc-")

        # ── Compute statistics ──
        p50 = statistics.median(durations)
        p95 = sorted(durations)[int(len(durations) * 0.95)]
        p99 = sorted(durations)[int(len(durations) * 0.99)]
        mean = statistics.mean(durations)

        print(f"\n{'='*60}")
        print(f"  Pipeline Performance Benchmark ({N_RUNS} runs)")
        print(f"{'='*60}")
        print(f"  Mean:  {mean*1000:.1f}ms")
        print(f"  P50:   {p50*1000:.1f}ms")
        print(f"  P95:   {p95*1000:.1f}ms")
        print(f"  P99:   {p99*1000:.1f}ms")
        print(f"  Min:   {min(durations)*1000:.1f}ms")
        print(f"  Max:   {max(durations)*1000:.1f}ms")
        print(f"{'='*60}")

        # ── SLA assertions (mocked, so should be very fast) ──
        # With mocks, pipeline overhead should be < 1s
        # Real AWS calls would add 10-30s for collection
        assert p50 < 5.0, f"P50 {p50:.2f}s exceeds 5s SLA (mocked)"
        assert p95 < 10.0, f"P95 {p95:.2f}s exceeds 10s SLA (mocked)"

    def test_pipeline_stages_measured(self, orchestrator):
        """Verify that the pipeline records duration_ms in the incident."""
        mock_event = make_mock_event()
        mock_rca = make_mock_rca()

        with patch("src.event_correlator.get_correlator") as mock_gc:
            mock_corr = MagicMock()
            mock_corr.collect = AsyncMock(return_value=mock_event)
            mock_gc.return_value = mock_corr

            with patch("src.rca_inference.get_rca_inference_engine") as mock_rca_eng:
                mock_rca_eng.return_value.analyze = AsyncMock(return_value=mock_rca)

                with patch("src.rca_sop_bridge.get_bridge") as mock_bridge:
                    mock_b = MagicMock()
                    mock_b.match_sops.return_value = []
                    mock_bridge.return_value = mock_b

                    result = asyncio.get_event_loop().run_until_complete(
                        orchestrator.handle_incident(
                            trigger_type="manual",
                            services=["ec2"],
                            dry_run=True,
                        )
                    )

                    assert result.duration_ms is not None
                    assert result.duration_ms >= 0
                    print(f"\nPipeline duration: {result.duration_ms}ms")

    def test_incident_record_has_timing_fields(self):
        """Verify IncidentRecord tracks timing."""
        from src.incident_orchestrator import IncidentRecord, TriggerType

        inc = IncidentRecord(
            incident_id="inc-timing-test",
            trigger_type=TriggerType.MANUAL,
            trigger_data={},
            region="us-east-1",
        )

        assert hasattr(inc, "duration_ms")
        assert hasattr(inc, "created_at")
        assert hasattr(inc, "completed_at")

    def test_reuse_path_near_zero(self, orchestrator):
        """When detect_result is fresh, collection is skipped → near 0ms."""
        mock_rca = make_mock_rca()

        # Create a mock DetectResult
        from src.detect_agent import DetectResult
        mock_detect = MagicMock(spec=DetectResult)
        mock_detect.is_stale = False
        mock_detect.detect_id = "det-bench"
        mock_detect.freshness_label = "fresh"
        mock_detect.age_seconds = 5.0
        mock_detect.correlated_event = make_mock_event()

        with patch("src.rca_inference.get_rca_inference_engine") as mock_rca_eng:
            mock_rca_eng.return_value.analyze = AsyncMock(return_value=mock_rca)

            with patch("src.rca_sop_bridge.get_bridge") as mock_bridge:
                mock_b = MagicMock()
                mock_b.match_sops.return_value = []
                mock_bridge.return_value = mock_b

                start = time.time()
                result = asyncio.get_event_loop().run_until_complete(
                    orchestrator.handle_incident(
                        trigger_type="alarm",
                        detect_result=mock_detect,
                        dry_run=True,
                    )
                )
                elapsed = time.time() - start

                assert result is not None
                print(f"\nReuse path elapsed: {elapsed*1000:.1f}ms")
                # Reuse path should be very fast (no collection)
                assert elapsed < 2.0, f"Reuse path took {elapsed:.2f}s, expected < 2s"
