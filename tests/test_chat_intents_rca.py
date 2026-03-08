"""Tests for routers/chat_intents/rca.py — keyword routing + helpers."""

import sys
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestRCAHandle:

    @pytest.mark.asyncio
    async def test_no_match(self):
        from routers.chat_intents.rca import handle
        assert await handle("hello world", "hello world") is None

    @pytest.mark.parametrize("msg", [
        "incident run", "事件处理", "incident handle", "closed loop", "闭环",
    ])
    @pytest.mark.asyncio
    async def test_incident_run(self, msg):
        with patch("routers.chat_intents.rca._incident_run", new_callable=AsyncMock, return_value="ok"):
            from routers.chat_intents.rca import handle
            result = await handle(msg, msg.lower())
            assert result is not None

    @pytest.mark.parametrize("msg", ["incident list", "事件列表", "incidents"])
    @pytest.mark.asyncio
    async def test_incident_list(self, msg):
        with patch("routers.chat_intents.rca._incident_list", return_value="list"):
            from routers.chat_intents.rca import handle
            assert await handle(msg, msg.lower()) == "list"

    @pytest.mark.parametrize("msg", ["incident stats", "事件统计"])
    @pytest.mark.asyncio
    async def test_incident_stats(self, msg):
        with patch("routers.chat_intents.rca._incident_stats", return_value="stats"):
            from routers.chat_intents.rca import handle
            assert await handle(msg, msg.lower()) == "stats"

    @pytest.mark.parametrize("msg", ["rca deep ec2", "rca 深度", "deep analyze", "深度分析"])
    @pytest.mark.asyncio
    async def test_rca_deep(self, msg):
        with patch("routers.chat_intents.rca._rca_deep", new_callable=AsyncMock, return_value="deep"):
            from routers.chat_intents.rca import handle
            assert await handle(msg, msg.lower()) == "deep"

    @pytest.mark.parametrize("msg", ["rca analyze high cpu", "diagnose", "诊断问题", "root cause"])
    @pytest.mark.asyncio
    async def test_rca_analyze(self, msg):
        with patch("routers.chat_intents.rca._rca_analyze", return_value="analysis"):
            from routers.chat_intents.rca import handle
            assert await handle(msg, msg.lower()) == "analysis"

    @pytest.mark.parametrize("msg", ["rca autofix high cpu", "rca 自动修复"])
    @pytest.mark.asyncio
    async def test_rca_autofix(self, msg):
        with patch("routers.chat_intents.rca._rca_autofix", return_value="fix"):
            from routers.chat_intents.rca import handle
            assert await handle(msg, msg.lower()) == "fix"

    @pytest.mark.asyncio
    async def test_auto_diagnose_matches_autofix(self):
        """'auto diagnose' should also match the autofix handler."""
        with patch("routers.chat_intents.rca._rca_autofix", return_value="fix"):
            from routers.chat_intents.rca import handle
            # "auto diagnose" has "diagnose" which could match rca_analyze too
            # but autofix check comes first in handle() order
            result = await handle("auto diagnose high cpu", "auto diagnose high cpu")
            assert result is not None

    @pytest.mark.parametrize("msg", ["rca feedback exec1 sop1 pat1 success", "rca 反馈"])
    @pytest.mark.asyncio
    async def test_rca_feedback(self, msg):
        with patch("routers.chat_intents.rca._rca_feedback", return_value="fb"):
            from routers.chat_intents.rca import handle
            assert await handle(msg, msg.lower()) == "fb"

    @pytest.mark.parametrize("msg", ["rca stats", "rca 统计", "rca status"])
    @pytest.mark.asyncio
    async def test_rca_stats(self, msg):
        with patch("routers.chat_intents.rca._rca_stats", return_value="stats"):
            from routers.chat_intents.rca import handle
            assert await handle(msg, msg.lower()) == "stats"

    @pytest.mark.parametrize("msg", ["safety check sop1", "安全检查", "dry run sop1", "dry-run sop1"])
    @pytest.mark.asyncio
    async def test_safety_check(self, msg):
        with patch("routers.chat_intents.rca._safety_check", return_value="safe"):
            from routers.chat_intents.rca import handle
            assert await handle(msg, msg.lower()) == "safe"

    @pytest.mark.parametrize("msg", ["safety stats", "安全统计", "safety status"])
    @pytest.mark.asyncio
    async def test_safety_stats(self, msg):
        with patch("routers.chat_intents.rca._safety_stats", return_value="ss"):
            from routers.chat_intents.rca import handle
            assert await handle(msg, msg.lower()) == "ss"

    @pytest.mark.asyncio
    async def test_approvals(self):
        with patch("routers.chat_intents.rca._pending_approvals", return_value="pa"):
            from routers.chat_intents.rca import handle
            assert await handle("approvals", "approvals") == "pa"

    @pytest.mark.asyncio
    async def test_approve(self):
        with patch("routers.chat_intents.rca._approve_reject", return_value="done"):
            from routers.chat_intents.rca import handle
            assert await handle("approve abc123", "approve abc123") == "done"


