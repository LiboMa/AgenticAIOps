# E2E Test Plan: Channel-Driven RCA + Autonomous Skills

**Author**: Tester  
**Date**: 2026-03-08  
**ADR Reference**: ADR-009 (Channel-Driven RCA + Skills Integration)  
**Baseline**: 2,903 passed | 71 skipped | 0 failed | 86% coverage

---

## 1. Scope

End-to-end testing for the full chain:
```
Channel Alert → AlertIngressService → StructuredAlert → SkillBridge → DetectAgent/RCA → Knowledge Flywheel
```

---

## 2. Test Modules

### 2.1 StructuredAlert Model (`tests/test_alert_models.py`) — ~15 tests

| # | Test | Priority |
|---|------|----------|
| 1 | Valid CloudWatch alert → StructuredAlert | P0 |
| 2 | Valid Datadog alert → StructuredAlert | P0 |
| 3 | Valid PagerDuty alert → StructuredAlert | P0 |
| 4 | Valid Grafana alert → StructuredAlert | P1 |
| 5 | Generic/unknown format → StructuredAlert with fallback | P1 |
| 6 | Severity normalization: P1→critical, warning→medium, error→high | P0 |
| 7 | Missing required fields → ValidationError | P0 |
| 8 | Duplicate detection (same external_id) | P1 |
| 9 | Timestamp parsing (ISO8601, epoch, mixed) | P1 |
| 10 | Resource hint extraction (i-xxx, arn:, pod name) | P0 |
| 11 | Raw data preserved in raw_data field | P1 |
| 12 | Channel source metadata (channel_id, message_id) | P1 |
| 13 | Sanitization: no AWS credentials in StructuredAlert | P0 ⚠️ |
| 14 | Sanitization: no IP addresses leaked | P1 |
| 15 | to_dict() / from_dict() round-trip | P1 |

### 2.2 Alert Parsers (`tests/test_alert_parsers.py`) — ~25 tests

| # | Parser | Tests | Priority |
|---|--------|-------|----------|
| 1-5 | CloudWatch parser | Alarm state change, metric threshold, composite alarm, anomaly, malformed | P0 |
| 6-10 | Datadog parser | Monitor alert, event, service check, log alert, malformed | P0 |
| 11-15 | PagerDuty parser | Incident trigger, resolve, acknowledge, escalate, malformed | P1 |
| 16-20 | Grafana parser | Alerting, OK, no_data, pending, malformed | P1 |
| 21-23 | Generic parser | Plain text alert, JSON blob, unknown format fallback | P1 |
| 24 | Parser selection: auto-detect source from message format | P0 |
| 25 | Non-alert message → rejected (false positive prevention) | P0 ⚠️ |

### 2.3 AlertIngressService (`tests/test_alert_ingress.py`) — ~12 tests

| # | Test | Priority |
|---|------|----------|
| 1 | Channel message → parse → emit StructuredAlert | P0 |
| 2 | EventBridge event → parse → emit StructuredAlert | P0 |
| 3 | Duplicate dedup (same external_id within window) | P1 |
| 4 | Rate limiting (>N alerts/minute → throttle) | P2 |
| 5 | Error in parser → log + skip (no crash) | P0 |
| 6 | Channel filter: only process from configured #alerts channel | P0 ⚠️ |
| 7 | Non-alert message in #alerts → ignored | P0 |
| 8 | Multi-source aggregation (CW + DD in same window) | P1 |
| 9 | Alert routing: critical → immediate, warning → batched | P2 |
| 10 | Health check: ingress service status endpoint | P2 |
| 11 | Configuration hot-reload (add new parser at runtime) | P3 |
| 12 | Metrics: alert_count, parse_errors, avg_latency | P2 |

### 2.4 SkillBridge (`tests/test_skill_bridge.py`) — ~18 tests

| # | Test | Priority |
|---|------|----------|
| 1 | Initialize with role "detect" → load detect-tier skills | P0 |
| 2 | Initialize with role "rca" → load rca-tier skills | P0 |
| 3 | Initialize with role "sre" → load sre-tier skills | P0 |
| 4 | load_skills_for_context(eks, pod_crash) → kubernetes skill | P0 |
| 5 | load_skills_for_context(ec2, high_cpu) → aws_general + monitoring | P0 |
| 6 | load_skills_for_context(unknown) → empty list (fail-closed) | P0 ⚠️ |
| 7 | Tier enforcement: detect role cannot load T2/T3 tools | P0 ⚠️ |
| 8 | Tier enforcement: sre role can load T0-T2 | P0 |
| 9 | @secure_tool validation passes through bridge | P0 |
| 10 | Bridge ↔ SkillRegistry singleton consistency | P1 |
| 11 | Multiple contexts → correct skill selection | P1 |
| 12 | Performance: load_skills_for_context < 50ms | P2 |
| 13 | Hot-reload: new skill registered → bridge sees it | P2 |
| 14 | agent_binding.py integration (bind_skills_to_agent) | P0 |
| 15 | System prompt generation with tier-scoped content | P1 |
| 16 | can_handle() routing with domains + keywords | P0 |
| 17 | confidence_boost scoring | P2 |
| 18 | Missing skill manifest → SkillLoadError | P1 |

