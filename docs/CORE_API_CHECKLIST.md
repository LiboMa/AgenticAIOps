# Core API Checklist — Frontend Coverage Target ≥80%

> **Author**: Architect | **Date**: 2026-03-08
> **Total Core APIs**: 55 | **Target**: ≥44 (80%)
> **Current**: ~15 (27%) → Phase 1: ~22 → Phase 2: ~38 → Phase 3: ≥44

## 🏠 Ops Hub (20 APIs)

| # | Method | Endpoint | View | Status |
|---|--------|----------|------|--------|
| 1 | GET | `/api/health-issues` | HealthIssueList | ✅ Phase 1 |
| 2 | GET | `/api/health-issues/{id}` | HealthIssueDetail | Phase 2 |
| 3 | PATCH | `/api/health-issues/{id}/status` | StatusUpdate | Phase 2 |
| 4 | POST | `/api/health-issues/{id}/fix-plan` | FixPlan | Phase 3 |
| 5 | POST | `/api/health-issues/{id}/force-close` | ForceClose | Phase 3 |
| 6 | GET | `/api/alert/feed` | AlertFeed | ✅ Phase 1 |
| 7 | GET | `/api/alert/stats` | AlertStats | ✅ Phase 1 |
| 8 | GET | `/api/incident/stats` | IncidentStats | ✅ Phase 1 |
| 9 | GET | `/api/incident/list` | IncidentList | Phase 2 |
| 10 | GET | `/api/incident/{id}` | IncidentDetail | Phase 2 |
| 11 | GET | `/api/sop/list` | SOPQuickActions | Phase 2 |
| 12 | GET | `/api/sop/{id}` | SOPDetail | Phase 2 |
| 13 | POST | `/api/sop/execute` | SOPExecute | Phase 2 |
| 14 | POST | `/api/sop/suggest` | SOPSuggest | Phase 3 |
| 15 | GET | `/api/proactive/status` | ProactiveBadge | Phase 2 |
| 16 | GET | `/api/proactive/results` | ProactiveResults | Phase 3 |
| 17 | POST | `/api/proactive/trigger` | ManualTrigger | Phase 3 |
| 18 | GET | `/api/issues/dashboard` | DashboardStats | ✅ (existing) |
| 19 | GET | `/api/events/collect` | EventsFeed | Phase 2 |
| 20 | GET | `/api/health/status` | HealthBadge | ✅ (existing) |

## 🔍 Diagnose (16 APIs)

| # | Method | Endpoint | View | Status |
|---|--------|----------|------|--------|
| 21 | GET | `/api/topology/vpc/{id}` | TopologyGraph | Phase 2 |
| 22 | GET | `/api/topology/vpc/{id}/propagation` | PropagationOverlay | Phase 2 |
| 23 | GET | `/api/topology/vpc/{id}/changes` | ChangeTimeline | Phase 2 |
| 24 | GET | `/api/topology/vpc/{id}/impact/{rid}` | ImpactAnalysis | Phase 3 |
| 25 | GET | `/api/topology/region` | RegionOverview | Phase 3 |
| 26 | GET | `/api/rca/reports` | RCAList | Phase 2 |
| 27 | GET | `/api/rca/reports/{id}` | RCAViewer | Phase 2 |
| 28 | POST | `/api/rca/analyze` | TriggerRCA | Phase 2 |
| 29 | POST | `/api/rca/deep` | DeepRCA | Phase 3 |
| 30 | POST | `/api/rca/feedback` | RCAFeedback | Phase 3 |
| 31 | GET | `/api/rca/bridge/stats` | BridgeStats | Phase 3 |
| 32 | POST | `/api/knowledge/search` | SimilarCases | Phase 2 |
| 33 | GET | `/api/knowledge/patterns` | PatternList | Phase 2 |
| 34 | GET | `/api/knowledge/stats` | KnowledgeStats | Phase 3 |
| 35 | POST | `/api/knowledge/learn` | LearnTrigger | Phase 3 |
| 36 | POST | `/api/knowledge/feedback` | KBFeedback | Phase 3 |

## 💬 Agent Console (8 APIs)

| # | Method | Endpoint | View | Status |
|---|--------|----------|------|--------|
| 37 | POST | `/api/chat` | ChatSend | ✅ (existing) |
| 38 | POST | `/api/chat/upload` | FileUpload | ✅ (existing) |
| 39 | GET | `/api/safety/approvals` | SafetyPanel | Phase 2 |
| 40 | POST | `/api/safety/approve/{id}` | ApproveAction | Phase 2 |
| 41 | POST | `/api/safety/reject/{id}` | RejectAction | Phase 2 |
| 42 | GET | `/api/safety/stats` | SafetyStats | Phase 3 |
| 43 | GET | `/api/detect/status` | DetectBadge | Phase 2 |
| 44 | GET | `/api/notifications/status` | NotifStatus | Phase 3 |

## ⚙️ Config (11 APIs)

| # | Method | Endpoint | View | Status |
|---|--------|----------|------|--------|
| 45 | GET | `/api/registry/status` | SkillsStatus | Phase 2 |
| 46 | GET | `/api/plugins` | PluginList | ✅ (existing) |
| 47 | POST | `/api/plugins` | AddPlugin | ✅ (existing) |
| 48 | POST | `/api/plugins/{id}/enable` | EnablePlugin | ✅ (existing) |
| 49 | POST | `/api/plugins/{id}/disable` | DisablePlugin | ✅ (existing) |
| 50 | GET | `/api/runbooks` | RunbookList | Phase 2 |
| 51 | GET | `/api/runbooks/executions` | ExecHistory | Phase 3 |
| 52 | POST | `/api/proactive/interval` | SetInterval | Phase 3 |
| 53 | POST | `/api/proactive/toggle` | ToggleProactive | Phase 3 |
| 54 | GET | `/api/health/check` | SystemHealth | ✅ (existing) |
| 55 | GET | `/api/health/history` | HealthHistory | Phase 3 |

---

## Summary

| Phase | APIs Added | Cumulative | Coverage |
|-------|-----------|------------|----------|
| Current | 15 | 15 | 27% |
| Phase 1 ✅ | +7 | 22 | 40% |
| Phase 2 | +16 | 38 | 69% |
| Phase 3 | +17 | 55 | 100% |

**80% target = 44 APIs → achievable by end of Phase 2 + partial Phase 3**
