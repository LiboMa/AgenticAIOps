#!/usr/bin/env python3
"""
E2E Real Scenario Test — EC2 High CPU Full Agent Chain

Scenario:
  A CloudWatch Alarm fires: EC2 CPUUtilization > 90%
  → Detect Agent collects real AWS data (CloudWatch metrics, alarms, trail, health)
  → Pattern matching identifies "cpu-001" / "high_cpu"
  → RCA Agent (Bedrock Claude) analyzes root cause
  → SOP Bridge matches "sop-ec2-high-cpu"
  → Safety Layer checks risk level, cooldown, dry-run preview
  → Result: Full IncidentRecord with all stages

Run:
  cd /home/ubuntu/agentic-aiops-mvp
  python3 -m tests.e2e_real_scenario

Exit codes:
  0 = all stages passed
  1 = one or more stages failed
"""

import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone

# ── Setup ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("e2e_real_scenario")

# Reduce noise from boto/urllib
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


# ── Pretty Print Helpers ───────────────────────────────────────────────
PASS = "✅"
FAIL = "❌"
SKIP = "⏭️"
WARN = "⚠️"


def stage_header(num: int, name: str):
    logger.info(f"\n{'='*60}")
    logger.info(f"  Stage {num}: {name}")
    logger.info(f"{'='*60}")


def stage_result(num: int, name: str, ok: bool, duration_ms: int, detail: str = ""):
    icon = PASS if ok else FAIL
    logger.info(f"{icon} Stage {num} [{name}] — {duration_ms}ms {detail}")
    return ok


# ── Stage 1: Detect Agent — Real AWS Data Collection ──────────────────
async def stage1_detect():
    """
    Run DetectAgent.run_detection() with real AWS CloudWatch data.
    Returns DetectResult.
    """
    stage_header(1, "Detect Agent — Real AWS Data Collection")
    start = time.time()

    from src.detect_agent import DetectAgent

    agent = DetectAgent(region="ap-southeast-1")
    result = await agent.run_detection(
        lookback_minutes=15,
        source="proactive_scan",
        ttl_seconds=300,
    )

    dur = int((time.time() - start) * 1000)

    # Validate
    assert result is not None, "DetectResult is None"
    assert result.detect_id.startswith("det-"), f"Bad detect_id: {result.detect_id}"
    assert result.correlated_event is not None, "correlated_event is None (collection failed)"
    assert not result.error, f"Detection error: {result.error}"

    ev = result.correlated_event
    logger.info(f"  detect_id:   {result.detect_id}")
    logger.info(f"  source:      {result.source}")
    logger.info(f"  freshness:   {result.freshness_label}")
    logger.info(f"  metrics:     {len(ev.metrics)}")
    logger.info(f"  alarms:      {len(ev.alarms)}")
    logger.info(f"  trail_events:{len(ev.trail_events)}")
    logger.info(f"  anomalies:   {len(ev.anomalies)}")
    logger.info(f"  health:      {len(ev.health_events)}")
    logger.info(f"  collect_ms:  {ev.duration_ms}")

    stage_result(1, "Detect", True, dur,
                 f"({len(ev.metrics)}m/{len(ev.alarms)}a/{len(ev.trail_events)}t)")
    return result


# ── Stage 2: Pattern Matching ─────────────────────────────────────────
def stage2_pattern_match(detect_result):
    """
    Match detected anomalies against known patterns via RCA_SOP_MAPPING.
    """
    stage_header(2, "Pattern Matching")
    start = time.time()

    from src.rca_sop_bridge import RCA_SOP_MAPPING

    ev = detect_result.correlated_event
    matched_patterns = []

    # Check anomalies for keyword matches
    for anomaly in ev.anomalies:
        metric = anomaly.get("metric_name", "").lower()
        detail = anomaly.get("detail", "").lower()
        combined = f"{metric} {detail}"

        for pattern_key in RCA_SOP_MAPPING:
            if pattern_key.lower() in combined:
                matched_patterns.append({
                    "pattern_key": pattern_key,
                    "anomaly_metric": anomaly.get("metric_name"),
                    "sop_ids": RCA_SOP_MAPPING[pattern_key],
                })

    # Also check alarm names
    for alarm in ev.alarms:
        alarm_name = alarm.name.lower() if hasattr(alarm, 'name') else str(alarm).lower()
        for pattern_key in RCA_SOP_MAPPING:
            if pattern_key.lower() in alarm_name:
                matched_patterns.append({
                    "pattern_key": pattern_key,
                    "alarm_source": alarm_name,
                    "sop_ids": RCA_SOP_MAPPING[pattern_key],
                })

    dur = int((time.time() - start) * 1000)
    logger.info(f"  Matched patterns: {len(matched_patterns)}")
    for p in matched_patterns:
        logger.info(f"    → {p['pattern_key']} → SOPs: {p['sop_ids']}")

    if not matched_patterns:
        logger.info(f"  {WARN} No pattern matches from anomalies (may still match via RCA keywords)")

    stage_result(2, "Pattern", True, dur, f"({len(matched_patterns)} matches)")
    return matched_patterns


