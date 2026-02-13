#!/usr/bin/env python3
"""
Real E2E Test — 手动串联真实场景
Ma Ronnie 要求: 从头到尾跑一个真实场景，哪步断了修哪步。

场景: ProactiveAgent heartbeat → DetectAgent 采集真实 AWS 数据 → 
      Orchestrator RCA → SOP 匹配 → Safety 检查

每步独立测试，打印结果，失败立刻报告。
"""

import asyncio
import json
import sys
import time
import traceback
from datetime import datetime, timezone

# ═══════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════

def banner(step, desc):
    print(f"\n{'='*60}")
    print(f"  STEP {step}: {desc}")
    print(f"{'='*60}")

def ok(msg):
    print(f"  ✅ {msg}")

def fail(msg):
    print(f"  ❌ {msg}")

def info(msg):
    print(f"  ℹ️  {msg}")


async def main():
    results = {}
    t0 = time.time()

    # ═══════════════════════════════════════════════════════════
    # STEP 1: EventCorrelator 真实 AWS 数据采集
    # ═══════════════════════════════════════════════════════════
    banner(1, "EventCorrelator — 真实 AWS 数据采集")
    try:
        from src.event_correlator import get_correlator
        correlator = get_correlator("ap-southeast-1")
        
        t1 = time.time()
        event = await correlator.collect(
            services=["ec2", "lambda", "rds", "s3"],
            lookback_minutes=15,
        )
        collect_ms = int((time.time() - t1) * 1000)
        
        ok(f"采集完成 — {collect_ms}ms")
        info(f"collection_id: {event.collection_id}")
        info(f"metrics: {len(event.metrics)}")
        info(f"alarms: {len(event.alarms)}")
        info(f"trail_events: {len(event.trail_events)}")
        info(f"anomalies: {len(event.anomalies)}")
        info(f"health_events: {len(event.health_events)}")
        
        results["step1"] = {"status": "ok", "event": event, "ms": collect_ms}
    except Exception as e:
        fail(f"采集失败: {e}")
        traceback.print_exc()
        results["step1"] = {"status": "fail", "error": str(e)}

    # ═══════════════════════════════════════════════════════════
    # STEP 2: DetectAgent — 封装采集 + 缓存
    # ═══════════════════════════════════════════════════════════
    banner(2, "DetectAgent — run_detection (真实 AWS)")
    try:
        from src.detect_agent import get_detect_agent
        agent = get_detect_agent("ap-southeast-1")
        
        t2 = time.time()
        detect_result = await agent.run_detection(source="proactive_scan")
        detect_ms = int((time.time() - t2) * 1000)
        
        ok(f"检测完成 — {detect_ms}ms")
        info(f"detect_id: {detect_result.detect_id}")
        info(f"source: {detect_result.source}")
        info(f"freshness: {detect_result.freshness_label}")
        info(f"is_stale: {detect_result.is_stale}")
        info(f"age_seconds: {detect_result.age_seconds:.1f}s")
        info(f"anomalies: {len(detect_result.anomalies_detected)}")
        info(f"pattern_matches: {len(detect_result.pattern_matches)}")
        if detect_result.correlated_event:
            ce = detect_result.correlated_event
            info(f"correlated_event.metrics: {len(ce.metrics)}")
            info(f"correlated_event.alarms: {len(ce.alarms)}")
        else:
            fail("correlated_event is None!")
        if detect_result.error:
            fail(f"detect error: {detect_result.error}")
        
        results["step2"] = {"status": "ok", "detect_result": detect_result, "ms": detect_ms}
    except Exception as e:
        fail(f"DetectAgent 失败: {e}")
        traceback.print_exc()
        results["step2"] = {"status": "fail", "error": str(e)}

    # ═══════════════════════════════════════════════════════════
    # STEP 3: Orchestrator — 完整 pipeline (用 DetectResult 跳过采集)
    # ═══════════════════════════════════════════════════════════
    banner(3, "IncidentOrchestrator — 完整 pipeline (detect_result 复用)")
    try:
        from src.incident_orchestrator import IncidentOrchestrator
        orchestrator = IncidentOrchestrator(region="ap-southeast-1")
        
        dr = results.get("step2", {}).get("detect_result")
        if not dr:
            info("Step 2 失败, 用 Step 1 的 event 做 fallback (不传 detect_result)")
        
        t3 = time.time()
        incident = await orchestrator.handle_incident(
            trigger_type="proactive" if dr else "manual",
            trigger_data={"test": "e2e_real_test", "timestamp": datetime.now(timezone.utc).isoformat()},
            services=["ec2", "lambda", "rds", "s3"],
            auto_execute=False,
            dry_run=True,
            lookback_minutes=15,
            detect_result=dr,
        )
        pipeline_ms = int((time.time() - t3) * 1000)
        
        ok(f"Pipeline 完成 — {pipeline_ms}ms, status={incident.status.value}")
        info(f"incident_id: {incident.incident_id}")
        
        # Collection
        if incident.collection_summary:
            cs = incident.collection_summary
            info(f"Collection: source={cs.get('source')}, metrics={cs.get('metrics')}, alarms={cs.get('alarms')}")
            if cs.get('source') == 'detect_agent_reuse':
                ok(f"DetectResult 复用成功! data_age={cs.get('data_age_seconds')}s")
            else:
                info(f"Fresh collection (expected if manual or no detect_result)")
        else:
            fail("No collection_summary!")
        
        # RCA
        if incident.rca_result:
            rca = incident.rca_result
            ok(f"RCA: root_cause='{rca.get('root_cause', '?')[:80]}...'")
            info(f"RCA: confidence={rca.get('confidence')}, severity={rca.get('severity')}")
            info(f"RCA: pattern_id={rca.get('pattern_id')}")
        else:
            fail("No rca_result!")
        
        # SOP Match
        if incident.matched_sops:
            ok(f"SOP 匹配: {len(incident.matched_sops)} SOPs")
            for sop in incident.matched_sops[:3]:
                info(f"  - {sop['sop_id']}: {sop['name']} (confidence={sop['match_confidence']:.0%})")
        else:
            info("No SOP matched (可能正常如果没有告警)")
        
        # Safety
        if incident.safety_check:
            sc = incident.safety_check
            ok(f"Safety: passed={sc.get('passed')}, mode={sc.get('execution_mode')}, risk={sc.get('risk_level')}")
        else:
            info("No safety_check (正常如果没有 SOP 匹配)")
        
        # Stage timings
        if incident.stage_timings:
            ok(f"Stage timings: {json.dumps(incident.stage_timings)}")
        
        results["step3"] = {"status": "ok" if incident.status.value in ("completed", "waiting_approval") else "fail", 
                           "incident": incident, "ms": pipeline_ms}
    except Exception as e:
        fail(f"Orchestrator pipeline 失败: {e}")
        traceback.print_exc()
        results["step3"] = {"status": "fail", "error": str(e)}

    # ═══════════════════════════════════════════════════════════
    # STEP 4: 同一个 DetectResult, 再跑一次 — 验证缓存复用
    # ═══════════════════════════════════════════════════════════
    banner(4, "缓存复用验证 — 同一 DetectResult 再跑一次 Orchestrator")
    try:
        dr = results.get("step2", {}).get("detect_result")
        if dr:
            from src.incident_orchestrator import IncidentOrchestrator
            orchestrator2 = IncidentOrchestrator(region="ap-southeast-1")
            
            t4 = time.time()
            incident2 = await orchestrator2.handle_incident(
                trigger_type="proactive",
                trigger_data={"test": "e2e_reuse_test"},
                detect_result=dr,
                dry_run=True,
            )
            reuse_ms = int((time.time() - t4) * 1000)
            
            cs = incident2.collection_summary or {}
            if cs.get("source") == "detect_agent_reuse":
                ok(f"缓存复用成功! Pipeline 耗时 {reuse_ms}ms (vs Step3 {results['step3'].get('ms', '?')}ms)")
                ok(f"数据年龄: {cs.get('data_age_seconds')}s")
            else:
                fail(f"缓存未复用! source={cs.get('source')}")
            
            results["step4"] = {"status": "ok", "ms": reuse_ms}
        else:
            info("跳过 — Step 2 没有 detect_result")
            results["step4"] = {"status": "skip"}
    except Exception as e:
        fail(f"缓存复用测试失败: {e}")
        traceback.print_exc()
        results["step4"] = {"status": "fail", "error": str(e)}

    # ═══════════════════════════════════════════════════════════
    # STEP 5: Manual trigger — 验证不复用缓存 (R2 规则)
    # ═══════════════════════════════════════════════════════════
    banner(5, "Manual trigger — 验证 R2 规则 (不复用缓存)")
    try:
        dr = results.get("step2", {}).get("detect_result")
        if dr:
            from src.incident_orchestrator import IncidentOrchestrator
            orchestrator3 = IncidentOrchestrator(region="ap-southeast-1")
            
            t5 = time.time()
            incident3 = await orchestrator3.handle_incident(
                trigger_type="manual",
                trigger_data={"test": "e2e_manual_test"},
                detect_result=dr,  # Should be IGNORED because manual
                dry_run=True,
                lookback_minutes=15,
            )
            manual_ms = int((time.time() - t5) * 1000)
            
            cs = incident3.collection_summary or {}
            if cs.get("source") == "fresh_collection":
                ok(f"R2 规则正确! Manual trigger 走 fresh collection ({manual_ms}ms)")
            else:
                fail(f"R2 规则失败! source={cs.get('source')} (should be fresh_collection)")
            
            results["step5"] = {"status": "ok", "ms": manual_ms}
        else:
            info("跳过 — Step 2 没有 detect_result")
            results["step5"] = {"status": "skip"}
    except Exception as e:
        fail(f"Manual trigger 测试失败: {e}")
        traceback.print_exc()
        results["step5"] = {"status": "fail", "error": str(e)}

    # ═══════════════════════════════════════════════════════════
    # 汇总
    # ═══════════════════════════════════════════════════════════
    total_ms = int((time.time() - t0) * 1000)
    
    print(f"\n{'='*60}")
    print(f"  E2E REAL TEST SUMMARY")
    print(f"{'='*60}")
    
    for step, data in results.items():
        status = data.get("status", "?")
        ms = data.get("ms", "")
        ms_str = f" ({ms}ms)" if ms else ""
        icon = "✅" if status == "ok" else "❌" if status == "fail" else "⏭️"
        print(f"  {icon} {step}: {status}{ms_str}")
    
    print(f"\n  Total: {total_ms}ms ({total_ms/1000:.1f}s)")
    
    failed = [k for k, v in results.items() if v.get("status") == "fail"]
    if failed:
        print(f"\n  ❌ FAILED STEPS: {', '.join(failed)}")
        return 1
    else:
        print(f"\n  ✅ ALL STEPS PASSED")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
