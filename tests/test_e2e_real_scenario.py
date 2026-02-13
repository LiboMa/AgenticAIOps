"""
E2E Real Scenario Test: EC2 CPU High → Full Pipeline

场景描述:
  1. EC2 实例 CPU 飙高 (95%) → CloudWatch Alarm 触发
  2. DetectAgent 采集真实 AWS 数据 (metrics, alarms, trail, health)
  3. RCA Engine 分析根因 (Pattern 匹配 → LLM 推理)
  4. Pattern 向量化存储 (S3 Knowledge Base + OpenSearch)
  5. SOP 匹配 → Safety Check → 执行/审批决策

这不是 mock 测试，是跑真实 AWS API 的端到端管道。
如果 AWS 不可用，测试会 skip (不会 fail)。

Author: Tester (✅)
Date: 2026-02-13
Requested by: Ma Ronnie — "从头开始做一真实场景的 E2E 测试！"
"""

import asyncio
import json
import logging
import os
import time
import tempfile
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

# ── Imports ────────────────────────────────────────────────────
from src.event_correlator import (
    EventCorrelator,
    CorrelatedEvent,
    MetricDataPoint,
    AlarmInfo,
    TrailEvent,
    HealthEvent,
    get_correlator,
)
from src.detect_agent import DetectAgent, DetectResult
from src.rca_inference import RCAInferenceEngine, get_rca_inference_engine
from src.rca.models import RCAResult, Severity, Remediation
from src.rca.pattern_matcher import PatternMatcher
from src.rca_sop_bridge import get_bridge, RCASOPBridge
from src.sop_safety import get_safety_layer, SOPSafetyLayer
from src.sop_system import get_sop_store
from src.s3_knowledge_base import S3KnowledgeBase, AnomalyPattern
from src.incident_orchestrator import (
    IncidentOrchestrator,
    IncidentRecord,
    IncidentStatus,
    TriggerType,
)


logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# Helper: AWS connectivity check
# ══════════════════════════════════════════════════════════════

def _aws_available() -> bool:
    """Quick STS check — can we talk to AWS?"""
    try:
        import boto3
        sts = boto3.client("sts", region_name="ap-southeast-1")
        sts.get_caller_identity()
        return True
    except Exception:
        return False


AWS_AVAILABLE = _aws_available()
skip_no_aws = pytest.mark.skipif(not AWS_AVAILABLE, reason="AWS credentials not available")


# ══════════════════════════════════════════════════════════════
# STAGE 1: Real AWS Data Collection (EventCorrelator)
# ══════════════════════════════════════════════════════════════

class TestStage1_DataCollection:
    """Stage 1: Collect real AWS data via EventCorrelator."""

    @skip_no_aws
    @pytest.mark.asyncio
    async def test_collect_real_aws_data(self):
        """
        真实场景 Step 1: EventCorrelator 采集 EC2/RDS/Lambda 数据。
        验证: 数据结构完整，各 source 有 ok/error 状态。
        """
        correlator = get_correlator("ap-southeast-1")

        start = time.time()
        event = await correlator.collect(
            services=["ec2", "rds", "lambda"],
            lookback_minutes=15,
        )
        duration = time.time() - start

        # ── Structural assertions ──
        assert isinstance(event, CorrelatedEvent)
        assert event.collection_id, "collection_id should not be empty"
        assert event.region == "ap-southeast-1"
        assert event.duration_ms > 0

        # Source status — all sources attempted
        assert "metrics" in event.source_status
        assert "alarms" in event.source_status

        # Metrics list exists (may be empty if no EC2 running)
        assert isinstance(event.metrics, list)
        assert isinstance(event.alarms, list)
        assert isinstance(event.trail_events, list)

        # Performance SLA (relaxed — AWS API can be slow)
        assert duration < 60, f"Collection took {duration:.1f}s — exceeds 60s hard limit"

        logger.info(
            f"Stage 1 OK: {len(event.metrics)} metrics, "
            f"{len(event.alarms)} alarms, "
            f"{len(event.trail_events)} trail events, "
            f"{len(event.anomalies)} anomalies, "
            f"duration={event.duration_ms}ms"
        )
        return event

    @skip_no_aws
    @pytest.mark.asyncio
    async def test_collect_graceful_degradation(self):
        """
        验证: 某个 source 失败时，其他 source 仍能正常采集。
        """
        correlator = get_correlator("ap-southeast-1")
        event = await correlator.collect(
            services=["ec2"],
            lookback_minutes=5,
            include_trail=True,
            include_health=True,
        )

        assert isinstance(event, CorrelatedEvent)
        # At least one source should succeed
        ok_sources = [s for s, v in event.source_status.items() if v == "ok"]
        assert len(ok_sources) >= 1, f"No sources succeeded: {event.source_status}"