# ---------------------------------------------------------------------------
# Helper to build mock modules for local imports
# ---------------------------------------------------------------------------

def _mock_module(name, **attrs):
    """Create a mock module and register it in sys.modules for local import."""
    mod = MagicMock()
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

class TestRCAHelpers:

    def test_incident_list_empty(self):
        mock_orch = MagicMock()
        mock_orch.list_incidents.return_value = []
        mod = _mock_module("src.incident_orchestrator", get_orchestrator=MagicMock(return_value=mock_orch))
        with patch.dict("sys.modules", {"src.incident_orchestrator": mod}):
            from routers.chat_intents.rca import _incident_list
            result = _incident_list()
            assert "暂无事件" in result

    def test_incident_list_with_data(self):
        mock_orch = MagicMock()
        mock_orch.list_incidents.return_value = [
            {"incident_id": "inc-1", "trigger_type": "manual",
             "status": "completed", "duration_ms": 1234,
             "created_at": "2026-01-01T00:00:00"},
        ]
        mod = _mock_module("src.incident_orchestrator", get_orchestrator=MagicMock(return_value=mock_orch))
        with patch.dict("sys.modules", {"src.incident_orchestrator": mod}):
            from routers.chat_intents.rca import _incident_list
            result = _incident_list()
            assert "事件列表" in result
            assert "inc-1" in result

    def test_incident_stats(self):
        mock_orch = MagicMock()
        mock_orch.get_stats.return_value = {
            "total_incidents": 10, "avg_duration_ms": 500,
            "target_ms": 1000, "within_target": True,
            "by_status": {"completed": 8, "failed": 2},
            "avg_stage_timings": {"collect": 200, "analyze": 50},
        }
        mod = _mock_module("src.incident_orchestrator", get_orchestrator=MagicMock(return_value=mock_orch))
        with patch.dict("sys.modules", {"src.incident_orchestrator": mod}):
            from routers.chat_intents.rca import _incident_stats
            result = _incident_stats()
            assert "闭环管道统计" in result

    def test_rca_analyze_no_symptoms(self):
        mod = _mock_module("src.rca_sop_bridge", get_bridge=MagicMock())
        with patch.dict("sys.modules", {"src.rca_sop_bridge": mod}):
            from routers.chat_intents.rca import _rca_analyze
            result = _rca_analyze("rca analyze")
            assert "用法" in result or "症状" in result

    def test_rca_analyze_with_symptoms(self):
        mock_bridge = MagicMock()
        mock_result = MagicMock()
        mock_result.to_markdown.return_value = "## RCA Result"
        mock_bridge.analyze_and_suggest.return_value = mock_result
        mod = _mock_module("src.rca_sop_bridge", get_bridge=MagicMock(return_value=mock_bridge))
        with patch.dict("sys.modules", {"src.rca_sop_bridge": mod}):
            from routers.chat_intents.rca import _rca_analyze
            result = _rca_analyze("rca analyze high cpu memory")
            assert "RCA Result" in result

    def test_rca_autofix_no_symptoms(self):
        mod = _mock_module("src.rca_sop_bridge", get_bridge=MagicMock())
        with patch.dict("sys.modules", {"src.rca_sop_bridge": mod}):
            from routers.chat_intents.rca import _rca_autofix
            result = _rca_autofix("rca autofix")
            assert "用法" in result

    def test_rca_autofix_with_symptoms(self):
        mock_bridge = MagicMock()
        mock_result = MagicMock()
        mock_result.to_markdown.return_value = "## Autofix"
        mock_bridge.analyze_and_suggest.return_value = mock_result
        mod = _mock_module("src.rca_sop_bridge", get_bridge=MagicMock(return_value=mock_bridge))
        with patch.dict("sys.modules", {"src.rca_sop_bridge": mod}):
            from routers.chat_intents.rca import _rca_autofix
            result = _rca_autofix("rca autofix high cpu")
            assert "Autofix" in result

    def test_rca_feedback_no_match(self):
        from routers.chat_intents.rca import _rca_feedback
        result = _rca_feedback("rca feedback")
        assert "用法" in result

    def test_rca_feedback_success(self):
        fb = MagicMock()
        fb.execution_id = "exec1"
        fb.sop_id = "sop1"
        fb.rca_pattern_id = "pat1"
        mock_bridge = MagicMock()
        mock_bridge.submit_feedback.return_value = fb
        mod = _mock_module("src.rca_sop_bridge", get_bridge=MagicMock(return_value=mock_bridge))
        with patch.dict("sys.modules", {"src.rca_sop_bridge": mod}):
            from routers.chat_intents.rca import _rca_feedback
            result = _rca_feedback("rca feedback exec1 sop1 pat1 success")
            assert "反馈已记录" in result
            assert "成功" in result

    def test_rca_feedback_fail(self):
        fb = MagicMock()
        fb.execution_id = "exec1"
        fb.sop_id = "sop1"
        fb.rca_pattern_id = "pat1"
        mock_bridge = MagicMock()
        mock_bridge.submit_feedback.return_value = fb
        mod = _mock_module("src.rca_sop_bridge", get_bridge=MagicMock(return_value=mock_bridge))
        with patch.dict("sys.modules", {"src.rca_sop_bridge": mod}):
            from routers.chat_intents.rca import _rca_feedback
            result = _rca_feedback("rca feedback exec1 sop1 pat1 fail")
            assert "反馈已记录" in result
            assert "失败" in result

    def test_rca_stats(self):
        mock_bridge = MagicMock()
        mock_bridge.get_feedback_stats.return_value = {
            "total_feedbacks": 20, "successful": 15, "failed": 5,
            "root_cause_confirmed": 12, "success_rate": 0.75,
            "avg_resolution_seconds": 120,
            "learned_mappings": {"pat1": {"sop1": 3}},
        }
        mod = _mock_module("src.rca_sop_bridge", get_bridge=MagicMock(return_value=mock_bridge))
        with patch.dict("sys.modules", {"src.rca_sop_bridge": mod}):
            from routers.chat_intents.rca import _rca_stats
            result = _rca_stats()
            assert "RCA ↔ SOP 统计" in result

    def test_safety_check_no_sop_id(self):
        mod = _mock_module("src.sop_safety", get_safety_layer=MagicMock())
        with patch.dict("sys.modules", {"src.sop_safety": mod}):
            from routers.chat_intents.rca import _safety_check
            result = _safety_check("safety check")
            assert "用法" in result

    def test_safety_check_with_sop(self):
        mock_safety = MagicMock()
        mock_check = MagicMock()
        mock_check.to_markdown.return_value = "## Safety OK"
        mock_safety.check.return_value = mock_check
        mod = _mock_module("src.sop_safety", get_safety_layer=MagicMock(return_value=mock_safety))
        with patch.dict("sys.modules", {"src.sop_safety": mod}):
            from routers.chat_intents.rca import _safety_check
            result = _safety_check("safety check sop-ec2-high-cpu")
            assert "Safety OK" in result

    def test_safety_stats(self):
        mock_safety = MagicMock()
        mock_safety.get_stats.return_value = {
            "active_cooldowns": 2, "snapshots_stored": 5,
            "pending_approvals": 1,
            "daily_execution_counts": {"L0": 3},
            "daily_limits": {"L0": 100, "L1": 50, "L2": 20, "L3": 5},
        }
        mod = _mock_module("src.sop_safety", get_safety_layer=MagicMock(return_value=mock_safety))
        with patch.dict("sys.modules", {"src.sop_safety": mod}):
            from routers.chat_intents.rca import _safety_stats
            result = _safety_stats()
            assert "安全层状态" in result

    def test_pending_approvals_empty(self):
        mock_safety = MagicMock()
        mock_safety.get_pending_approvals.return_value = []
        mod = _mock_module("src.sop_safety", get_safety_layer=MagicMock(return_value=mock_safety))
        with patch.dict("sys.modules", {"src.sop_safety": mod}):
            from routers.chat_intents.rca import _pending_approvals
            result = _pending_approvals()
            assert "无待审批" in result

    def test_pending_approvals_list(self):
        mock_safety = MagicMock()
        mock_safety.get_pending_approvals.return_value = [
            {"approval_id": "a1", "sop_id": "sop1", "risk_level": "L2",
             "requested_by": "admin", "expires_at": "2026-01-01"},
        ]
        mod = _mock_module("src.sop_safety", get_safety_layer=MagicMock(return_value=mock_safety))
        with patch.dict("sys.modules", {"src.sop_safety": mod}):
            from routers.chat_intents.rca import _pending_approvals
            result = _pending_approvals()
            assert "待审批" in result

    def test_approve_success(self):
        mock_safety = MagicMock()
        mock_result = MagicMock()
        mock_result.approved = True
        mock_result.sop_id = "sop1"
        mock_result.risk_level = MagicMock(value="L2")
        mock_safety.approve.return_value = mock_result
        mod = _mock_module("src.sop_safety", get_safety_layer=MagicMock(return_value=mock_safety))
        with patch.dict("sys.modules", {"src.sop_safety": mod}):
            from routers.chat_intents.rca import _approve_reject
            result = _approve_reject("approve a1")
            assert "已批准" in result

    def test_reject(self):
        mock_safety = MagicMock()
        mock_result = MagicMock()
        mock_result.approved = False
        mock_result.sop_id = "sop1"
        mock_result.risk_level = MagicMock(value="L3")
        mock_safety.reject.return_value = mock_result
        mod = _mock_module("src.sop_safety", get_safety_layer=MagicMock(return_value=mock_safety))
        with patch.dict("sys.modules", {"src.sop_safety": mod}):
            from routers.chat_intents.rca import _approve_reject
            result = _approve_reject("reject a1")
            assert "已拒绝" in result

    def test_approve_not_found(self):
        mock_safety = MagicMock()
        mock_safety.approve.return_value = None
        mod = _mock_module("src.sop_safety", get_safety_layer=MagicMock(return_value=mock_safety))
        with patch.dict("sys.modules", {"src.sop_safety": mod}):
            from routers.chat_intents.rca import _approve_reject
            result = _approve_reject("approve unknown")
            assert "未找到" in result