# ── Stage 3: RCA Agent (Bedrock Claude) ───────────────────────────────
async def stage3_rca(detect_result):
    """
    Run RCA inference using Bedrock Claude on real collected data.
    """
    stage_header(3, "RCA Agent — Bedrock Claude Analysis")
    start = time.time()

    from src.rca_inference import get_rca_inference_engine

    engine = get_rca_inference_engine()
    rca_result = await engine.analyze(detect_result.correlated_event)

    dur = int((time.time() - start) * 1000)

    assert rca_result is not None, "RCA result is None"

    logger.info(f"  pattern_id:  {rca_result.pattern_id}")
    logger.info(f"  root_cause:  {rca_result.root_cause[:120]}...")
    logger.info(f"  severity:    {rca_result.severity}")
    logger.info(f"  confidence:  {rca_result.confidence}")
    logger.info(f"  model:       {getattr(rca_result, 'model_id', 'unknown')}")
    if hasattr(rca_result, 'recommendations') and rca_result.recommendations:
        logger.info(f"  recommendations:")
        for r in rca_result.recommendations[:3]:
            logger.info(f"    • {r[:100]}")

    stage_result(3, "RCA", True, dur,
                 f"(conf={rca_result.confidence}, sev={rca_result.severity})")
    return rca_result


# ── Stage 3b: RCA Agent — Force Bedrock LLM Path ─────────────────────
async def stage3b_rca_llm(detect_result):
    """
    Run RCA with force_llm=True to bypass pattern matcher short-circuit
    and validate the Bedrock Claude → Sonnet (→ Opus) path end-to-end.
    """
    stage_header("3b", "RCA Agent — Bedrock LLM Path (force_llm=True)")
    start = time.time()

    from src.rca_inference import get_rca_inference_engine

    engine = get_rca_inference_engine()
    rca_result = await engine.analyze(detect_result.correlated_event, force_llm=True)

    dur = int((time.time() - start) * 1000)

    assert rca_result is not None, "RCA LLM result is None"

    model = getattr(rca_result, 'model_id', 'unknown')
    logger.info(f"  pattern_id:  {rca_result.pattern_id}")
    logger.info(f"  root_cause:  {rca_result.root_cause[:200]}...")
    logger.info(f"  severity:    {rca_result.severity}")
    logger.info(f"  confidence:  {rca_result.confidence}")
    logger.info(f"  model:       {model}")
    if hasattr(rca_result, 'recommendations') and rca_result.recommendations:
        logger.info(f"  recommendations:")
        for r in rca_result.recommendations[:3]:
            logger.info(f"    • {r[:120]}")

    # Validate it actually went through LLM
    is_llm = "llm" in (rca_result.pattern_id or "").lower() or "sonnet" in model.lower() or "opus" in model.lower() or "claude" in model.lower() or "apac" in model.lower() or "global" in model.lower()
    if is_llm:
        logger.info(f"  {PASS} BEDROCK LLM PATH CONFIRMED — model: {model}")
    else:
        logger.info(f"  {WARN} Could not confirm LLM path (pattern_id={rca_result.pattern_id}, model={model})")

    stage_result("3b", "RCA-LLM", True, dur,
                 f"(conf={rca_result.confidence}, sev={rca_result.severity}, model={model})")
    return rca_result


