#!/usr/bin/env python3
"""
E2E Manual Walkthrough — 用现有代码手动串一遍完整 pipeline

场景: EC2 CPU 高 → 数据采集 → 事件关联 → RCA 分析 → SOP 匹配 → Safety Check

每一步都跑，哪步断了就报出来。
"""

import asyncio
import json
import sys
import time
import traceback
sys.path.insert(0, '.')

PASS = "✅"
FAIL = "❌"
SKIP = "⏭️"
results = []

def report(stage, name, ok, detail=""):
    status = PASS if ok else FAIL
    results.append((stage, name, ok, detail))
    print(f"\n{status} Stage {stage}: {name}", flush=True)
    if detail:
        print(f"   {detail}", flush=True)


async def main():
    t0 = time.time()

    # ── Stage 1: EventCorrelator — 采集真实 AWS 数据 ──────────────
    print("\n" + "="*60, flush=True)
    print("Stage 1: EventCorrelator — Collect real AWS data", flush=True)
    print("="*60, flush=True)
    correlated_event = None
    try:
        from src.event_correlator import EventCorrelator
        correlator = EventCorrelator()
        correlated_event = await correlator.collect(
            services=['ec2', 'rds', 'lambda'],
            lookback_minutes=15,
        )
        report(1, "EventCorrelator.collect()",
               True,
               f"metrics={len(correlated_event.metrics)} "
               f"alarms={len(correlated_event.alarms)} "
               f"trail={len(correlated_event.trail_events)} "
               f"health={len(correlated_event.health_events)} "
               f"anomalies={len(correlated_event.anomalies)} "
               f"region={correlated_event.region}")
    except Exception as e:
        report(1, "EventCorrelator.collect()", False, str(e))
        traceback.print_exc()

    # ── Stage 2: DetectAgent — 封装为 DetectResult ────────────────
    print("\n" + "="*60, flush=True)
    print("Stage 2: DetectAgent — Wrap as DetectResult", flush=True)
    print("="*60, flush=True)
    detect_result = None
    try:
        from src.detect_agent import DetectAgent, DetectResult
        agent = DetectAgent()
        detect_result = await agent.run_detection(services=['ec2', 'rds', 'lambda'])
        report(2, "DetectAgent.run_detection()",
               detect_result is not None,
               f"detect_id={detect_result.detect_id} "
               f"anomalies={len(detect_result.anomalies_detected)} "
               f"source={detect_result.source}")
    except Exception as e:
        report(2, "DetectAgent.run_detection()", False, str(e))
        traceback.print_exc()
        # Fallback: construct DetectResult manually from Stage 1
        if correlated_event:
            print("   ↳ Building DetectResult manually from Stage 1 data...", flush=True)
            import uuid
            from datetime import datetime, timezone
            detect_result = DetectResult(
                detect_id=f"det-manual-{uuid.uuid4().hex[:8]}",
                timestamp=datetime.now(timezone.utc).isoformat(),
                source="manual_e2e",
                correlated_event=correlated_event,
                anomalies_detected=correlated_event.anomalies,
            )
            print(f"   ↳ Manual DetectResult created: {detect_result.detect_id}", flush=True)

    # ── Stage 3: RCA Inference — 分析根因 ────────────────────────
    print("\n" + "="*60, flush=True)
    print("Stage 3: RCA Inference — Analyze root cause", flush=True)
    print("="*60, flush=True)
    rca_result = None
    try:
        from src.rca_inference import RCAInferenceEngine, get_rca_inference_engine
        engine = get_rca_inference_engine()

        # Feed correlated event data to RCA
        event_data = correlated_event if correlated_event else (
            detect_result.correlated_event if detect_result else None
        )
        if event_data:
            rca_result = await engine.analyze(event_data)
            report(3, "RCAInferenceEngine.analyze()",
                   rca_result is not None,
                   f"root_cause={getattr(rca_result, 'root_cause', 'N/A')[:80]} "
                   f"severity={getattr(rca_result, 'severity', 'N/A')} "
                   f"confidence={getattr(rca_result, 'confidence', 'N/A')}")
        else:
            report(3, "RCAInferenceEngine.analyze()", False, "No event data from previous stages")
    except Exception as e:
        report(3, "RCAInferenceEngine.analyze()", False, str(e))
        traceback.print_exc()

    # ── Stage 4: SOP Matching — 匹配 SOP ─────────────────────────
    print("\n" + "="*60, flush=True)
    print("Stage 4: SOP Matching via RCA-SOP Bridge", flush=True)
    print("="*60, flush=True)
    matched_sops = None
    try:
        from src.rca_sop_bridge import get_bridge
        bridge = get_bridge()
        if rca_result:
            matched_sops = bridge.match_sops(rca_result)
            report(4, "RCA-SOP Bridge.match_sops()",
                   True,
                   f"matched_sops={len(matched_sops) if matched_sops else 0}")
        else:
            # Try without RCA result using direct category
            report(4, "RCA-SOP Bridge", False, "No RCA result from Stage 3, skipping SOP match")
    except Exception as e:
        report(4, "SOP Matching", False, str(e))
        traceback.print_exc()

    # ── Stage 5: SOP Safety Layer — 安全检查 ──────────────────────
    print("\n" + "="*60, flush=True)
    print("Stage 5: SOP Safety Layer — Risk & execution check", flush=True)
    print("="*60, flush=True)
    safety_decision = None
    try:
        from src.sop_safety import get_safety_layer
        safety = get_safety_layer()
        if matched_sops and len(matched_sops) > 0:
            sop = matched_sops[0]
            # Extract sop_id from matched SOP (could be dict or object)
            if isinstance(sop, dict):
                sop_id = sop.get('sop_id') or sop.get('id') or sop.get('name', 'unknown')
                resource_ids = sop.get('resource_ids', [])
            else:
                sop_id = getattr(sop, 'sop_id', getattr(sop, 'id', 'unknown'))
                resource_ids = getattr(sop, 'resource_ids', [])
            safety_decision = safety.check(sop_id, resource_ids=resource_ids, dry_run=True)
            report(5, "SOPSafetyLayer.check()",
                   safety_decision is not None,
                   f"sop_id={sop_id} risk={safety_decision.risk_level.value} "
                   f"mode={safety_decision.execution_mode.value} "
                   f"passed={safety_decision.passed}")
        else:
            # Test with a dummy SOP action to verify the layer works
            from src.sop_safety import RiskLevel
            risk = safety.classify_risk("describe_instances")
            report(5, "SOPSafetyLayer.classify_risk()",
                   risk == RiskLevel.L0,
                   f"describe_instances → {risk.value} (expected L0)")
    except Exception as e:
        report(5, "SOP Safety Layer", False, str(e))
        traceback.print_exc()

    # ── Stage 6: IncidentOrchestrator — Full pipeline ─────────────
    print("\n" + "="*60, flush=True)
    print("Stage 6: IncidentOrchestrator — Full pipeline", flush=True)
    print("="*60, flush=True)
    try:
        from src.incident_orchestrator import get_orchestrator
        orchestrator = get_orchestrator()
        if detect_result:
            incident = await orchestrator.handle_incident(
                trigger_type="manual",
                trigger_data={"test": "e2e_walkthrough", "source": "developer"},
                detect_result=detect_result,
                auto_execute=False,  # Don't auto-execute, just test the pipeline
            )
            report(6, "IncidentOrchestrator.handle_incident()",
                   incident is not None,
                   f"incident_id={incident.incident_id} "
                   f"status={incident.status.value} "
                   f"duration={incident.duration_ms}ms")
        else:
            report(6, "IncidentOrchestrator", False, "No DetectResult available")
    except Exception as e:
        report(6, "IncidentOrchestrator", False, str(e))
        traceback.print_exc()

    # ── Summary ───────────────────────────────────────────────────
    elapsed = time.time() - t0
    print("\n" + "="*60, flush=True)
    print(f"E2E WALKTHROUGH SUMMARY  ({elapsed:.1f}s)", flush=True)
    print("="*60, flush=True)
    passed = sum(1 for _, _, ok, _ in results if ok)
    failed = sum(1 for _, _, ok, _ in results if not ok)
    for stage, name, ok, detail in results:
        status = PASS if ok else FAIL
        print(f"  {status} Stage {stage}: {name}")
        if detail:
            print(f"     └─ {detail}")
    print(f"\n  Total: {passed} passed, {failed} failed out of {len(results)}", flush=True)
    print("="*60, flush=True)

    return 0 if failed == 0 else 1

if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