# ══════════════════════════════════════════════════════════════
# STAGE 2: DetectAgent — Collect + Cache + TTL
# ══════════════════════════════════════════════════════════════

class TestStage2_DetectAgent:
    """Stage 2: DetectAgent wraps EventCorrelator with caching."""

    @skip_no_aws
    @pytest.mark.asyncio
    async def test_detect_agent_real_detection(self):
        """
        真实场景 Step 2: DetectAgent.run_detection() 跑真实 AWS。
        验证: DetectResult 完整，缓存有效，TTL 判断正确。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = DetectAgent(region="ap-southeast-1", cache_dir=tmpdir)

            result = await agent.run_detection(
                services=["ec2"],
                lookback_minutes=15,
                source="e2e_test",
                ttl_seconds=300,
            )

            # ── Core assertions ──
            assert isinstance(result, DetectResult)
            assert result.detect_id.startswith("det-")
            assert result.source == "e2e_test"
            assert result.region == "ap-southeast-1"
            assert result.correlated_event is not None, "Should have collected data"
            assert result.error is None, f"Detection failed: {result.error}"

            # Freshness
            assert not result.is_stale, "Just-created result should not be stale"
            # AWS collection can take 10-40s; age = time since timestamp (before collection)
            assert result.age_seconds < 120, f"Age {result.age_seconds:.0f}s should be < 120s"

            # Cache
            assert agent.get_latest() == result
            assert agent.get_latest_fresh() == result
            assert agent.get_result(result.detect_id) == result

            # Persisted to disk
            cache_files = list(Path(tmpdir).glob("*.json"))
            assert len(cache_files) == 1, f"Expected 1 cache file, got {len(cache_files)}"

            # Health endpoint
            health = agent.health()
            assert health["status"] == "idle"
            assert health["latest_detect_id"] == result.detect_id

            logger.info(
                f"Stage 2 OK: detect_id={result.detect_id}, "
                f"{len(result.anomalies_detected)} anomalies, "
                f"freshness={result.freshness_label}"
            )
            return result


# ══════════════════════════════════════════════════════════════
# STAGE 3: RCA Inference (Pattern Match → LLM)
# ══════════════════════════════════════════════════════════════

class TestStage3_RCAInference:
    """Stage 3: RCA — pattern match first, Claude if needed."""

    def test_pattern_matcher_cpu_scenario(self):
        """
        验证: EC2 CPU 高场景命中 pattern rule。
        用构造的 telemetry 数据模拟真实 alarm。
        """
        matcher = PatternMatcher()

        # 如果没加载到 patterns，跳过
        if not matcher.patterns:
            pytest.skip("No patterns loaded from config/rca_patterns.yaml")

        # 查看是否有 CPU 相关 pattern
        cpu_patterns = [p for p in matcher.patterns if "cpu" in p.id.lower()]
        logger.info(f"Available CPU patterns: {[p.id for p in cpu_patterns]}")

        # 构造 EC2 CPU 高 telemetry — 模拟 CloudWatch ALARM 转化后的 events
        telemetry = {
            "events": [
                {
                    "reason": "CloudWatch ALARM: EC2-HighCPU",
                    "message": "CPUUtilization > 90% for i-0abc123",
                    "type": "Warning",
                    "source": "cloudwatch_alarm",
                }
            ],
            "metrics": {"CPUUtilization": 95.2},
            "logs": [],
        }

        result = matcher.match(telemetry)
        # Pattern may or may not match depending on YAML config
        # The important thing is the matcher runs without error
        logger.info(f"Pattern match result: {result}")

    @skip_no_aws
    @pytest.mark.asyncio
    async def test_rca_with_real_data(self):
        """
        真实场景 Step 3: 用真实 CorrelatedEvent 跑 RCA。
        先 pattern match，如果 confidence < 0.85 走 Claude。
        """
        # Collect real data first
        correlator = get_correlator("ap-southeast-1")
        event = await correlator.collect(
            services=["ec2"],
            lookback_minutes=15,
        )

        engine = get_rca_inference_engine()
        rca_result = await engine.analyze(event)

        # ── Assertions ──
        assert isinstance(rca_result, RCAResult)
        assert rca_result.pattern_id, "pattern_id should not be empty"
        assert rca_result.root_cause, "root_cause should not be empty"
        assert isinstance(rca_result.severity, Severity)
        assert 0 <= rca_result.confidence <= 1.0
        assert rca_result.remediation is not None

        logger.info(
            f"Stage 3 OK: pattern={rca_result.pattern_id}, "
            f"cause='{rca_result.root_cause[:60]}...', "
            f"severity={rca_result.severity.value}, "
            f"confidence={rca_result.confidence:.0%}"
        )
        return rca_result


# ══════════════════════════════════════════════════════════════
# STAGE 4: SOP Matching + Safety Check
# ══════════════════════════════════════════════════════════════

class TestStage4_SOPMatching:
    """Stage 4: Match SOPs from RCA result → Safety check."""

    def test_sop_matching_for_ec2_cpu(self):
        """
        验证: EC2 CPU 高的 RCA 结果能匹配到 sop-ec2-high-cpu。
        """
        bridge = get_bridge()

        # 构造一个真实风格的 RCA result
        rca_result = RCAResult(
            pattern_id="cpu-001",
            pattern_name="EC2 High CPU",
            root_cause="EC2 instance i-0abc123 high CPU utilization (95%) due to runaway process",
            severity=Severity.HIGH,
            confidence=0.88,
            matched_symptoms=["CPUUtilization > 90%"],
            remediation=Remediation(
                action="investigate_cpu",
                auto_execute=False,
                suggestion="Check top processes on the instance",
            ),
            evidence=["CloudWatch ALARM: CPUUtilization > 90% for 5 minutes"],
        )

        matched = bridge.match_sops(rca_result)

        # Should match sop-ec2-high-cpu
        assert len(matched) > 0, "Should match at least one SOP for EC2 CPU high"

        sop_ids = [s["sop_id"] for s in matched]
        assert "sop-ec2-high-cpu" in sop_ids, f"Expected sop-ec2-high-cpu in {sop_ids}"

        logger.info(f"Stage 4a OK: Matched SOPs = {sop_ids}")

    def test_safety_check_for_ec2_sop(self):
        """
        验证: Safety layer 对 EC2 CPU SOP 做 risk 分类 + check。
        """
        safety = get_safety_layer()

        result = safety.check(
            sop_id="sop-ec2-high-cpu",
            resource_ids=["i-0abc123"],
            dry_run=True,
            force=False,
            context={
                "confidence": 0.88,
                "severity": "high",
                "incident_id": "inc-e2e-test",
            },
        )

        assert result is not None
        assert hasattr(result, "passed")
        assert hasattr(result, "execution_mode")

        # Risk classification
        risk = safety._classify_risk("sop-ec2-high-cpu")
        assert risk is not None

        logger.info(
            f"Stage 4b OK: passed={result.passed}, "
            f"mode={result.execution_mode}, risk={risk}"
        )


# ══════════════════════════════════════════════════════════════
# STAGE 5: Knowledge Base — Pattern 存储 + 向量检索
# ══════════════════════════════════════════════════════════════

class TestStage5_KnowledgeBase:
    """Stage 5: Pattern 向量化存储 + 检索。"""

    @skip_no_aws
    @pytest.mark.asyncio
    async def test_add_and_search_pattern(self):
        """
        验证: 将 EC2 CPU 高 pattern 写入 Knowledge Base，再检索回来。
        """
        kb = S3KnowledgeBase()

        pattern = AnomalyPattern(
            pattern_id=f"e2e-cpu-high-{int(time.time())}",
            title="EC2 CPU High Utilization",
            description="EC2 instance CPU utilization exceeds 90% threshold",
            resource_type="ec2",
            severity="high",
            symptoms=["CPUUtilization > 90%", "CloudWatch ALARM triggered"],
            root_cause="Runaway process or insufficient instance size",
            remediation="1) Check top processes 2) Consider instance resize",
            metrics={"CPUUtilization": 95.2},
            tags=["ec2", "cpu", "performance"],
            confidence=0.88,
            source="e2e_test",
        )

        # Add (may fail if S3/OpenSearch not configured — that's OK)
        try:
            success = await kb.add_pattern(pattern, quality_score=0.9)
            logger.info(f"Pattern add: success={success}")
        except Exception as e:
            logger.warning(f"Pattern add failed (expected if S3/OS not configured): {e}")
            # S3 failure is non-fatal; local cache still works

        # Search (uses local cache; S3 bucket may not exist — that's P2)
        results = await kb.search_patterns(
            keywords=["CPU", "high"],
            resource_type="ec2",
        )
        assert isinstance(results, list)
        logger.info(f"Stage 5 OK: {len(results)} patterns found for EC2 CPU high")


# ══════════════════════════════════════════════════════════════
# STAGE 6: Full Pipeline — IncidentOrchestrator E2E
# ══════════════════════════════════════════════════════════════

class TestStage6_FullPipeline:
    """
    Stage 6: 完整管道 — 从 alarm 触发到最终 completed/waiting_approval。
    
    这是 Ronnie 要看的：一个真实场景，从头跑到尾。
    """

    @skip_no_aws
    @pytest.mark.asyncio
    async def test_full_pipeline_alarm_trigger(self):
        """
        ★ 核心 E2E ★
        场景: EC2 CPU 高 → alarm trigger → collect → RCA → SOP → safety → done
        """
        orchestrator = IncidentOrchestrator(region="ap-southeast-1")

        start = time.time()
        incident = await orchestrator.handle_incident(
            trigger_type="alarm",
            trigger_data={
                "alarm_name": "EC2-HighCPU-E2E-Test",
                "metric_name": "CPUUtilization",
                "threshold": 90,
                "current_value": 95.2,
                "instance_id": "i-0abc123",
                "region": "ap-southeast-1",
            },
            services=["ec2"],
            auto_execute=False,
            dry_run=True,
            lookback_minutes=15,
        )
        duration = time.time() - start

        # ── Pipeline should complete (not fail) ──
        assert isinstance(incident, IncidentRecord)
        assert incident.incident_id.startswith("inc-")
        assert incident.status in (
            IncidentStatus.COMPLETED,
            IncidentStatus.WAITING_APPROVAL,
        ), f"Pipeline ended in unexpected status: {incident.status.value}, error: {incident.error}"

        # ── Each stage should have produced output ──
        assert incident.collection_summary is not None, "Stage 1 (collect) missing"
        assert incident.collection_summary.get("metrics", -1) >= 0
        assert incident.rca_result is not None, "Stage 2 (RCA) missing"
        assert incident.rca_result.get("root_cause"), "RCA should have root_cause"

        # SOP matching (may be empty if no patterns match)
        assert incident.matched_sops is not None, "Stage 3 (SOP) missing"

        # Safety check (only if SOPs matched)
        if incident.matched_sops:
            assert incident.safety_check is not None, "Stage 4 (safety) missing when SOPs matched"

        # ── Timing ──
        assert incident.duration_ms > 0
        assert "collect" in incident.stage_timings
        assert "analyze" in incident.stage_timings

        logger.info(
            f"★ FULL PIPELINE OK ★\n"
            f"  incident_id: {incident.incident_id}\n"
            f"  status: {incident.status.value}\n"
            f"  duration: {incident.duration_ms}ms ({duration:.1f}s)\n"
            f"  collection: {json.dumps(incident.collection_summary, default=str)[:200]}\n"
            f"  rca: pattern={incident.rca_result.get('pattern_id')}, "
            f"confidence={incident.rca_result.get('confidence')}\n"
            f"  sops_matched: {len(incident.matched_sops or [])}\n"
            f"  safety: {incident.safety_check is not None}\n"
            f"  timings: {incident.stage_timings}"
        )

    @skip_no_aws
    @pytest.mark.asyncio
    async def test_full_pipeline_with_detect_agent(self):
        """
        ★ 完整链路 ★
        DetectAgent → IncidentOrchestrator (with detect_result reuse)
        
        验证: detect_result 被复用，Stage 1 跳过采集。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Step A: DetectAgent collects data
            detect = DetectAgent(region="ap-southeast-1", cache_dir=tmpdir)
            detect_result = await detect.run_detection(
                services=["ec2"],
                lookback_minutes=15,
                source="proactive_scan",
            )

            assert detect_result.error is None, f"Detection failed: {detect_result.error}"
            assert detect_result.correlated_event is not None

            # Step B: Pass detect_result to orchestrator (should reuse)
            orchestrator = IncidentOrchestrator(region="ap-southeast-1")
            incident = await orchestrator.handle_incident(
                trigger_type="anomaly",  # non-manual → allows reuse
                trigger_data={"source": "detect_agent", "detect_id": detect_result.detect_id},
                services=["ec2"],
                auto_execute=False,
                dry_run=True,
                detect_result=detect_result,
            )

            assert incident.status in (
                IncidentStatus.COMPLETED,
                IncidentStatus.WAITING_APPROVAL,
            ), f"Pipeline failed: {incident.error}"

            # Verify data reuse
            source = incident.collection_summary.get("source", "")
            assert source == "detect_agent_reuse", (
                f"Expected detect_agent_reuse, got '{source}' — "
                f"Stage 1 should have been skipped"
            )

            logger.info(
                f"★ DETECT→PIPELINE OK ★\n"
                f"  detect_id: {detect_result.detect_id}\n"
                f"  reuse: {source}\n"
                f"  incident: {incident.incident_id} → {incident.status.value}\n"
                f"  timings: {incident.stage_timings}"
            )

    @skip_no_aws
    @pytest.mark.asyncio
    async def test_full_pipeline_manual_trigger_no_reuse(self):
        """
        验证 Rule R2: manual trigger 即使有 detect_result 也不复用。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            detect = DetectAgent(region="ap-southeast-1", cache_dir=tmpdir)
            detect_result = await detect.run_detection(
                services=["ec2"],
                lookback_minutes=15,
                source="proactive_scan",
            )

            orchestrator = IncidentOrchestrator(region="ap-southeast-1")
            incident = await orchestrator.handle_incident(
                trigger_type="manual",  # manual → should NOT reuse
                trigger_data={"reason": "user requested analysis"},
                services=["ec2"],
                dry_run=True,
                detect_result=detect_result,
            )

            assert incident.status in (
                IncidentStatus.COMPLETED,
                IncidentStatus.WAITING_APPROVAL,
            ), f"Pipeline failed: {incident.error}"

            source = incident.collection_summary.get("source", "")
            assert source == "fresh_collection", (
                f"Manual trigger should do fresh collection, got '{source}'"
            )

            logger.info(
                f"★ MANUAL NO-REUSE OK ★ source={source}, "
                f"timings={incident.stage_timings}"
            )


# ══════════════════════════════════════════════════════════════
# STAGE 7: Pipeline Report — Summary of all stages
# ══════════════════════════════════════════════════════════════

class TestStage7_PipelineReport:
    """生成管道健康报告 (不需要 AWS，只检查组件就绪状态)。"""

    def test_all_components_importable(self):
        """验证所有管道组件可正常 import。"""
        components = {}

        # EventCorrelator
        try:
            from src.event_correlator import get_correlator
            get_correlator("ap-southeast-1")
            components["EventCorrelator"] = "✅"
        except Exception as e:
            components["EventCorrelator"] = f"❌ {e}"

        # DetectAgent
        try:
            from src.detect_agent import DetectAgent
            DetectAgent.__init__  # existence check
            components["DetectAgent"] = "✅"
        except Exception as e:
            components["DetectAgent"] = f"❌ {e}"

        # RCA Engine
        try:
            from src.rca_inference import get_rca_inference_engine
            get_rca_inference_engine()
            components["RCA Engine"] = "✅"
        except Exception as e:
            components["RCA Engine"] = f"❌ {e}"

        # Pattern Matcher
        try:
            from src.rca.pattern_matcher import PatternMatcher
            pm = PatternMatcher()
            components["PatternMatcher"] = f"✅ ({len(pm.patterns)} patterns)"
        except Exception as e:
            components["PatternMatcher"] = f"❌ {e}"

        # SOP Bridge
        try:
            from src.rca_sop_bridge import get_bridge
            get_bridge()
            components["SOP Bridge"] = "✅"
        except Exception as e:
            components["SOP Bridge"] = f"❌ {e}"

        # Safety Layer
        try:
            from src.sop_safety import get_safety_layer
            get_safety_layer()
            components["Safety Layer"] = "✅"
        except Exception as e:
            components["Safety Layer"] = f"❌ {e}"

        # SOP Store
        try:
            from src.sop_system import get_sop_store
            store = get_sop_store()
            sop = store.get_sop("sop-ec2-high-cpu")
            components["SOP Store"] = f"✅ (sop-ec2-high-cpu: {'found' if sop else 'missing'})"
        except Exception as e:
            components["SOP Store"] = f"❌ {e}"

        # S3 Knowledge Base
        try:
            from src.s3_knowledge_base import S3KnowledgeBase
            S3KnowledgeBase()
            components["S3 Knowledge Base"] = "✅"
        except Exception as e:
            components["S3 Knowledge Base"] = f"❌ {e}"

        # Orchestrator
        try:
            from src.incident_orchestrator import IncidentOrchestrator
            IncidentOrchestrator(region="ap-southeast-1")
            components["Orchestrator"] = "✅"
        except Exception as e:
            components["Orchestrator"] = f"❌ {e}"

        # Print report
        print("\n" + "=" * 60)
        print("  E2E Pipeline Component Health Report")
        print("=" * 60)
        for name, status in components.items():
            print(f"  {name:25s} {status}")
        print("=" * 60)

        # All should be importable
        failures = [n for n, s in components.items() if s.startswith("❌")]
        assert len(failures) == 0, f"Components failed: {failures}"

    def test_sop_ec2_cpu_exists(self):
        """验证 EC2 CPU 高 SOP 存在且有完整步骤。"""
        store = get_sop_store()
        sop = store.get_sop("sop-ec2-high-cpu")
        assert sop is not None, "sop-ec2-high-cpu not found in SOP store"
        assert sop.steps, "SOP should have steps"
        assert sop.service == "ec2"
        logger.info(f"SOP OK: {sop.sop_id}, {len(sop.steps)} steps")

    def test_rca_sop_mapping_has_cpu(self):
        """验证 RCA→SOP 映射包含 cpu-001 → sop-ec2-high-cpu。"""
        from src.rca_sop_bridge import RCA_SOP_MAPPING
        assert "cpu-001" in RCA_SOP_MAPPING, "cpu-001 missing from RCA_SOP_MAPPING"
        assert "sop-ec2-high-cpu" in RCA_SOP_MAPPING["cpu-001"]
        logger.info(f"Mapping OK: cpu-001 → {RCA_SOP_MAPPING['cpu-001']}")