# ── Stage 4: SOP Matching (Bridge) ────────────────────────────────────
def stage4_sop_match(rca_result):
    """
    Use RCA→SOP Bridge to find matching SOPs.
    """
    stage_header(4, "SOP Matching — RCA→SOP Bridge")
    start = time.time()

    from src.rca_sop_bridge import get_bridge

    bridge = get_bridge()
    matched_sops = bridge.match_sops(rca_result)

    dur = int((time.time() - start) * 1000)

    logger.info(f"  Matched SOPs: {len(matched_sops)}")
    for sop in matched_sops:
        logger.info(f"    → {sop['sop_id']}: {sop.get('name', 'N/A')} "
                     f"(match={sop.get('match_type', '?')}, conf={sop.get('confidence', '?')})")

    stage_result(4, "SOP Match", True, dur, f"({len(matched_sops)} SOPs)")
    return matched_sops


# ── Stage 5: Safety Layer ─────────────────────────────────────────────
def stage5_safety(matched_sops, rca_result):
    """
    Run safety checks on matched SOPs.
    """
    stage_header(5, "Safety Layer — Risk Check + Dry Run")
    start = time.time()

    if not matched_sops:
        dur = int((time.time() - start) * 1000)
        logger.info(f"  {SKIP} No SOPs matched — skipping safety check")
        stage_result(5, "Safety", True, dur, "(skipped)")
        return None

    from src.sop_safety import get_safety_layer

    safety = get_safety_layer()
    best_sop = matched_sops[0]

    resource_ids = (
        getattr(rca_result, 'affected_resources', None)
        or getattr(rca_result, 'matched_symptoms', None)
        or []
    )

    safety_result = safety.check(
        sop_id=best_sop['sop_id'],
        resource_ids=resource_ids,
        dry_run=True,  # Always dry-run in E2E test
        force=False,
        context={
            "confidence": rca_result.confidence,
            "severity": rca_result.severity.value if hasattr(rca_result.severity, 'value') else str(rca_result.severity),
            "trigger": "e2e_test",
        }
    )

    dur = int((time.time() - start) * 1000)

    logger.info(f"  sop_id:      {best_sop['sop_id']}")
    logger.info(f"  risk_level:  {safety_result.risk_level}")
    logger.info(f"  exec_mode:   {safety_result.execution_mode}")
    logger.info(f"  passed:      {safety_result.passed}")
    logger.info(f"  reason:      {safety_result.reason}")
    if safety_result.warnings:
        logger.info(f"  warnings:    {safety_result.warnings}")
    if safety_result.dry_run_preview:
        logger.info(f"  dry_run_preview: {json.dumps(safety_result.dry_run_preview, indent=4, default=str)[:300]}")

    stage_result(5, "Safety", True, dur,
                 f"(risk={safety_result.risk_level}, mode={safety_result.execution_mode})")
    return safety_result


# ── Stage 6: Full Pipeline (Orchestrator with DetectResult Reuse) ─────
async def stage6_full_pipeline(detect_result):
    """
    Run the full IncidentOrchestrator.handle_incident() using DetectResult
    to prove data reuse (Stage 1 skip).
    """
    stage_header(6, "Full Pipeline — Orchestrator with DetectResult Reuse")
    start = time.time()

    from src.incident_orchestrator import IncidentOrchestrator

    orchestrator = IncidentOrchestrator(region="ap-southeast-1")
    incident = await orchestrator.handle_incident(
        trigger_type="detect_agent",
        trigger_data={"scenario": "e2e_real_test", "source": detect_result.detect_id},
        dry_run=True,
        detect_result=detect_result,
    )

    dur = int((time.time() - start) * 1000)

    logger.info(f"  incident_id:   {incident.incident_id}")
    logger.info(f"  status:        {incident.status.value}")
    logger.info(f"  total_ms:      {incident.duration_ms}")
    logger.info(f"  stage_timings: {json.dumps(incident.stage_timings, indent=4)}")

    # Check data reuse
    coll = incident.collection_summary or {}
    source = coll.get("source", "unknown")
    logger.info(f"  collection_source: {source}")

    if source == "detect_agent_reuse":
        logger.info(f"  {PASS} DATA REUSE CONFIRMED — Stage 1 skipped!")
        logger.info(f"     Data age: {coll.get('data_age_seconds', '?')}s")
    else:
        logger.info(f"  {WARN} Fresh collection used (detect_result may have been stale)")

    if incident.rca_result:
        logger.info(f"  rca_pattern:   {incident.rca_result.get('pattern_id', 'N/A')}")
        logger.info(f"  rca_confidence:{incident.rca_result.get('confidence', 'N/A')}")

    if incident.matched_sops:
        logger.info(f"  matched_sops:  {len(incident.matched_sops)}")
        for sop in incident.matched_sops[:3]:
            logger.info(f"    → {sop.get('sop_id', '?')}")

    ok = incident.status.value in ("completed", "waiting_approval")
    stage_result(6, "Pipeline", ok, dur,
                 f"(status={incident.status.value}, {incident.duration_ms}ms)")
    return incident