### 2.5 Agent Integration (`tests/test_agent_skill_integration.py`) — ~12 tests

| # | Test | Priority |
|---|------|----------|
| 1 | DetectAgent.run_detection() uses SkillBridge | P0 |
| 2 | DetectAgent selects kubernetes skill for pod alert | P0 |
| 3 | DetectAgent selects monitoring skill for metric alert | P0 |
| 4 | RCA uses SkillBridge to collect diagnostic evidence | P0 |
| 5 | IncidentOrchestrator routes alert → detect → rca chain | P0 |
| 6 | End-to-end: StructuredAlert → detect → rca → result | P0 |
| 7 | Fallback: no matching skill → graceful degradation | P0 ⚠️ |
| 8 | Multiple skills for same alert (kubernetes + monitoring) | P1 |
| 9 | Skill execution error → logged, RCA continues | P1 |
| 10 | detect_result reuse (0ms path) still works | P1 |
| 11 | Async execution: Skills don't block event loop | P1 |
| 12 | Integration with existing test baseline (no regression) | P0 |

### 2.6 Knowledge Flywheel (`tests/test_knowledge_flywheel.py`) — ~15 tests

| # | Test | Priority |
|---|------|----------|
| 1 | RCA result → CaseStudy conversion | P0 |
| 2 | CaseStudy fields: symptom, root_cause, resolution, lessons_learned | P0 |
| 3 | CaseStudy status: pending_review (default) | P0 |
| 4 | VectorStore.upsert() stores embedding | P0 |
| 5 | VectorStore.search() returns relevant cases | P0 |
| 6 | HybridSearch: vector + keyword fallback | P1 |
| 7 | HybridSearch: rerank by relevance | P2 |
| 8 | Flywheel capture: auto-extract from RCA result | P0 |
| 9 | Flywheel retrieval: inject history into RCA context | P0 |
| 10 | Sensitive data sanitization before storage | P0 ⚠️ |
| 11 | Empty/failed RCA → no CaseStudy created | P1 |
| 12 | Duplicate CaseStudy → update not insert | P1 |
| 13 | SQLite persistence across restarts | P1 |
| 14 | Embedding model failure → keyword-only fallback | P2 |
| 15 | CaseStudy lifecycle: pending → verified → archived | P1 |

### 2.7 Full E2E Chain (`tests/test_e2e_channel_rca.py`) — ~8 tests

| # | Test | Priority |
|---|------|----------|
| 1 | CloudWatch alert in #alerts → detect → rca → result + CaseStudy | P0 🔴 |
| 2 | Datadog alert → full chain | P0 |
| 3 | Repeat alert → KB retrieval → faster RCA | P0 |
| 4 | Critical alert → immediate processing | P0 |
| 5 | Non-alert message in #alerts → ignored | P0 |
| 6 | Multiple concurrent alerts → correct routing | P1 |
| 7 | Chain failure mid-way → graceful error + no CaseStudy | P1 |
| 8 | Full chain with Skills tier enforcement | P0 |

---

## 3. Test Summary

| Module | Tests | P0 | P1 | P2+ |
|--------|-------|----|----|-----|
| StructuredAlert Model | 15 | 6 | 7 | 2 |
| Alert Parsers | 25 | 12 | 11 | 2 |
| AlertIngressService | 12 | 5 | 3 | 4 |
| SkillBridge | 18 | 9 | 5 | 4 |
| Agent Integration | 12 | 7 | 4 | 1 |
| Knowledge Flywheel | 15 | 7 | 5 | 3 |
| Full E2E Chain | 8 | 6 | 2 | 0 |
| **TOTAL** | **105** | **52** | **37** | **16** |

---

## 4. Security Tests (⚠️ marked above)

Critical security tests that must pass before any merge:

1. **Sanitization**: No AWS credentials/keys in StructuredAlert or CaseStudy
2. **Channel isolation**: Only configured #alerts channel processed
3. **False positive prevention**: Non-alert messages rejected
4. **Tier enforcement**: detect role blocked from T2/T3 tools
5. **Fail-closed**: Unknown context → no tools loaded (not all tools)

---

## 5. Success Criteria

1. All P0 tests pass (52 tests)
2. Full regression ≥2,903 passed (no regression)
3. Coverage ≥86% (no decrease)
4. ADR-009 success criteria #1-5 all verified
5. Security tests (5 items) all pass

---

## 6. Execution Strategy

- Tests written **in parallel with development** (not after)
- Each ADR-009 Phase → corresponding test module delivered same day
- Phase 1 (StructuredAlert) → `test_alert_models.py`
- Phase 2 (Parsers) → `test_alert_parsers.py`
- Phase 3 (SkillBridge) → `test_skill_bridge.py`
- Phase 4 (Agent Integration) → `test_agent_skill_integration.py`
- Phase 5 (Knowledge Flywheel) → `test_knowledge_flywheel.py`
- Phase 6-7 (E2E) → `test_e2e_channel_rca.py`

---

*Tester — 2026-03-08 03:01 UTC*