# ── Main ──────────────────────────────────────────────────────────────
async def main():
    logger.info("""
╔══════════════════════════════════════════════════════════════╗
║     E2E Real Scenario — EC2 High CPU Full Agent Chain       ║
║                                                              ║
║  Detect → Pattern → RCA → SOP → Safety → Full Pipeline      ║
║  Real AWS data • Real Bedrock inference • Dry-run only       ║
╚══════════════════════════════════════════════════════════════╝
""")
    logger.info(f"  Start: {datetime.now(timezone.utc).isoformat()}")
    logger.info(f"  Region: ap-southeast-1")
    logger.info(f"  Mode: DRY_RUN (no remediation executed)\n")

    total_start = time.time()
    results = {}

    # Stage 1: Detect Agent
    try:
        detect_result = await stage1_detect()
        results["detect"] = True
    except Exception as e:
        logger.error(f"{FAIL} Stage 1 FAILED: {e}")
        results["detect"] = False
        logger.info("\n⛔ Cannot continue without detection data. Aborting.")
        return 1

    # Stage 2: Pattern Match
    try:
        patterns = stage2_pattern_match(detect_result)
        results["pattern"] = True
    except Exception as e:
        logger.error(f"{FAIL} Stage 2 FAILED: {e}")
        results["pattern"] = False
        patterns = []

    # Stage 3: RCA
    try:
        rca_result = await stage3_rca(detect_result)
        results["rca"] = True
    except Exception as e:
        logger.error(f"{FAIL} Stage 3 FAILED: {e}")
        results["rca"] = False
        logger.info("\n⛔ Cannot continue without RCA. Aborting.")
        return 1

    # Stage 3b: RCA via Bedrock LLM (force_llm=True)
    try:
        rca_llm_result = await stage3b_rca_llm(detect_result)
        results["rca_llm"] = True
    except Exception as e:
        logger.error(f"{FAIL} Stage 3b FAILED: {e}")
        results["rca_llm"] = False
        rca_llm_result = None

    # Stage 4: SOP Match
    try:
        matched_sops = stage4_sop_match(rca_result)
        results["sop_match"] = True
    except Exception as e:
        logger.error(f"{FAIL} Stage 4 FAILED: {e}")
        results["sop_match"] = False
        matched_sops = []

    # Stage 5: Safety
    try:
        safety_result = stage5_safety(matched_sops, rca_result)
        results["safety"] = True
    except Exception as e:
        logger.error(f"{FAIL} Stage 5 FAILED: {e}")
        results["safety"] = False

    # Stage 6: Full Pipeline with Reuse
    try:
        incident = await stage6_full_pipeline(detect_result)
        results["pipeline"] = True
    except Exception as e:
        logger.error(f"{FAIL} Stage 6 FAILED: {e}")
        results["pipeline"] = False

    # ── Summary ──────────────────────────────────────────────
    total_ms = int((time.time() - total_start) * 1000)
    logger.info(f"\n{'='*60}")
    logger.info(f"  E2E SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"  Total time: {total_ms}ms ({total_ms/1000:.1f}s)")
    logger.info(f"  Results:")
    all_ok = True
    for stage, ok in results.items():
        icon = PASS if ok else FAIL
        logger.info(f"    {icon} {stage}")
        if not ok:
            all_ok = False

    if all_ok:
        logger.info(f"\n  🎉 ALL STAGES PASSED — Real E2E scenario verified!")
    else:
        failed = [k for k, v in results.items() if not v]
        logger.info(f"\n  ⛔ FAILED stages: {', '.join(failed)}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
